"""
Sarvam AI Client for STT, LLM, and Bulbul V4 Flash TTS with HTTP/2 support.
"""
import json
import logging
from typing import Dict, Any, Tuple, Optional, AsyncIterator
import httpx
from app.config import (
    SARVAM_API_KEY,
    SARVAM_TTS_ENDPOINT,
    SARVAM_STT_ENDPOINT,
    SARVAM_LLM_ENDPOINT,
    DEFAULT_LLM_MODEL,
    DEFAULT_TTS_MODEL,
    DEFAULT_STT_MODEL,
)

logger = logging.getLogger("awaaz.sarvam")


def auto_detect_language(text: str, fallback: str = "en-IN") -> str:
    """Detect Indian script or return fallback ISO code for Sarvam TTS."""
    for ch in text:
        cp = ord(ch)
        if 0x0900 <= cp <= 0x097F:
            return "hi-IN"
        if 0x0A80 <= cp <= 0x0AFF:
            return "gu-IN"
        if 0x0980 <= cp <= 0x09FF:
            return "bn-IN"
        if 0x0B80 <= cp <= 0x0BFF:
            return "ta-IN"
        if 0x0C00 <= cp <= 0x0C7F:
            return "te-IN"
        if 0x0C80 <= cp <= 0x0CFF:
            return "kn-IN"
        if 0x0D00 <= cp <= 0x0D7F:
            return "ml-IN"
        if 0x0A00 <= cp <= 0x0A7F:
            return "pa-IN"
        if 0x0B00 <= cp <= 0x0B7F:
            return "od-IN"
        if 0x0600 <= cp <= 0x06FF:
            return "ur-IN"
    return fallback if fallback and fallback != "unknown" else "en-IN"


class SarvamClient:
    """Async client with HTTP/2 support for low-latency streaming."""

    def __init__(self, api_key: str = SARVAM_API_KEY):
        self.api_key = api_key
        self._client: Optional[httpx.AsyncClient] = None

    def get_or_create_client(self) -> httpx.AsyncClient:
        """Returns or creates an HTTP/2 keep-alive client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                http2=True,
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=50, keepalive_expiry=120.0),
                timeout=httpx.Timeout(20.0, connect=3.0),
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP/2 connection pool cleanly."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    @property
    def _headers(self) -> Dict[str, str]:
        return {"api-subscription-key": self.api_key}

    async def speech_to_text(
        self,
        audio_bytes: bytes,
        filename: str = "audio.wav",
        mime_type: str = "audio/wav",
        model: str = DEFAULT_STT_MODEL,
        custom_client: Optional[httpx.AsyncClient] = None,
    ) -> Tuple[str, str]:
        if not audio_bytes:
            return "", "en-IN"

        client = custom_client or self.get_or_create_client()
        files = {"file": (filename, audio_bytes, mime_type)}
        data = {"model": model}

        resp = await client.post(SARVAM_STT_ENDPOINT, headers=self._headers, files=files, data=data)
        if resp.status_code != 200:
            logger.error(f"STT Error {resp.status_code}: {resp.text}")
            raise RuntimeError(f"STT failed ({resp.status_code}): {resp.text}")

        res = resp.json()
        transcript = res.get("transcript", "").strip()
        lang = res.get("language_code", "en-IN")
        logger.info(f"STT [{lang}]: '{transcript}'")
        return transcript, lang

    async def stream_chat_completion(
        self,
        messages: list,
        temperature: float = 0.7,
        max_tokens: int = 200,
        model: str = DEFAULT_LLM_MODEL,
        custom_client: Optional[httpx.AsyncClient] = None,
    ) -> AsyncIterator[str]:
        """Stream tokens via SSE over HTTP/2."""
        headers = {**self._headers, "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        client = custom_client or self.get_or_create_client()
        async with client.stream("POST", SARVAM_LLM_ENDPOINT, headers=headers, json=payload) as resp:
            if resp.status_code != 200:
                err_body = await resp.aread()
                logger.error(f"LLM Stream Error {resp.status_code}: {err_body}")
                yield "I hear you."
                return

            async for line in resp.aiter_lines():
                line = line.strip()
                if not line or line == "data: [DONE]":
                    continue
                if line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])
                        delta = data.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except Exception:
                        continue

    async def text_to_speech(
        self,
        text: str,
        persona: Dict[str, Any],
        model: str = DEFAULT_TTS_MODEL,
        target_language_code: Optional[str] = None,
        custom_client: Optional[httpx.AsyncClient] = None,
    ) -> str:
        clean_text = text.strip()
        if not clean_text:
            clean_text = "..."

        fb = target_language_code or persona.get("target_language_code", "en-IN")
        target_lang = auto_detect_language(clean_text, fallback=fb)

        headers = {**self._headers, "Content-Type": "application/json"}
        payload = {
            "inputs": [clean_text],
            "target_language_code": target_lang,
            "speaker": persona.get("speaker", "simran_en_conversation"),
            "model": model,
            "pace": persona.get("pace", 1.15),
            "enable_preprocessing": True,
        }

        client = custom_client or self.get_or_create_client()
        resp = await client.post(SARVAM_TTS_ENDPOINT, headers=headers, json=payload)
        if resp.status_code != 200:
            logger.error(f"TTS Error {resp.status_code}: {resp.text}")
            raise RuntimeError(f"TTS failed ({resp.status_code}): {resp.text}")

        res = resp.json()
        audios = res.get("audios", [])
        if not audios or not audios[0]:
            raise RuntimeError("Empty audio returned")
        return audios[0]


sarvam_client = SarvamClient()

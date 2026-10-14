"""
Awaaz — Multi-Agent Group Discussion Voice AI Backend with HTTP/2 & Streaming Clause TTS.
"""
import re
import json
import base64
import logging
from pathlib import Path
import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.websockets import WebSocketState

from app.config import SARVAM_API_KEY
from app.personas import list_personas, get_persona, list_rooms, get_room, DEFAULT_ROOM_ID
from app.session import session_manager
from app.controller import select_speakers_for_turn, check_interruption_intent, detect_addressed_personas, VOICE_CATALOG
from app.sarvam_client import sarvam_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("awaaz.main")

app = FastAPI(title="Awaaz — Multi-Agent Voice Roundtable", version="2.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
STATIC_DIR = Path(__file__).resolve().parent / "static"


def clean_spoken_text(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"^\[.*?\]:?\s*", "", text)
    cleaned = re.sub(r"^[A-Za-z\s]+:\s*", "", cleaned)
    return re.sub(r"[*_#`]", "", cleaned).strip()


async def safe_send(ws: WebSocket, payload: dict) -> bool:
    try:
        if ws.client_state == WebSocketState.CONNECTED:
            await ws.send_json(payload)
            return True
    except Exception:
        pass
    return False


@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "sarvam_configured": bool(SARVAM_API_KEY), "http2": True}

@app.get("/api/rooms")
async def get_rooms_endpoint():
    return {"rooms": list_rooms()}

@app.get("/api/personas")
async def get_personas_endpoint():
    return {"personas": list_personas()}

@app.post("/api/reset")
async def reset_session(session_id: str = "default_session"):
    session_manager.reset(session_id)
    return {"status": "reset", "session_id": session_id}


@app.websocket("/ws/voice")
async def websocket_voice_endpoint(websocket: WebSocket):
    await websocket.accept()
    session_id = websocket.query_params.get("session_id", "default_session")
    sess = session_manager.get_or_create(session_id)
    
    # Open dedicated HTTP/2 connection pool for this live session
    session_http = httpx.AsyncClient(
        http2=True,
        limits=httpx.Limits(max_keepalive_connections=20, max_connections=40, keepalive_expiry=120.0),
        timeout=httpx.Timeout(20.0, connect=3.0),
    )
    turn_cancel_flag = False

    try:
        while True:
            raw_msg = await websocket.receive_text()
            data = json.loads(raw_msg)
            msg_type = data.get("type", "")

            if msg_type == "barge_in":
                turn_cancel_flag = True
                await safe_send(websocket, {"type": "interrupted"})
                continue
            if msg_type == "set_room":
                new_room = data.get("room_id", DEFAULT_ROOM_ID)
                sess.set_room(new_room)
                await safe_send(websocket, {
                    "type": "room_changed", "room": get_room(new_room),
                    "agenda": sess.get_current_agenda(), "user_name": sess.user_name,
                    "user_role": sess.get_user_role_in_room(),
                })
                continue
            if msg_type == "set_agenda":
                new_agenda = data.get("agenda", "").strip()
                r_id = data.get("room_id", sess.room_id)
                if new_agenda:
                    sess.set_agenda(r_id, new_agenda)
                await safe_send(websocket, {"type": "agenda_updated", "room_id": r_id, "agenda": sess.get_current_agenda()})
                continue
            if msg_type == "set_user_name":
                new_name = data.get("user_name", "").strip()
                if new_name:
                    sess.set_user_name(new_name)
                await safe_send(websocket, {"type": "user_profile_updated", "user_name": sess.user_name, "role": sess.get_user_role_in_room()})
                continue
            if msg_type == "reset":
                sess.clear()
                await safe_send(websocket, {"type": "system", "message": "Memory cleared."})
                continue

            user_text = ""
            detected_lang = "en-IN"

            detected_lang = "en-IN"
            if msg_type == "audio":
                audio_b64 = data.get("audio_base64", "")
                if not audio_b64:
                    continue
                try:
                    transcript, detected_lang = await sarvam_client.speech_to_text(
                        audio_bytes=base64.b64decode(audio_b64),
                        custom_client=session_http,
                    )
                    user_text = transcript.strip()
                except Exception as e:
                    logger.error(f"STT error: {e}")
                    await safe_send(websocket, {"type": "status", "status": "listening"})
                    continue

            elif msg_type == "text":
                user_text = data.get("text", "").strip()
                detected_lang = "en-IN"

            if not user_text or len(user_text) < 2:
                await safe_send(websocket, {"type": "status", "status": "listening"})
                continue

            if check_interruption_intent(user_text):
                await safe_send(websocket, {"type": "interrupted", "text": "Stopped."})
                continue

            await safe_send(websocket, {
                "type": "user_speech",
                "text": user_text,
                "speaker_name": sess.user_name,
                "role": sess.get_user_role_in_room(),
                "lang": detected_lang,
            })
            sess.add_user_speech(user_text, detected_lang)

            speaking_personas = select_speakers_for_turn(user_text, sess)
            turn_cancel_flag = False
            await safe_send(websocket, {"type": "turn_plan", "speakers": speaking_personas})

            idx = 0
            while idx < len(speaking_personas):
                if turn_cancel_flag or websocket.client_state != WebSocketState.CONNECTED:
                    break
                p_id = speaking_personas[idx]
                idx += 1

                persona = get_persona(p_id)
                await safe_send(websocket, {
                    "type": "agent_start",
                    "speaker_id": p_id,
                    "speaker_name": persona["name"],
                    "role": persona["role"],
                })

                llm_messages = sess.build_persona_llm_messages(p_id)
                full_turn_text, clause_buffer = "", ""

                async def emit_speech(phrase: str):
                    if not phrase or turn_cancel_flag:
                        return
                    audio_b64 = await sarvam_client.text_to_speech(
                        phrase, persona, custom_client=session_http
                    )
                    if not turn_cancel_flag and websocket.client_state == WebSocketState.CONNECTED:
                        await safe_send(websocket, {
                            "type": "agent_speech",
                            "speaker_id": p_id,
                            "speaker_name": persona["name"],
                            "role": persona["role"],
                            "text": phrase,
                            "audio_base64": audio_b64,
                        })

                try:
                    async for token in sarvam_client.stream_chat_completion(
                        messages=llm_messages, custom_client=session_http
                    ):
                        if turn_cancel_flag or websocket.client_state != WebSocketState.CONNECTED:
                            break
                        clause_buffer += token
                        full_turn_text += token

                        has_end = any(p in clause_buffer for p in [".", "!", "?", "।", "\n"])
                        if has_end and len(clause_buffer.strip().split()) >= 3:
                            sentence = clean_spoken_text(clause_buffer)
                            clause_buffer = ""
                            if sentence and len(sentence) > 2:
                                await emit_speech(sentence)

                    if clause_buffer and not turn_cancel_flag:
                        rem = clean_spoken_text(clause_buffer)
                        if rem and len(rem) > 1:
                            await emit_speech(rem)

                    if full_turn_text and not turn_cancel_flag:
                        turn_clean = clean_spoken_text(full_turn_text)
                        sess.add_persona_speech(p_id, turn_clean)
                        # Only queue peer if speaker directly asks them a question, never looping back
                        if len(speaking_personas) == 1 and "?" in turn_clean:
                            current_room = get_room(sess.room_id)
                            peers = [pid for pid in current_room["persona_ids"] if pid != p_id]
                            for peer_id in detect_addressed_personas(turn_clean, allowed_personas=peers):
                                if peer_id not in speaking_personas:
                                    speaking_personas.append(peer_id)
                                    await safe_send(websocket, {"type": "turn_plan", "speakers": speaking_personas})
                                    break
                except Exception as e:
                    logger.error(f"Turn error for {p_id}: {e}")
                await safe_send(websocket, {"type": "agent_done", "speaker_id": p_id})
            await safe_send(websocket, {"type": "status", "status": "listening"})
    except (WebSocketDisconnect, RuntimeError):
        logger.info(f"WebSocket closed: session {session_id}")
    finally:
        await session_http.aclose()

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    @app.get("/")
    async def serve_index():
        return FileResponse(STATIC_DIR / "index.html")

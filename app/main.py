"""
Awaaz — Multi-Agent Group Discussion Voice AI Backend with HTTP/2 & Pipelined Streaming TTS.
"""
import re
import json
import time
import base64
import asyncio
import logging
from pathlib import Path
from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.websockets import WebSocketState

from app.config import SARVAM_API_KEY
from app.personas import list_personas, get_persona, list_rooms, get_room, DEFAULT_ROOM_ID
from app.session import session_manager
from app.controller import (
    select_speakers_for_turn,
    check_interruption_intent,
    detect_addressed_personas,
    detect_peer_referral,
    VOICE_CATALOG,
)
from app.sarvam_client import sarvam_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("awaaz.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Pre-warm HTTP/2 connection pool to Sarvam AI on server startup."""
    logger.info("Initializing Awaaz: pre-warming Sarvam HTTP/2 connection pool...")
    asyncio.create_task(sarvam_client.warmup())
    yield
    await sarvam_client.close()


app = FastAPI(title="Awaaz — Multi-Agent Voice Roundtable", version="2.3.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
STATIC_DIR = Path(__file__).resolve().parent / "static"


def clean_spoken_text(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"^\[.*?\]:?\s*", "", text)
    cleaned = re.sub(r"^[A-Za-z\s]+:\s*", "", cleaned)
    return re.sub(r"[*_#`]", "", cleaned).strip()


def should_split_clause(buffer: str) -> bool:
    """
    Check if buffer has reached a complete sentence boundary.
    Never splits mid-sentence at commas or colons to preserve neural TTS prosody,
    intonation, and natural punctuation.
    """
    clean = buffer.strip()
    words = clean.split()
    cnt = len(words)
    if cnt < 3:
        return False
    # Only split on true sentence terminal punctuation marks
    if any(p in buffer for p in [".", "!", "?", "।", "\n"]):
        return True
    # Length safety fallback only if an unusually long run-on sentence exceeds 18 words
    if cnt >= 18:
        return True
    return False


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


@app.post("/api/prewarm")
async def prewarm_endpoint():
    """Manual prewarm trigger for client initialization."""
    success = await sarvam_client.warmup()
    return {"status": "prewarmed", "success": success}


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

    # Dedicated HTTP/2 connection pool for this live session
    session_http = httpx.AsyncClient(
        http2=True,
        limits=httpx.Limits(max_keepalive_connections=30, max_connections=60, keepalive_expiry=180.0),
        timeout=httpx.Timeout(20.0, connect=3.0),
    )
    # Pre-warm session connection in background immediately
    asyncio.create_task(sarvam_client.warmup(session_http))

    active_turn_task: Optional[asyncio.Task] = None
    active_turn_cancel: Optional[asyncio.Event] = None

    async def cancel_active_turn():
        nonlocal active_turn_task, active_turn_cancel
        if active_turn_task and not active_turn_task.done():
            if active_turn_cancel:
                active_turn_cancel.set()
            active_turn_task.cancel()
            try:
                await active_turn_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"Error cancelling active turn: {e}")
            active_turn_task = None

    async def execute_agent_turn(u_text: str, u_lang: str, cancel_ev: asyncio.Event):
        try:
            await safe_send(websocket, {
                "type": "user_speech",
                "text": u_text,
                "speaker_name": sess.user_name,
                "role": sess.get_user_role_in_room(),
                "lang": u_lang,
            })
            sess.add_user_speech(u_text, u_lang)

            speaking_personas = select_speakers_for_turn(u_text, sess)
            await safe_send(websocket, {"type": "turn_plan", "speakers": speaking_personas})

            idx = 0
            preceding_speaker_id = None
            preceding_speaker_name = None
            preceding_turn_text = None
            addressed_by_peer = False

            while idx < len(speaking_personas):
                if cancel_ev.is_set() or websocket.client_state != WebSocketState.CONNECTED:
                    break
                p_id = speaking_personas[idx]
                idx += 1

                persona = get_persona(p_id)
                await safe_send(websocket, {
                    "type": "agent_start",
                    "speaker_id": p_id,
                    "speaker_name": persona["name"],
                    "role": persona["role"],
                    "turn_index": idx,
                    "total_turns": len(speaking_personas),
                })

                # Dynamic turn context for referencing colleagues
                turn_context = None
                if preceding_speaker_id:
                    peer_name_hint = get_persona(preceding_speaker_id).get("peer_name")
                    short_name = peer_name_hint or preceding_speaker_name.split()[0]
                    turn_context = {
                        "is_multi_turn_second_speaker": (len(speaking_personas) > 1 and not addressed_by_peer),
                        "preceding_speaker_id": preceding_speaker_id,
                        "preceding_speaker_name": preceding_speaker_name,
                        "preceding_short_name": short_name,
                        "preceding_turn_text": preceding_turn_text,
                        "addressed_by_peer": addressed_by_peer,
                    }

                llm_messages = sess.build_persona_llm_messages(p_id, turn_context=turn_context)

                # --- Pipelined Streaming TTS Architecture ---
                clause_tasks = []
                clause_queue: asyncio.Queue = asyncio.Queue()
                stream_done = asyncio.Event()
                turn_cancel_event = asyncio.Event()
                turn_start_time = time.perf_counter()
                first_token_time = None
                first_audio_time = None
                dispatched_clauses = 0

                async def tts_worker(seq: int, phrase: str):
                    try:
                        if cancel_ev.is_set() or turn_cancel_event.is_set():
                            return
                        audio_b64 = await sarvam_client.text_to_speech(phrase, persona, custom_client=session_http)
                        if not cancel_ev.is_set() and not turn_cancel_event.is_set():
                            await clause_queue.put((seq, phrase, audio_b64))
                    except Exception as err:
                        logger.error(f"TTS synthesis error for {p_id} seq {seq}: {err}")
                        if not cancel_ev.is_set() and not turn_cancel_event.is_set():
                            await clause_queue.put((seq, phrase, None))

                async def sender_worker():
                    nonlocal first_audio_time
                    expected_seq = 0
                    buffer_map = {}

                    while True:
                        if cancel_ev.is_set() or turn_cancel_event.is_set() or websocket.client_state != WebSocketState.CONNECTED:
                            break

                        if expected_seq in buffer_map:
                            seq, phrase, audio_b64 = buffer_map.pop(expected_seq)
                            if audio_b64 and not cancel_ev.is_set() and not turn_cancel_event.is_set():
                                if first_audio_time is None:
                                    first_audio_time = time.perf_counter()
                                    ttfa_ms = (first_audio_time - turn_start_time) * 1000
                                    logger.info(f"[{persona['name']}] TTFA: {ttfa_ms:.1f}ms")
                                    await safe_send(websocket, {
                                        "type": "latency_stats",
                                        "speaker_id": p_id,
                                        "ttfa_ms": round(ttfa_ms, 1),
                                    })
                                await safe_send(websocket, {
                                    "type": "agent_speech",
                                    "speaker_id": p_id,
                                    "speaker_name": persona["name"],
                                    "role": persona["role"],
                                    "text": phrase,
                                    "audio_base64": audio_b64,
                                    "seq": seq,
                                })
                            expected_seq += 1
                            continue

                        if stream_done.is_set() and expected_seq >= dispatched_clauses:
                            break

                        try:
                            item = await asyncio.wait_for(clause_queue.get(), timeout=0.08)
                            buffer_map[item[0]] = item
                        except asyncio.TimeoutError:
                            continue

                sender_task = asyncio.create_task(sender_worker())
                full_turn_text = ""
                clause_buffer = ""

                try:
                    async for token in sarvam_client.stream_chat_completion(
                        messages=llm_messages, custom_client=session_http
                    ):
                        if cancel_ev.is_set() or websocket.client_state != WebSocketState.CONNECTED:
                            turn_cancel_event.set()
                            break

                        if first_token_time is None:
                            first_token_time = time.perf_counter()
                            ttft_ms = (first_token_time - turn_start_time) * 1000
                            logger.info(f"[{persona['name']}] TTFT: {ttft_ms:.1f}ms")
                            await safe_send(websocket, {
                                "type": "latency_stats",
                                "speaker_id": p_id,
                                "ttft_ms": round(ttft_ms, 1),
                            })

                        clause_buffer += token
                        full_turn_text += token

                        if should_split_clause(clause_buffer):
                            sentence = clean_spoken_text(clause_buffer)
                            clause_buffer = ""
                            if sentence and len(sentence) >= 2:
                                task = asyncio.create_task(tts_worker(dispatched_clauses, sentence))
                                clause_tasks.append(task)
                                dispatched_clauses += 1

                    if clause_buffer and not cancel_ev.is_set() and not turn_cancel_event.is_set():
                        rem = clean_spoken_text(clause_buffer)
                        if rem and len(rem) >= 2:
                            task = asyncio.create_task(tts_worker(dispatched_clauses, rem))
                            clause_tasks.append(task)
                            dispatched_clauses += 1

                    stream_done.set()
                    await sender_task

                    if full_turn_text and not cancel_ev.is_set() and not turn_cancel_event.is_set():
                        turn_clean = clean_spoken_text(full_turn_text)
                        sess.add_persona_speech(p_id, turn_clean)
                        preceding_speaker_id = p_id
                        preceding_speaker_name = persona["name"]
                        preceding_turn_text = turn_clean

                        # Dynamic peer referral: did speaker invite or mention their colleague?
                        if len(speaking_personas) < 3:
                            referred = detect_peer_referral(turn_clean, current_speaker_id=p_id, room_id=sess.room_id)
                            if referred and referred not in speaking_personas:
                                speaking_personas.append(referred)
                                addressed_by_peer = True
                                await safe_send(websocket, {
                                    "type": "turn_plan",
                                    "speakers": speaking_personas,
                                    "peer_referral": True,
                                    "from_speaker": p_id,
                                    "to_speaker": referred,
                                })
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"Turn error for {p_id}: {e}")
                finally:
                    turn_cancel_event.set()
                    for t in clause_tasks:
                        if not t.done():
                            t.cancel()
                    if not sender_task.done():
                        sender_task.cancel()

                if not cancel_ev.is_set():
                    await safe_send(websocket, {"type": "agent_done", "speaker_id": p_id})

            if not cancel_ev.is_set():
                await safe_send(websocket, {"type": "status", "status": "listening"})
        except asyncio.CancelledError:
            logger.info("execute_agent_turn cancelled by interruption.")
        except Exception as e:
            logger.error(f"execute_agent_turn unexpected error: {e}")

    try:
        while True:
            raw_msg = await websocket.receive_text()
            data = json.loads(raw_msg)
            msg_type = data.get("type", "")

            if msg_type == "barge_in":
                await cancel_active_turn()
                await safe_send(websocket, {"type": "interrupted"})
                continue
            if msg_type == "set_room":
                await cancel_active_turn()
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
                await cancel_active_turn()
                sess.clear()
                await safe_send(websocket, {"type": "system", "message": "Memory cleared."})
                continue

            user_text = ""
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

            # Crucial: If an agent was speaking or generating, immediately interrupt and halt it!
            had_active = active_turn_task is not None and not active_turn_task.done()
            if had_active:
                logger.info(f"Interrupting active agent turn with new user input: '{user_text}'")
                await cancel_active_turn()
                await safe_send(websocket, {"type": "interrupted"})

            if check_interruption_intent(user_text):
                await safe_send(websocket, {"type": "interrupted", "text": "Stopped."})
                continue

            active_turn_cancel = asyncio.Event()
            active_turn_task = asyncio.create_task(
                execute_agent_turn(user_text, detected_lang, active_turn_cancel)
            )
    except (WebSocketDisconnect, RuntimeError):
        logger.info(f"WebSocket closed: session {session_id}")
    finally:
        await cancel_active_turn()
        await session_http.aclose()


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    async def serve_index():
        return FileResponse(STATIC_DIR / "index.html")


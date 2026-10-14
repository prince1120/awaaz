"""
Discussion Orchestrator & Turn-Taking Controller for Awaaz.
Coordinates deliberate, structured turn-taking for Office, Chill, and Family rooms.
"""
import re
import logging
from typing import Dict, Any, List, Optional, Tuple
from app.personas import ROUNDTABLE_PERSONAS, get_persona, get_room, DEFAULT_ROOM_ID
from app.session import GroupDiscussionSession

logger = logging.getLogger("awaaz.controller")

VOICE_CATALOG: Dict[str, Dict[str, Any]] = {
    p_id: {
        "speaker": p["speaker"],
        "lang": p["target_language_code"],
        "pace": p["pace"],
        "name": p["name"],
        "initials": p.get("initials", p["name"][:1]),
        "color": p["color"],
        "role": p["role"],
    }
    for p_id, p in ROUNDTABLE_PERSONAS.items()
}


def check_interruption_intent(user_text: str) -> bool:
    """Detect if the user said an explicit stop word."""
    if not user_text:
        return False
    text = user_text.lower().strip()
    stop_words = ["stop", "wait", "hold on", "pause", "shut up", "ruko", "chup", "bas", "thehro", "shant"]
    return any(re.search(rf"\b{re.escape(w)}\b", text) for w in stop_words)


def detect_addressed_personas(user_text: str, allowed_personas: Optional[List[str]] = None) -> List[str]:
    """Check if the user addressed characters and return them ordered by appearance."""
    if not user_text:
        return []

    text_lower = user_text.lower()
    matches = []
    pool = allowed_personas if allowed_personas else list(ROUNDTABLE_PERSONAS.keys())

    for p_id in pool:
        p = get_persona(p_id)
        for kw in p["keywords"]:
            m = re.search(rf"\b{re.escape(kw)}\b", text_lower)
            if m:
                matches.append((m.start(), p_id))
                break

    matches.sort(key=lambda x: x[0])
    return [p_id for _, p_id in matches]


def select_speakers_for_turn(
    user_text: str,
    session: Optional[GroupDiscussionSession] = None,
    room_id: Optional[str] = None,
) -> List[str]:
    """
    Selects EXACTLY who speaks:
    - If user mentions someone by name -> ONLY that person speaks.
    - If user explicitly says 'both of you' or 'everyone' -> all room members speak sequentially.
    - If open statement -> only ONE most relevant persona in the room speaks.
    """
    active_room_id = room_id or (session.room_id if session else DEFAULT_ROOM_ID)
    room = get_room(active_room_id)
    room_members = room["persona_ids"]

    if not user_text:
        return [room["default_speaker"]]

    text_lower = user_text.lower().strip()

    # 1. Direct address check
    explicit = detect_addressed_personas(text_lower, allowed_personas=room_members)
    if explicit:
        if len(explicit) > 1 and not any(q in text_lower for q in ["both", "all of you", "everyone", "sab log", "dono"]):
            for p_id in explicit:
                p = get_persona(p_id)
                for kw in p["keywords"]:
                    if re.search(rf"\b(ask|tell|consult|pucho|bolo)\s+{re.escape(kw)}\b", text_lower):
                        return [p_id]
            return [explicit[-1]] if "ask" in text_lower else [explicit[0]]
        return explicit

    # Also check if user addressed someone outside the current room
    any_explicit = detect_addressed_personas(text_lower)
    if any_explicit:
        return any_explicit

    # 2. Check if user explicitly asked everyone/both to answer
    if any(q in text_lower for q in ["both of you", "all of you", "everyone", "sab log", "dono"]):
        return room_members

    # 3. Deliberate Single-Speaker Selection per Room:
    if active_room_id == "office":
        if any(w in text_lower for w in ["tech", "code", "ai", "model", "architecture", "system", "bug", "scale", "api", "database"]):
            return ["tech_lead"]
        if any(w in text_lower for w in ["khana", "food", "health", "tired", "headache", "sick"]):
            return ["mom"]
        return ["manager"]

    elif active_room_id == "chill":
        if any(w in text_lower for w in ["joke", "funny", "bro", "crazy", "laugh", "meme", "party", "chill"]):
            return ["friend"]
        last_spk = None
        if session and session.global_history:
            for t in reversed(session.global_history):
                if t.speaker_id in room_members:
                    last_spk = t.speaker_id
                    break
        return ["saheli"] if last_spk == "friend" else ["friend"]

    elif active_room_id == "family":
        if any(w in text_lower for w in ["career", "future", "money", "invest", "job", "decision", "discipline"]):
            return ["dad"]
        return ["mom"]

    return [room["default_speaker"]]


def detect_voice_from_context(
    user_text: str,
    current_voice_key: str = "manager",
    previous_voice_key: Optional[str] = None
) -> Tuple[str, Dict[str, Any], bool]:
    speakers = select_speakers_for_turn(user_text)
    primary = speakers[0] if speakers else "manager"
    changed = (primary != current_voice_key)
    meta = VOICE_CATALOG.get(primary, VOICE_CATALOG["manager"])
    return primary, meta, changed

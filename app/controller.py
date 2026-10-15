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
    """Check if characters were addressed by name or title, returning them in order of appearance."""
    if not user_text:
        return []

    text_lower = user_text.lower()
    matches: List[Tuple[int, str]] = []
    pool = allowed_personas if allowed_personas else list(ROUNDTABLE_PERSONAS.keys())

    for p_id in pool:
        p = get_persona(p_id)
        # Check name and role keywords first
        names_to_check = p.get("keywords", [])
        for kw in names_to_check:
            m = re.search(rf"\b{re.escape(kw)}\b", text_lower)
            if m:
                matches.append((m.start(), p_id))
                break

    matches.sort(key=lambda x: x[0])
    ordered_ids: List[str] = []
    for _, pid in matches:
        if pid not in ordered_ids:
            ordered_ids.append(pid)
    return ordered_ids


def detect_peer_referral(agent_text: str, current_speaker_id: str, room_id: str) -> Optional[str]:
    """
    Detect if an agent directly referenced or addressed their room colleague during their speech,
    inviting or handing off the floor to the peer.
    """
    if not agent_text:
        return None

    room = get_room(room_id)
    room_members = room.get("persona_ids", [])
    peers = [pid for pid in room_members if pid != current_speaker_id]
    if not peers:
        return None

    text_lower = agent_text.lower().strip()
    current_persona = get_persona(current_speaker_id)
    designated_peer = current_persona.get("peer_id")

    for peer_id in peers:
        peer = get_persona(peer_id)
        peer_keywords = peer.get("keywords", [])
        has_peer_mention = any(re.search(rf"\b{re.escape(kw)}\b", text_lower) for kw in peer_keywords)
        if not has_peer_mention:
            continue

        # Look for invitation / question / hand-off signals
        is_question = "?" in agent_text
        has_direct_address = any(
            re.search(rf"\b{re.escape(kw)}\b\s*[,!?]", text_lower)
            or re.search(rf"\b(hey|suno|arre)?\s*{re.escape(kw)}\b\s+(kya|what|can|batao|tell|should|will|aap|tum)", text_lower)
            for kw in peer_keywords
        )
        has_handoff_phrase = any(
            phrase in text_lower
            for phrase in [
                "what do you think", "can you", "could you", "batao", "aap kya kehte",
                "tum batao", "right?", "sahi hai na", "agreed?", "is that right"
            ]
        )

        if is_question or has_direct_address or has_handoff_phrase or peer_id == designated_peer:
            return peer_id

    return None


def select_speakers_for_turn(
    user_text: str,
    session: Optional[GroupDiscussionSession] = None,
    room_id: Optional[str] = None,
) -> List[str]:
    """
    Selects EXACTLY who speaks:
    - If user explicitly addresses multiple characters ('Rohan and Dev', 'Mom and Dad') -> both speak in order.
    - If user explicitly says 'both of you', 'everyone', 'dono' -> all room members speak sequentially.
    - If user addresses one person -> ONLY that person speaks.
    - If open statement -> deliberate single speaker selected by topic relevance.
    """
    active_room_id = room_id or (session.room_id if session else DEFAULT_ROOM_ID)
    room = get_room(active_room_id)
    room_members = room["persona_ids"]

    if not user_text:
        return [room["default_speaker"]]

    text_lower = user_text.lower().strip()

    # 1. Check if user explicitly asked both / all members of the room
    is_multi_ask = any(q in text_lower for q in [
        "both of you", "all of you", "everyone", "sab log", "dono", "both", "tell me both",
        "dono batao", "har koi", "all participants", "whole team"
    ])

    # 2. Direct address check
    explicit = detect_addressed_personas(text_lower, allowed_personas=room_members)
    if explicit:
        # If user explicitly mentioned multiple room members or connected them with and/aur/&
        has_multi_connector = any(c in text_lower for c in [" and ", " & ", " aur ", " + ", ", "])
        if len(explicit) > 1:
            if is_multi_ask or has_multi_connector:
                return explicit

            # If user said "Ask Rohan, not Dev" or "Tell Dev to check with Rohan"
            for p_id in explicit:
                p = get_persona(p_id)
                for kw in p["keywords"]:
                    if re.search(rf"\b(ask|tell|consult|pucho|bolo)\s+{re.escape(kw)}\b", text_lower):
                        return [p_id]
            return [explicit[0]]

        # Single member explicitly addressed
        if is_multi_ask:
            # User said e.g. "Dev, both of you answer" -> start with Dev, then remaining room members
            other_members = [m for m in room_members if m != explicit[0]]
            return explicit + other_members
        return explicit

    # Also check if user addressed someone outside the current room
    any_explicit = detect_addressed_personas(text_lower)
    if any_explicit:
        return any_explicit

    # 3. Check if user explicitly asked everyone/both to answer
    if is_multi_ask:
        return list(room_members)

    # 4. Deliberate Single-Speaker Selection per Room:
    if active_room_id == "office":
        if any(w in text_lower for w in ["tech", "code", "ai", "model", "architecture", "system", "bug", "scale", "api", "database", "latency", "backend"]):
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
        if any(w in text_lower for w in ["career", "future", "money", "invest", "job", "decision", "discipline", "savings", "finance"]):
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

"""
Group Discussion Session & Memory Management for Awaaz.
Dual-layer memory with customizable user identity (e.g. Ken) and room-specific roles:
- Office: The Boss / Founder
- Chill: Close Friend
- Family: Son / Child (Beta)
"""
import time
from typing import Dict, List, Any, Optional
from app.personas import ROUNDTABLE_PERSONAS, get_persona, get_room, DEFAULT_ROOM_ID

DEFAULT_AGENDAS: Dict[str, str] = {
    "office": "Sprint Review: Finalizing Q4 Voice AI architecture, API latency, and delivery deadline.",
    "chill": "Weekend Hangout: Planning a trip, sharing hilarious stories, and brainstorming fun ideas.",
    "family": "Family Roundtable: Career decisions, maintaining good health, work-life balance, and peace of mind.",
}


class DiscussionTurn:
    def __init__(self, speaker_id: str, speaker_name: str, content: str, role: str = "assistant"):
        self.speaker_id = speaker_id
        self.speaker_name = speaker_name
        self.content = content
        self.role = role
        self.timestamp = time.time()


class GroupDiscussionSession:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.room_id: str = DEFAULT_ROOM_ID
        self.user_name: str = "Ken"
        self.agendas: Dict[str, str] = dict(DEFAULT_AGENDAS)
        self.global_history: List[DiscussionTurn] = []
        self.local_memory: Dict[str, List[str]] = {pid: [] for pid in ROUNDTABLE_PERSONAS.keys()}
        self.last_active = time.time()

    def set_room(self, room_id: str) -> None:
        self.room_id = room_id
        self.last_active = time.time()

    def set_user_name(self, name: str) -> None:
        if name and name.strip():
            self.user_name = name.strip()
            self.last_active = time.time()

    def get_user_role_in_room(self) -> str:
        if self.room_id == "office":
            return "The Boss / Founder"
        elif self.room_id == "chill":
            return "Close Friend"
        elif self.room_id == "family":
            return "Son / Child (Beta)"
        return "Member"

    def set_agenda(self, room_id: str, agenda: str) -> None:
        self.agendas[room_id] = agenda.strip()
        self.last_active = time.time()

    def get_current_agenda(self) -> str:
        return self.agendas.get(self.room_id, DEFAULT_AGENDAS.get(self.room_id, "Open Group Discussion"))

    def add_user_speech(self, content: str, lang: str = "en-IN") -> None:
        self.global_history.append(DiscussionTurn("user", self.user_name, content, role="user"))
        has_devanagari = any('\u0900' <= c <= '\u097f' for c in content)
        if has_devanagari or lang.startswith("hi"):
            self.last_user_lang = "hi-IN"
        else:
            self.last_user_lang = lang or "en-IN"
        self.last_active = time.time()

    def add_persona_speech(self, persona_id: str, content: str) -> None:
        persona = get_persona(persona_id)
        self.global_history.append(DiscussionTurn(persona_id, persona["name"], content, role="assistant"))
        
        if persona_id not in self.local_memory:
            self.local_memory[persona_id] = []
        self.local_memory[persona_id].append(content)
        if len(self.local_memory[persona_id]) > 4:
            self.local_memory[persona_id].pop(0)

        self.last_active = time.time()

    def build_persona_llm_messages(self, persona_id: str, max_turns: int = 16) -> List[Dict[str, str]]:
        persona = get_persona(persona_id)
        room = get_room(self.room_id)
        agenda = self.get_current_agenda()
        user_role = self.get_user_role_in_room()
        
        peers = [f"- '{get_persona(pid)['name']}': {get_persona(pid)['role']}" for pid in room["persona_ids"] if pid != persona_id]
        system_content = [
            f"You are {persona['name']}, role: {persona['role']} in the '{room['name']}' roundtable.",
            f"ROOM PARTICIPANTS:",
            f"- '{self.user_name}': The user talking with you ({user_role}).",
            f"- '{persona['name']}': YOU (Never address the user as '{persona['name']}').",
        ]
        system_content.extend(peers)

        system_content.extend([
            f"\nROLE & BEHAVIOR:\n{persona['system_prompt']}",
            f"\nTOPIC / AGENDA:\n{agenda} (Context theme only. Never recite this text verbatim).",
            "\nCRITICAL CONVERSATION RULES:",
            f"- READ THE FULL CONVERSATION HISTORY. You know what {self.user_name} said and what other participants said.",
            f"- DIRECTLY ANSWER what {self.user_name} asks or brings up. Follow the conversational flow.",
            "- PROPOSE REAL, SPECIFIC IDEAS: When asked for suggestions or plans, pitch concrete, imaginative ideas (places, activities, technical solutions). Never tell the user 'tum batao' or ask them to answer their own question.",
            "- Speak naturally like a real human participant in 2 to 3 engaging sentences (say whatever is needed to give a satisfying, complete response).",
            "- LANGUAGE: Reply in the exact same language that the user is speaking. Never switch languages on your own.",
            "- Never prefix your message with your name or any label. Zero markdown."
        ])

        if self.room_id == "office":
            system_content.append(f"Relationship: You report to {self.user_name}. Keep it professional and conversational. Do NOT spam 'Boss'.")
        elif self.room_id == "chill":
            system_content.append(f"Relationship: Treat {self.user_name} as your close friend. Call them '{self.user_name}' or 'yaar'.")
        elif self.room_id == "family":
            system_content.append(f"Relationship: The user is your son '{self.user_name}'. Be warm and loving. Do NOT repeat 'beta' constantly.")

        messages: List[Dict[str, str]] = [{"role": "system", "content": "\n".join(system_content)}]

        recent_turns = self.global_history[-max_turns:] if self.global_history else []
        for t in recent_turns:
            if t.speaker_id == "user":
                messages.append({"role": "user", "content": f"{self.user_name}: {t.content}"})
            elif t.speaker_id == persona_id:
                messages.append({"role": "assistant", "content": t.content})
            else:
                messages.append({"role": "user", "content": f"{t.speaker_name}: {t.content}"})

        return messages

    def clear(self) -> None:
        self.global_history.clear()
        self.local_memory = {pid: [] for pid in ROUNDTABLE_PERSONAS.keys()}
        self.last_active = time.time()


class SessionManager:
    def __init__(self):
        self._sessions: Dict[str, GroupDiscussionSession] = {}

    def get_or_create(self, session_id: Optional[str] = None) -> GroupDiscussionSession:
        sid = session_id or "default_session"
        if sid not in self._sessions:
            self._sessions[sid] = GroupDiscussionSession(sid)
        return self._sessions[sid]

    def reset(self, session_id: str) -> GroupDiscussionSession:
        sess = self.get_or_create(session_id)
        sess.clear()
        return sess


session_manager = SessionManager()

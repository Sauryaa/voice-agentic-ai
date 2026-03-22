import json
import threading
from pathlib import Path
from uuid import uuid4

from .models import ConversationTurn, SessionRecord, utc_now


class SessionStore:
    def __init__(self, logs_dir: Path):
        self.logs_dir = logs_dir
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._cache: dict[str, SessionRecord] = {}

    def create_session(self, participant_id: str | None = None, company: str = "Mayo Clinic") -> SessionRecord:
        session_id = str(uuid4())
        session = SessionRecord(session_id=session_id, participant_id=participant_id, company=company)
        self.save(session)
        return session

    def load(self, session_id: str) -> SessionRecord | None:
        with self._lock:
            if session_id in self._cache:
                return self._cache[session_id]

            path = self._session_path(session_id)
            if not path.exists():
                return None

            payload = json.loads(path.read_text(encoding="utf-8"))
            session = SessionRecord.model_validate(payload)
            self._cache[session_id] = session
            return session

    def save(self, session: SessionRecord) -> SessionRecord:
        session.updated_at = utc_now()
        path = self._session_path(session.session_id)
        with self._lock:
            path.write_text(
                json.dumps(session.model_dump(mode="json"), ensure_ascii=True, indent=2),
                encoding="utf-8",
            )
            self._cache[session.session_id] = session
        return session

    def append_turn(self, session_id: str, turn: ConversationTurn) -> SessionRecord:
        session = self.load(session_id)
        if session is None:
            raise KeyError(f"Session {session_id} not found")
        session.turns.append(turn)
        return self.save(session)

    def _session_path(self, session_id: str) -> Path:
        return self.logs_dir / f"{session_id}.json"

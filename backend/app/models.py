from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from .agenda import HEADACHE_INTERVIEW_QUESTIONS


Speaker = Literal["agent", "interviewee"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ConversationTurn(BaseModel):
    speaker: Speaker
    text: str
    timestamp: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionRecord(BaseModel):
    session_id: str
    company: str = "Mayo Clinic"
    participant_id: str | None = None
    started_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    current_question_index: int = 0
    completed: bool = False
    agenda: list[str] = Field(default_factory=lambda: list(HEADACHE_INTERVIEW_QUESTIONS))
    turns: list[ConversationTurn] = Field(default_factory=list)


class StartSessionRequest(BaseModel):
    participant_id: str | None = None


class StartSessionResponse(BaseModel):
    session_id: str
    message: str
    current_question_index: int
    total_questions: int
    interview_complete: bool


class TextTurnRequest(BaseModel):
    text: str


class TurnResponse(BaseModel):
    session_id: str
    transcript: str
    assistant_message: str
    current_question_index: int
    total_questions: int
    interview_complete: bool
    question_completed: bool
    completion_confidence: float

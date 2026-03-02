from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

InterviewMode = Literal["user_controlled", "agent_controlled"]
SessionStatus = Literal["in_progress", "completed"]
TurnType = Literal[
    "question",
    "answer",
    "clarification",
    "acknowledgment",
    "completion",
]


class PromptPayload(BaseModel):
    question_id: int | None = None
    type: Literal["question", "clarification", "completion"]
    text: str


class StartSessionRequest(BaseModel):
    mode: InterviewMode = "user_controlled"


class StartSessionResponse(BaseModel):
    session_id: str
    created_at: datetime
    mode: InterviewMode
    status: SessionStatus
    current_prompt: PromptPayload


class TranscribeRequest(BaseModel):
    audio_base64: str
    mime_type: str = "audio/webm"
    language_code: str | None = None
    sample_rate_hz: int | None = None


class TranscribeResponse(BaseModel):
    text: str
    mime_type: str


class InterviewRespondRequest(BaseModel):
    session_id: str
    text: str


class InterviewRespondResponse(BaseModel):
    session_id: str
    status: SessionStatus
    question_id: int | None = None
    is_complete_for_question: bool
    needs_clarification: bool
    reason: str
    next_prompt: PromptPayload | None = None
    interview_complete: bool


class NextQuestionRequest(BaseModel):
    session_id: str
    force: bool = False


class NextQuestionResponse(BaseModel):
    session_id: str
    status: SessionStatus
    next_prompt: PromptPayload | None = None
    moved_to_next_question: bool = False
    interview_complete: bool = False


class Turn(BaseModel):
    turn_index: int
    speaker: Literal["agent", "interviewee"]
    question_id: int | None = None
    type: TurnType
    text: str
    timestamp: datetime


class SessionLog(BaseModel):
    session_id: str
    created_at: datetime
    mode: InterviewMode
    status: SessionStatus
    turns: list[Turn] = Field(default_factory=list)

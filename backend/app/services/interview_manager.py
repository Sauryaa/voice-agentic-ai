from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock
from uuid import uuid4

from backend.app.config import Settings
from backend.app.models.schemas import (
    InterviewRespondResponse,
    NextQuestionResponse,
    PromptPayload,
    SessionLog,
    StartSessionResponse,
    Turn,
)
from backend.app.prompts.interview_prompts import (
    DEFAULT_CLARIFICATION_PROMPT,
    INTERVIEW_QUESTIONS,
)
from backend.app.services.gemini_agent import GeminiInterviewAgent


@dataclass
class SessionState:
    session_id: str
    created_at: datetime
    mode: str
    status: str = "in_progress"
    current_question_index: int = 0
    active_prompt: PromptPayload | None = None
    turn_counter: int = 0
    turns: list[Turn] = field(default_factory=list)
    answers_by_question: dict[int, list[str]] = field(default_factory=dict)
    clarification_attempts: dict[int, int] = field(default_factory=dict)


class InterviewManager:
    def __init__(self, settings: Settings, gemini_agent: GeminiInterviewAgent) -> None:
        self.settings = settings
        self.gemini_agent = gemini_agent
        self.questions = INTERVIEW_QUESTIONS
        self._sessions: dict[str, SessionState] = {}
        self._lock = RLock()

    def start_session(self, mode: str) -> StartSessionResponse:
        with self._lock:
            session_id = str(uuid4())
            created_at = datetime.now(UTC)
            first_prompt = PromptPayload(
                question_id=1,
                type="question",
                text=self.questions[0],
            )

            state = SessionState(
                session_id=session_id,
                created_at=created_at,
                mode=mode,
                active_prompt=first_prompt,
            )
            self._append_turn(
                state,
                speaker="agent",
                turn_type="question",
                text=first_prompt.text,
                question_id=1,
            )

            self._sessions[session_id] = state
            return StartSessionResponse(
                session_id=session_id,
                created_at=created_at,
                mode=mode,
                status="in_progress",
                current_prompt=first_prompt,
            )

    def respond(self, session_id: str, text: str) -> InterviewRespondResponse:
        clean_text = (text or "").strip()
        if not clean_text:
            raise ValueError("Response text is required.")

        with self._lock:
            state = self._get_session_state(session_id)
            if state.status == "completed":
                raise ValueError("Interview session is already completed.")
            if state.active_prompt is None or state.active_prompt.question_id is None:
                raise ValueError("No active interview question is available.")

            question_id = state.active_prompt.question_id
            question_index = question_id - 1
            question_text = self.questions[question_index]

            self._append_turn(
                state,
                speaker="interviewee",
                turn_type="answer",
                text=clean_text,
                question_id=question_id,
            )

            question_answers = state.answers_by_question.setdefault(question_id, [])
            question_answers.append(clean_text)
            cumulative_answer = " ".join(question_answers)
            attempts = state.clarification_attempts.get(question_id, 0)

            evaluation = self.gemini_agent.evaluate_answer(
                question_id=question_id,
                question_text=question_text,
                latest_answer=clean_text,
                cumulative_answer=cumulative_answer,
                clarification_attempts=attempts,
            )

            max_attempts_reached = attempts >= self.settings.max_clarifications_per_question

            if not evaluation.is_complete and not max_attempts_reached:
                attempts += 1
                state.clarification_attempts[question_id] = attempts

                follow_up = evaluation.follow_up_question or DEFAULT_CLARIFICATION_PROMPT
                clarification_prompt = PromptPayload(
                    question_id=question_id,
                    type="clarification",
                    text=follow_up,
                )
                state.active_prompt = clarification_prompt

                self._append_turn(
                    state,
                    speaker="agent",
                    turn_type="clarification",
                    text=follow_up,
                    question_id=question_id,
                )

                return InterviewRespondResponse(
                    session_id=session_id,
                    status=state.status,
                    question_id=question_id,
                    is_complete_for_question=False,
                    needs_clarification=True,
                    reason=evaluation.reason,
                    next_prompt=clarification_prompt,
                    interview_complete=False,
                )

            completion_reason = evaluation.reason
            if not evaluation.is_complete and max_attempts_reached:
                completion_reason = (
                    f"{evaluation.reason} Max clarification attempts reached, moving to the next question."
                )

            if (
                self.settings.include_acknowledgment_turns
                and evaluation.acknowledgment
                and evaluation.is_complete
            ):
                self._append_turn(
                    state,
                    speaker="agent",
                    turn_type="acknowledgment",
                    text=evaluation.acknowledgment,
                    question_id=question_id,
                )

            state.current_question_index = question_index + 1

            if state.current_question_index >= len(self.questions):
                state.status = "completed"
                state.active_prompt = None
                completion_prompt = PromptPayload(
                    question_id=None,
                    type="completion",
                    text="Interview complete. Thank you for sharing these details.",
                )
                self._append_turn(
                    state,
                    speaker="agent",
                    turn_type="completion",
                    text=completion_prompt.text,
                    question_id=None,
                )
                return InterviewRespondResponse(
                    session_id=session_id,
                    status=state.status,
                    question_id=None,
                    is_complete_for_question=True,
                    needs_clarification=False,
                    reason=completion_reason,
                    next_prompt=completion_prompt,
                    interview_complete=True,
                )

            next_question_id = state.current_question_index + 1
            next_question_text = self.questions[state.current_question_index]
            next_prompt = PromptPayload(
                question_id=next_question_id,
                type="question",
                text=next_question_text,
            )
            state.active_prompt = next_prompt

            self._append_turn(
                state,
                speaker="agent",
                turn_type="question",
                text=next_question_text,
                question_id=next_question_id,
            )

            return InterviewRespondResponse(
                session_id=session_id,
                status=state.status,
                question_id=question_id,
                is_complete_for_question=True,
                needs_clarification=False,
                reason=completion_reason,
                next_prompt=next_prompt,
                interview_complete=False,
            )

    def next_question(self, session_id: str, force: bool = False) -> NextQuestionResponse:
        with self._lock:
            state = self._get_session_state(session_id)

            if state.status == "completed":
                return NextQuestionResponse(
                    session_id=session_id,
                    status=state.status,
                    next_prompt=None,
                    moved_to_next_question=False,
                    interview_complete=True,
                )

            if not force:
                if state.active_prompt is None:
                    question_id = state.current_question_index + 1
                    state.active_prompt = PromptPayload(
                        question_id=question_id,
                        type="question",
                        text=self.questions[state.current_question_index],
                    )
                    self._append_turn(
                        state,
                        speaker="agent",
                        turn_type="question",
                        text=state.active_prompt.text,
                        question_id=question_id,
                    )

                return NextQuestionResponse(
                    session_id=session_id,
                    status=state.status,
                    next_prompt=state.active_prompt,
                    moved_to_next_question=False,
                    interview_complete=False,
                )

            state.current_question_index += 1
            if state.current_question_index >= len(self.questions):
                state.status = "completed"
                state.active_prompt = None
                completion_prompt = PromptPayload(
                    question_id=None,
                    type="completion",
                    text="Interview complete. Thank you for sharing these details.",
                )
                self._append_turn(
                    state,
                    speaker="agent",
                    turn_type="completion",
                    text=completion_prompt.text,
                    question_id=None,
                )
                return NextQuestionResponse(
                    session_id=session_id,
                    status=state.status,
                    next_prompt=completion_prompt,
                    moved_to_next_question=True,
                    interview_complete=True,
                )

            next_question_id = state.current_question_index + 1
            next_prompt = PromptPayload(
                question_id=next_question_id,
                type="question",
                text=self.questions[state.current_question_index],
            )
            state.active_prompt = next_prompt
            self._append_turn(
                state,
                speaker="agent",
                turn_type="question",
                text=next_prompt.text,
                question_id=next_question_id,
            )

            return NextQuestionResponse(
                session_id=session_id,
                status=state.status,
                next_prompt=next_prompt,
                moved_to_next_question=True,
                interview_complete=False,
            )

    def get_session_log(self, session_id: str) -> SessionLog:
        with self._lock:
            state = self._get_session_state(session_id)
            return SessionLog(
                session_id=state.session_id,
                created_at=state.created_at,
                mode=state.mode,
                status=state.status,
                turns=list(state.turns),
            )

    def _get_session_state(self, session_id: str) -> SessionState:
        state = self._sessions.get(session_id)
        if state is None:
            raise KeyError(f"Session not found: {session_id}")
        return state

    def _append_turn(
        self,
        state: SessionState,
        *,
        speaker: str,
        turn_type: str,
        text: str,
        question_id: int | None,
    ) -> None:
        state.turn_counter += 1
        state.turns.append(
            Turn(
                turn_index=state.turn_counter,
                speaker=speaker,
                question_id=question_id,
                type=turn_type,
                text=text,
                timestamp=datetime.now(UTC),
            )
        )

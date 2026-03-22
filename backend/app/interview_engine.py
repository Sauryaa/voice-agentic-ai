from dataclasses import dataclass

from .models import ConversationTurn, SessionRecord
from .llm_service import GeminiInterviewEvaluator
from .logging_store import SessionStore


@dataclass
class InterviewStepResult:
    session: SessionRecord
    assistant_message: str
    question_completed: bool
    completion_confidence: float
    transcript: str


class InterviewEngine:
    def __init__(self, store: SessionStore, evaluator: GeminiInterviewEvaluator):
        self.store = store
        self.evaluator = evaluator

    def start_session(self, participant_id: str | None, company_name: str = "Mayo Clinic") -> SessionRecord:
        session = self.store.create_session(participant_id=participant_id, company=company_name)
        first_question = session.agenda[0]
        session.turns.append(
            ConversationTurn(
                speaker="agent",
                text=first_question,
                metadata={"question_index": 0, "type": "agenda_question"},
            )
        )
        return self.store.save(session)

    def process_transcript(self, session_id: str, transcript: str) -> InterviewStepResult:
        session = self.store.load(session_id)
        if session is None:
            raise KeyError(f"Session {session_id} not found")

        cleaned = transcript.strip()
        if not cleaned:
            assistant_message = "I did not catch that clearly. Could you please repeat your answer?"
            session.turns.append(
                ConversationTurn(
                    speaker="agent",
                    text=assistant_message,
                    metadata={"question_index": session.current_question_index, "type": "repeat_request"},
                )
            )
            session = self.store.save(session)
            return InterviewStepResult(
                session=session,
                assistant_message=assistant_message,
                question_completed=False,
                completion_confidence=0.0,
                transcript=cleaned,
            )

        session.turns.append(
            ConversationTurn(
                speaker="interviewee",
                text=cleaned,
                metadata={"question_index": session.current_question_index},
            )
        )

        if session.completed:
            assistant_message = "This interview is already complete. Thank you."
            session.turns.append(ConversationTurn(speaker="agent", text=assistant_message, metadata={"type": "already_complete"}))
            session = self.store.save(session)
            return InterviewStepResult(
                session=session,
                assistant_message=assistant_message,
                question_completed=False,
                completion_confidence=1.0,
                transcript=cleaned,
            )

        question_index = session.current_question_index
        current_question = session.agenda[question_index]
        recent_history = [(turn.speaker, turn.text) for turn in session.turns]
        decision = self.evaluator.evaluate(
            current_question=current_question,
            interviewee_response=cleaned,
            recent_history=recent_history,
        )

        if decision.is_complete:
            next_index = question_index + 1
            if next_index >= len(session.agenda):
                session.completed = True
                assistant_message = "Thank you. We have completed all interview questions."
                message_type = "interview_complete"
            else:
                session.current_question_index = next_index
                assistant_message = session.agenda[next_index]
                message_type = "agenda_question"

            session.turns.append(
                ConversationTurn(
                    speaker="agent",
                    text=assistant_message,
                    metadata={
                        "question_completed_index": question_index,
                        "question_index": session.current_question_index,
                        "type": message_type,
                        "confidence": decision.confidence,
                    },
                )
            )
            session = self.store.save(session)
            return InterviewStepResult(
                session=session,
                assistant_message=assistant_message,
                question_completed=True,
                completion_confidence=decision.confidence,
                transcript=cleaned,
            )

        follow_up = decision.follow_up or "Could you share a bit more detail before we move to the next question?"
        session.turns.append(
            ConversationTurn(
                speaker="agent",
                text=follow_up,
                metadata={
                    "question_index": question_index,
                    "type": "follow_up",
                    "confidence": decision.confidence,
                    "reason": decision.reason,
                },
            )
        )
        session = self.store.save(session)
        return InterviewStepResult(
            session=session,
            assistant_message=follow_up,
            question_completed=False,
            completion_confidence=decision.confidence,
            transcript=cleaned,
        )

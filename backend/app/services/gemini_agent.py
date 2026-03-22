import json
import logging
import re
from dataclasses import dataclass

from backend.app.config import Settings
from backend.app.prompts.interview_prompts import (
    DEFAULT_CLARIFICATION_PROMPT,
    build_answer_evaluation_prompt,
)

logger = logging.getLogger(__name__)


@dataclass
class AnswerEvaluation:
    is_complete: bool
    reason: str
    follow_up_question: str | None = None
    acknowledgment: str | None = None


class GeminiInterviewAgent:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model = None
        self._init_model()

    def _init_model(self) -> None:
        try:
            import vertexai
            from vertexai.generative_models import GenerativeModel

            vertexai.init(
                project=self.settings.google_cloud_project,
                location=self.settings.google_cloud_location,
            )
            self._model = GenerativeModel(self.settings.gemini_model)
            logger.info("Gemini model initialized: %s", self.settings.gemini_model)
        except Exception as exc:  # pragma: no cover - environment dependent
            self._model = None
            logger.warning("Gemini unavailable, using heuristic fallback: %s", exc)

    def evaluate_answer(
        self,
        *,
        question_id: int,
        question_text: str,
        latest_answer: str,
        cumulative_answer: str,
        clarification_attempts: int,
    ) -> AnswerEvaluation:
        if not self._model:
            return self._heuristic_evaluation(
                question_id=question_id,
                latest_answer=latest_answer,
                cumulative_answer=cumulative_answer,
            )

        prompt = build_answer_evaluation_prompt(
            question_id=question_id,
            question_text=question_text,
            latest_answer=latest_answer,
            cumulative_answer=cumulative_answer,
            clarification_attempts=clarification_attempts,
            max_clarifications=self.settings.max_clarifications_per_question,
            minimum_answer_word_count=self.settings.minimum_answer_word_count,
        )

        try:
            from vertexai.generative_models import GenerationConfig

            response = self._model.generate_content(
                prompt,
                generation_config=GenerationConfig(
                    temperature=self.settings.gemini_temperature,
                    top_p=0.8,
                    max_output_tokens=256,
                ),
            )
            payload = self._extract_json(self._response_text(response))
            return self._normalize_payload(payload)
        except Exception as exc:  # pragma: no cover - external service dependent
            logger.warning("Gemini evaluation failed, using heuristic fallback: %s", exc)
            return self._heuristic_evaluation(
                question_id=question_id,
                latest_answer=latest_answer,
                cumulative_answer=cumulative_answer,
            )

    def _response_text(self, response: object) -> str:
        text = getattr(response, "text", None)
        if text:
            return text

        candidates = getattr(response, "candidates", None)
        if not candidates:
            return "{}"

        parts: list[str] = []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            if not content:
                continue
            for part in getattr(content, "parts", []):
                part_text = getattr(part, "text", "")
                if part_text:
                    parts.append(part_text)

        return "\n".join(parts) if parts else "{}"

    def _extract_json(self, raw_text: str) -> dict:
        match = re.search(r"\{.*\}", raw_text, flags=re.DOTALL)
        if not match:
            raise ValueError("No JSON object found in model response")
        return json.loads(match.group(0))

    def _normalize_payload(self, payload: dict) -> AnswerEvaluation:
        is_complete = bool(payload.get("is_complete", False))
        reason = str(payload.get("reason", "No reason provided.")).strip() or "No reason provided."
        follow_up = payload.get("follow_up_question")
        acknowledgment = payload.get("acknowledgment")

        if is_complete:
            follow_up = None
        elif not follow_up:
            follow_up = DEFAULT_CLARIFICATION_PROMPT

        return AnswerEvaluation(
            is_complete=is_complete,
            reason=reason,
            follow_up_question=str(follow_up).strip() if follow_up else None,
            acknowledgment=str(acknowledgment).strip() if acknowledgment else None,
        )

    def _heuristic_evaluation(
        self,
        *,
        question_id: int,
        latest_answer: str,
        cumulative_answer: str,
    ) -> AnswerEvaluation:
        normalized = cumulative_answer.strip().lower()
        words = [w for w in re.split(r"\s+", normalized) if w]

        if len(words) < self.settings.minimum_answer_word_count:
            return AnswerEvaluation(
                is_complete=False,
                reason="Answer appears too short for reliable capture.",
                follow_up_question=DEFAULT_CLARIFICATION_PROMPT,
            )

        vague_markers = [
            "not sure",
            "i don't know",
            "dont know",
            "maybe",
            "kind of",
            "something",
        ]
        if any(marker in normalized for marker in vague_markers):
            return AnswerEvaluation(
                is_complete=False,
                reason="Answer appears vague.",
                follow_up_question=DEFAULT_CLARIFICATION_PROMPT,
            )

        if question_id == 5 and not re.search(r"\b([0-9]|10)\b", normalized):
            return AnswerEvaluation(
                is_complete=False,
                reason="Pain scale value was not clearly provided.",
                follow_up_question="Could you rate your average headache pain from 0 to 10?",
            )

        if question_id == 6 and not re.search(
            r"\b(minute|minutes|hour|hours|day|days|week|weeks|month|months)\b",
            normalized,
        ):
            return AnswerEvaluation(
                is_complete=False,
                reason="Typical headache duration was not clearly stated.",
                follow_up_question="How long does a typical headache last (for example minutes, hours, or days)?",
            )

        if question_id in (7, 8):
            has_medication_detail = bool(re.search(r"\bmg\b|\bmcg\b|\btablet\b|\bdose\b|\bnone\b", normalized))
            if not has_medication_detail and len(words) < 8:
                return AnswerEvaluation(
                    is_complete=False,
                    reason="Medication details appear incomplete.",
                    follow_up_question="Could you share the medication names and doses, or say none if you do not take any?",
                )

        if not latest_answer.strip():
            return AnswerEvaluation(
                is_complete=False,
                reason="No answer detected.",
                follow_up_question=DEFAULT_CLARIFICATION_PROMPT,
            )

        return AnswerEvaluation(
            is_complete=True,
            reason="Answer appears sufficient for this question.",
            acknowledgment="Thank you. I captured that.",
        )

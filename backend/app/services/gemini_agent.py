import json
import logging
import re
from dataclasses import dataclass

from backend.app.config import Settings
from backend.app.prompts.interview_prompts import (
    DEFAULT_CLARIFICATION_PROMPT,
    build_answer_evaluation_prompt,
    build_question_generation_prompt,
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

    def compose_question(
        self,
        *,
        question_id: int,
        feature: str,
        question_text: str,
        prior_dialogue: str,
    ) -> str:
        if not self._model:
            return question_text

        prompt = build_question_generation_prompt(
            question_id=question_id,
            feature=feature,
            question_text=question_text,
            prior_dialogue=prior_dialogue,
        )

        try:
            from vertexai.generative_models import GenerationConfig

            response = self._model.generate_content(
                prompt,
                generation_config=GenerationConfig(
                    temperature=self.settings.gemini_question_temperature,
                    top_p=0.8,
                    max_output_tokens=128,
                ),
            )
            generated = self._response_text(response).strip().strip('"')
            return generated or question_text
        except Exception as exc:  # pragma: no cover - external service dependent
            logger.warning("Gemini question generation failed, using original question: %s", exc)
            return question_text

    def evaluate_answer(
        self,
        *,
        question_id: int,
        feature: str,
        question_text: str,
        actual_question_asked: str,
        latest_answer: str,
        cumulative_answer: str,
        clarification_attempts: int,
    ) -> AnswerEvaluation:
        if not self._model:
            return self._heuristic_evaluation(
                question_id=question_id,
                latest_answer=latest_answer,
                cumulative_answer=cumulative_answer,
                clarification_attempts=clarification_attempts,
            )

        prompt = build_answer_evaluation_prompt(
            question_id=question_id,
            feature=feature,
            question_text=question_text,
            actual_question_asked=actual_question_asked,
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
                clarification_attempts=clarification_attempts,
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
        clarification_attempts: int,
    ) -> AnswerEvaluation:
        normalized = cumulative_answer.strip().lower()
        words = [w for w in re.split(r"\s+", normalized) if w]

        if not latest_answer.strip():
            return AnswerEvaluation(
                is_complete=False,
                reason="No answer detected.",
                follow_up_question=DEFAULT_CLARIFICATION_PROMPT,
            )

        if self._contains_vague_marker(normalized):
            return AnswerEvaluation(
                is_complete=False,
                reason="Answer appears vague.",
                follow_up_question=DEFAULT_CLARIFICATION_PROMPT,
            )

        if question_id in (5, 8, 10) and self._contains_yes_no(normalized):
            return AnswerEvaluation(
                is_complete=True,
                reason="Clear yes or no answer provided.",
                acknowledgment="Thank you. I captured that.",
            )

        if question_id == 2 and self._contains_side_location(normalized):
            return AnswerEvaluation(
                is_complete=True,
                reason="Headache side/location was clearly stated.",
                acknowledgment="Thank you. I captured that.",
            )

        if question_id == 3:
            if not self._contains_pain_scale(normalized):
                return AnswerEvaluation(
                    is_complete=False,
                    reason="Pain scale value was not clearly provided.",
                    follow_up_question="Could you rate your average headache pain from 0 to 10?",
                )

            return AnswerEvaluation(
                is_complete=True,
                reason="Pain scale value was clearly provided.",
                acknowledgment="Thank you. I captured that.",
            )

        if question_id == 6:
            if not self._contains_duration(normalized):
                return AnswerEvaluation(
                    is_complete=False,
                    reason="Typical headache duration was not clearly stated.",
                    follow_up_question="How long does a typical headache last (for example minutes, hours, or days)?",
                )

            return AnswerEvaluation(
                is_complete=True,
                reason="Headache duration was clearly stated.",
                acknowledgment="Thank you. I captured that.",
            )

        if question_id == 9:
            if self._is_negative_medication_answer(normalized) or self._contains_medication_detail(normalized):
                return AnswerEvaluation(
                    is_complete=True,
                    reason="Medication answer was clearly provided.",
                    acknowledgment="Thank you. I captured that.",
                )

            if clarification_attempts == 0 and len(words) < 8:
                return AnswerEvaluation(
                    is_complete=False,
                    reason="Medication details appear incomplete.",
                    follow_up_question="Could you share the medication names and doses, or say none if you do not take any?",
                )

            return AnswerEvaluation(
                is_complete=True,
                reason="Medication answer appears sufficient for this question.",
                acknowledgment="Thank you. I captured that.",
            )

        if len(words) < self.settings.minimum_answer_word_count:
            if clarification_attempts > 0:
                return AnswerEvaluation(
                    is_complete=True,
                    reason="Short answer accepted after clarification.",
                    acknowledgment="Thank you. I captured that.",
                )

            return AnswerEvaluation(
                is_complete=False,
                reason="Answer appears too short for reliable capture.",
                follow_up_question=DEFAULT_CLARIFICATION_PROMPT,
            )

        return AnswerEvaluation(
            is_complete=True,
            reason="Answer appears sufficient for this question.",
            acknowledgment="Thank you. I captured that.",
        )

    def _contains_vague_marker(self, normalized: str) -> bool:
        vague_markers = (
            "not sure",
            "i don't know",
            "dont know",
            "maybe",
            "kind of",
            "something",
        )
        return any(marker in normalized for marker in vague_markers)

    def _contains_yes_no(self, normalized: str) -> bool:
        return bool(re.search(r"\b(yes|no)\b", normalized))

    def _contains_side_location(self, normalized: str) -> bool:
        return bool(
            re.search(
                r"\b(one side|both sides|left side|right side|left|right|bilateral|unilateral)\b",
                normalized,
            )
        )

    def _contains_pain_scale(self, normalized: str) -> bool:
        return bool(
            re.search(
                r"\b(10|[0-9]|zero|one|two|three|four|five|six|seven|eight|nine|ten)\b",
                normalized,
            )
        )

    def _contains_duration(self, normalized: str) -> bool:
        return bool(
            re.search(
                r"\b(second|seconds|minute|minutes|hour|hours|day|days|week|weeks|month|months|year|years)\b",
                normalized,
            )
        )

    def _is_negative_medication_answer(self, normalized: str) -> bool:
        return bool(
            re.search(
                r"\b(none|no medications?|not taking any|do not take any|don't take any)\b",
                normalized,
            )
        )

    def _contains_medication_detail(self, normalized: str) -> bool:
        return bool(
            re.search(
                r"\b(mg|mcg|tablet|tablets|capsule|capsules|dose|doses|pill|pills)\b",
                normalized,
            )
        )

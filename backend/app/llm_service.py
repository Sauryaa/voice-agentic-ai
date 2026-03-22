import json
import re
from dataclasses import dataclass

import vertexai
from vertexai.generative_models import GenerativeModel


@dataclass
class CompletenessDecision:
    is_complete: bool
    follow_up: str
    confidence: float
    reason: str


class GeminiInterviewEvaluator:
    def __init__(self, project: str, location: str, model_name: str):
        self.project = project
        self.location = location
        self.model_name = model_name
        self._model: GenerativeModel | None = None

    def evaluate(
        self,
        current_question: str,
        interviewee_response: str,
        recent_history: list[tuple[str, str]],
    ) -> CompletenessDecision:
        if not interviewee_response.strip():
            return CompletenessDecision(
                is_complete=False,
                follow_up="I did not catch that. Could you answer the question once more?",
                confidence=0.0,
                reason="empty_response",
            )

        prompt = self._build_prompt(current_question, interviewee_response, recent_history)
        fallback = self._heuristic_decision(interviewee_response)

        try:
            raw = self._get_model().generate_content(prompt).text or ""
            parsed = self._parse_json(raw)
            if parsed is None:
                return fallback

            is_complete = bool(parsed.get("is_complete", fallback.is_complete))
            follow_up = str(parsed.get("follow_up", fallback.follow_up)).strip()
            confidence_raw = parsed.get("confidence", fallback.confidence)
            confidence = float(confidence_raw)
            confidence = max(0.0, min(1.0, confidence))
            reason = str(parsed.get("reason", ""))

            if not is_complete and not follow_up:
                follow_up = fallback.follow_up

            return CompletenessDecision(
                is_complete=is_complete,
                follow_up=follow_up,
                confidence=confidence,
                reason=reason or "model_decision",
            )
        except Exception:
            return fallback

    def _get_model(self) -> GenerativeModel:
        if self._model is None:
            if not self.project:
                raise RuntimeError("GOOGLE_CLOUD_PROJECT is missing")
            vertexai.init(project=self.project, location=self.location)
            self._model = GenerativeModel(self.model_name)
        return self._model

    def _build_prompt(
        self,
        current_question: str,
        interviewee_response: str,
        recent_history: list[tuple[str, str]],
    ) -> str:
        history_lines = []
        for speaker, text in recent_history[-6:]:
            history_lines.append(f"{speaker}: {text}")
        history_text = "\n".join(history_lines) if history_lines else "(none)"

        return f"""
You are assisting a structured clinical-style intake interview.
Determine if the interviewee's latest response is complete enough for moving to the next agenda question.
If incomplete, provide one concise follow-up question to obtain missing key information.

Return ONLY strict JSON with this exact schema:
{{
  "is_complete": true or false,
  "follow_up": "string; must be empty when is_complete=true",
  "confidence": number between 0 and 1,
  "reason": "short reason"
}}

Current agenda question:
{current_question}

Recent conversation:
{history_text}

Interviewee latest response:
{interviewee_response}
""".strip()

    def _parse_json(self, raw_text: str) -> dict | None:
        text = raw_text.strip()
        if not text:
            return None

        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return None

        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    def _heuristic_decision(self, interviewee_response: str) -> CompletenessDecision:
        lowered = interviewee_response.strip().lower()
        word_count = len([part for part in lowered.split() if part])
        uncertain = {"not sure", "don't know", "idk", "maybe", "unsure"}
        likely_incomplete = word_count < 6 or any(token in lowered for token in uncertain)

        if likely_incomplete:
            return CompletenessDecision(
                is_complete=False,
                follow_up="Thanks. Could you share a little more detail so I can capture this accurately?",
                confidence=0.35,
                reason="heuristic_incomplete",
            )

        return CompletenessDecision(
            is_complete=True,
            follow_up="",
            confidence=0.65,
            reason="heuristic_complete",
        )

from textwrap import dedent

INTERVIEW_QUESTIONS = [
    "Can you briefly tell me about the headache that makes you come in today?",
    "Other than the headache, have you noticed any weakness, numbness or problems with balance or coordination?",
    "Do your headaches tend to start on one or both sides of the head? If one side, does it go to the other side as well when it is severe?",
    "How would you describe your headaches? How do they usually feel?",
    "If you did not take any medication, how would you rate the pain intensity of your average headache from 0 (meaning No Pain) to 10 (meaning Worst Pain Imaginable)?",
    "How long does your typical headache last?",
    "What medications and on what dosage are you currently taking for headache? Let's start with the medications you take as needed.",
    "Do you take any medications on a regular basis for headache, as prevention?",
]

DEFAULT_CLARIFICATION_PROMPT = (
    "Could you share a little more detail so I can capture this accurately?"
)

CLARIFICATION_POLICY = dedent(
    """
    Ask a clarification follow-up only when the answer is incomplete, too vague,
    or misses required information for the current question. Keep follow-ups concise,
    specific, and neutral.
    """
).strip()


def build_answer_evaluation_prompt(
    *,
    question_id: int,
    question_text: str,
    latest_answer: str,
    cumulative_answer: str,
    clarification_attempts: int,
    max_clarifications: int,
    minimum_answer_word_count: int,
) -> str:
    return dedent(
        f"""
        You are evaluating transcript quality for a structured health interview.
        The assistant is collecting information only, not diagnosing or giving advice.

        {CLARIFICATION_POLICY}

        Return JSON only with this exact schema:
        {{
          "is_complete": boolean,
          "reason": string,
          "follow_up_question": string or null,
          "acknowledgment": string or null
        }}

        Rules:
        - If information is sufficient for this question, set "is_complete" to true and "follow_up_question" to null.
        - If not sufficient, set "is_complete" to false and provide one short follow-up question.
        - Keep the follow-up professional, neutral, and under 25 words.
        - Do not ask more than one follow-up question at once.
        - If clarification_attempts is already at max_clarifications, prefer completion.
        - A concise acknowledgment is optional when complete.

        Inputs:
        question_id: {question_id}
        question_text: {question_text}
        clarification_attempts: {clarification_attempts}
        max_clarifications: {max_clarifications}
        minimum_answer_word_count: {minimum_answer_word_count}

        latest_answer:
        {latest_answer}

        cumulative_answer_for_question:
        {cumulative_answer}
        """
    ).strip()

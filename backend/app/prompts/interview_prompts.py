from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from zipfile import ZipFile
import xml.etree.ElementTree as ET


@dataclass(frozen=True)
class InterviewQuestion:
    feature: str
    question: str


BASE_PROMPT_INSTRUCTIONS = (
    "You are now doing role-play. Pretend you are a headache specialist to interview a patient. "
    "You can lightly paraphrase the question, but make sure to preserve the original meaning accurately. "
    "Please SKIP any question that has been answered by the patient to a previous question. "
    "You can skip the aura Frequency and Duration questions if the patient denied having aura with the CURRENT headache condition that brought her/him in here. "
    "DO NOT talk to yourself and DO NOT think loud your reasoning such as why you are skipping a question. "
    "Try not use extensively cue words like *continue* or *move on* when transitioning to the next question. "
    "For the medication questions, please ask follow-up questions to push the patient specify whether each drug was effective. "
    "If the patient only mentioned he or she had side effects from a drug but did not specify, please ask to enumerate the specific side effects. "
    "Likewise, you may ask follow-up questions if the patient's answer does not adequately address your previous question. "
    "If there is no more question to ask, thank the patient with some closing remark."
)

DEFAULT_INTERVIEW_QUESTIONS = [
    InterviewQuestion(
        feature="Overview",
        question="Can you briefly tell me about the headache that makes you come in today?",
    ),
    InterviewQuestion(
        feature="Laterality",
        question=(
            "Do your headaches tend to start on the right, left, or both sides of the head? "
            "Also, is it always the same side, both sides, or changes from time to time?"
        ),
    ),
    InterviewQuestion(
        feature="Intensity",
        question=(
            "If you did not take any medication, how would you rate the pain intensity of your average headache "
            "from 0 (meaning No Pain) to 10 (meaning Worst Pain Imaginable)?"
        ),
    ),
    InterviewQuestion(
        feature="Redflag-Time of Day",
        question=(
            "At what time of the day are your headaches most severe? Is there a particular time of the day "
            "that the headache is always worse, or better?"
        ),
    ),
    InterviewQuestion(
        feature="Aura Visual",
        question=(
            "Some people say they SEE lights, stars or lines before or with their headache; we call it aura. "
            "Have you experienced those with the CURRENT headache you are here for?"
        ),
    ),
    InterviewQuestion(
        feature="Aura Visual-Duration",
        question="If your CURRENT headache comes with aura, how long does the aura or visual disturbance last?",
    ),
    InterviewQuestion(
        feature="Triggers",
        question=(
            "Have you noticed anything that triggers your headache, like eating/drinking certain food, "
            "specific daily activity, or environment stimulus?"
        ),
    ),
    InterviewQuestion(
        feature="Family History",
        question="Are you aware of anyone in your family with headaches?",
    ),
    InterviewQuestion(
        feature="Acute Medication-Current",
        question=(
            "What medications are you currently using as needed to relieve your headache? Please share with me "
            "the names, dose, how often you take them, if you find it effective, or have side effects."
        ),
    ),
    InterviewQuestion(
        feature="Imaging",
        question="Have you had any head MRI or CT scan?",
    ),
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


def load_interview_questions(question_bank_path: str | None = None) -> list[InterviewQuestion]:
    if not question_bank_path:
        return list(DEFAULT_INTERVIEW_QUESTIONS)

    path = Path(question_bank_path).expanduser()
    if not path.exists():
        return list(DEFAULT_INTERVIEW_QUESTIONS)

    try:
        questions = _read_questions_from_xlsx(path)
    except Exception:
        return list(DEFAULT_INTERVIEW_QUESTIONS)
    return questions or list(DEFAULT_INTERVIEW_QUESTIONS)


def build_question_generation_prompt(
    *,
    question_id: int,
    feature: str,
    question_text: str,
    prior_dialogue: str,
) -> str:
    return dedent(
        f"""
        {BASE_PROMPT_INSTRUCTIONS}

        Return only the next patient-facing question. Do not include labels, explanations, or reasoning.
        Preserve the meaning of the original question. A light natural paraphrase is allowed.

        Current agenda item:
        question_id: {question_id}
        feature: {feature}
        original_question: {question_text}

        Prior dialogue:
        {prior_dialogue or "None yet."}
        """
    ).strip()


def build_answer_evaluation_prompt(
    *,
    question_id: int,
    feature: str,
    question_text: str,
    actual_question_asked: str,
    latest_answer: str,
    cumulative_answer: str,
    clarification_attempts: int,
    max_clarifications: int,
    minimum_answer_word_count: int,
) -> str:
    return dedent(
        f"""
        {BASE_PROMPT_INSTRUCTIONS}

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
        - If information is sufficient for this agenda item, set "is_complete" to true and "follow_up_question" to null.
        - If not sufficient, set "is_complete" to false and provide one short follow-up question.
        - Keep the follow-up professional, neutral, and under 25 words.
        - Do not ask more than one follow-up question at once.
        - If clarification_attempts is already at max_clarifications, prefer completion.
        - Treat concise but fully responsive answers as complete when appropriate:
          yes/no for symptom questions, 0-10 pain ratings, clear durations, medication details, "none", or prior answered context.
        - For medication questions, ask for effectiveness or side effects if those details are missing.
        - Do not ask a generic clarification when the answer already resolves the question.
        - A concise acknowledgment is optional when complete.

        Inputs:
        question_id: {question_id}
        feature: {feature}
        original_question: {question_text}
        actual_question_asked: {actual_question_asked}
        clarification_attempts: {clarification_attempts}
        max_clarifications: {max_clarifications}
        minimum_answer_word_count: {minimum_answer_word_count}

        latest_answer:
        {latest_answer}

        cumulative_answer_for_question:
        {cumulative_answer}
        """
    ).strip()


def _read_questions_from_xlsx(path: Path) -> list[InterviewQuestion]:
    ns = {
        "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    }

    with ZipFile(path) as archive:
        shared_strings = _read_shared_strings(archive, ns)
        sheet_path = _find_first_sheet_path(archive, ns)
        root = ET.fromstring(archive.read(sheet_path))

    rows: list[dict[str, str]] = []
    for row in root.findall(".//main:sheetData/main:row", ns):
        cells = {
            _column_name(cell.attrib.get("r", "")): _cell_value(cell, shared_strings, ns)
            for cell in row.findall("main:c", ns)
        }
        if cells:
            rows.append(cells)

    if not rows:
        return []

    header = {column: value.strip().lower() for column, value in rows[0].items()}
    feature_column = _find_header_column(header, "feature")
    question_column = _find_header_column(header, "question")
    if not feature_column or not question_column:
        return []

    questions: list[InterviewQuestion] = []
    for row in rows[1:]:
        feature = row.get(feature_column, "").strip()
        question = row.get(question_column, "").strip()
        if feature and question:
            questions.append(InterviewQuestion(feature=feature, question=question))

    return questions


def _read_shared_strings(archive: ZipFile, ns: dict[str, str]) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []

    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    strings: list[str] = []
    text_tag = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t"
    for item in root.findall("main:si", ns):
        strings.append("".join(text.text or "" for text in item.iter(text_tag)))
    return strings


def _find_first_sheet_path(archive: ZipFile, ns: dict[str, str]) -> str:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
    sheet = workbook.find("main:sheets/main:sheet", ns)
    if sheet is None:
        raise ValueError("No worksheet found in question bank.")

    relation_id = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
    target = rel_map[relation_id].lstrip("/")
    return target if target.startswith("xl/") else f"xl/{target}"


def _column_name(cell_reference: str) -> str:
    return "".join(char for char in cell_reference if char.isalpha())


def _cell_value(cell: ET.Element, shared_strings: list[str], ns: dict[str, str]) -> str:
    value = cell.find("main:v", ns)
    raw_value = "" if value is None else value.text or ""
    cell_type = cell.attrib.get("t")

    if cell_type == "s" and raw_value:
        return shared_strings[int(raw_value)]

    if cell_type == "inlineStr":
        inline = cell.find("main:is", ns)
        if inline is None:
            return ""
        text_tag = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t"
        return "".join(text.text or "" for text in inline.iter(text_tag))

    return raw_value


def _find_header_column(header: dict[str, str], header_name: str) -> str | None:
    for column, value in header.items():
        if value == header_name:
            return column
    return None

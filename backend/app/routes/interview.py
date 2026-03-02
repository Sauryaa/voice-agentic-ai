import base64
import binascii
import json

from fastapi import APIRouter, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response

from backend.app.config import get_settings
from backend.app.models.schemas import (
    InterviewRespondRequest,
    InterviewRespondResponse,
    NextQuestionRequest,
    NextQuestionResponse,
    SessionLog,
    StartSessionRequest,
    StartSessionResponse,
    TranscribeRequest,
    TranscribeResponse,
)
from backend.app.services.gemini_agent import GeminiInterviewAgent
from backend.app.services.interview_manager import InterviewManager
from backend.app.services.speech_to_text import SpeechToTextService

settings = get_settings()
gemini_agent = GeminiInterviewAgent(settings)
interview_manager = InterviewManager(settings, gemini_agent)
speech_to_text_service = SpeechToTextService(default_language_code=settings.stt_language_code)

router = APIRouter(prefix="/api", tags=["interview"])


@router.post("/session/start", response_model=StartSessionResponse)
def start_session(payload: StartSessionRequest) -> StartSessionResponse:
    return interview_manager.start_session(mode=payload.mode)


@router.post("/transcribe", response_model=TranscribeResponse)
def transcribe(payload: TranscribeRequest) -> TranscribeResponse:
    try:
        audio_bytes = _decode_audio_payload(payload.audio_base64)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not audio_bytes:
        raise HTTPException(status_code=400, detail="No audio content provided.")

    try:
        transcript = speech_to_text_service.transcribe_audio(
            audio_bytes=audio_bytes,
            mime_type=payload.mime_type,
            language_code=payload.language_code,
            sample_rate_hz=payload.sample_rate_hz,
        )
    except Exception as exc:  # pragma: no cover - external service dependent
        raise HTTPException(status_code=502, detail=f"Speech-to-Text failed: {exc}") from exc

    return TranscribeResponse(text=transcript, mime_type=payload.mime_type)


@router.post("/interview/respond", response_model=InterviewRespondResponse)
def respond(payload: InterviewRespondRequest) -> InterviewRespondResponse:
    try:
        return interview_manager.respond(session_id=payload.session_id, text=payload.text)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/interview/next", response_model=NextQuestionResponse)
def next_question(payload: NextQuestionRequest) -> NextQuestionResponse:
    try:
        return interview_manager.next_question(
            session_id=payload.session_id,
            force=payload.force,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/session/{session_id}/log", response_model=SessionLog)
def session_log(session_id: str) -> SessionLog:
    try:
        return interview_manager.get_session_log(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/session/{session_id}/download")
def download_session_log(session_id: str) -> Response:
    try:
        log = interview_manager.get_session_log(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    payload = jsonable_encoder(log)
    content = json.dumps(payload, indent=2)

    return Response(
        content=content,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="interview_{session_id}.json"'
        },
    )


def _decode_audio_payload(audio_base64: str) -> bytes:
    if not audio_base64:
        raise ValueError("Audio payload is empty.")

    payload = audio_base64.strip()
    if payload.startswith("data:") and "," in payload:
        payload = payload.split(",", maxsplit=1)[1]

    try:
        return base64.b64decode(payload, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Invalid base64 audio payload.") from exc

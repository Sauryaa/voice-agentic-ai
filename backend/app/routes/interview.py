import base64
import binascii
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response
from google.cloud import recaptchaenterprise_v1

from backend.app.config import get_settings
from backend.app.limiter import limiter
from backend.app.models.schemas import (
    InterviewRespondRequest,
    InterviewRespondResponse,
    NextQuestionRequest,
    NextQuestionResponse,
    SessionLog,
    StartSessionRequest,
    StartSessionResponse,
    TextToSpeechVoiceList,
    TranscribeRequest,
    TranscribeResponse,
)
from backend.app.services.gemini_agent import GeminiInterviewAgent
from backend.app.services.interview_manager import InterviewManager
from backend.app.services.speech_to_text import SpeechToTextService
from backend.app.services.text_to_speech import TextToSpeechService

settings = get_settings()
logger = logging.getLogger(__name__)
gemini_agent = GeminiInterviewAgent(settings)
interview_manager = InterviewManager(settings, gemini_agent)
speech_to_text_service = SpeechToTextService(default_language_code=settings.stt_language_code)
text_to_speech_service = TextToSpeechService()

router = APIRouter(prefix="/api", tags=["interview"])


@router.post("/session/start", response_model=StartSessionResponse)
@limiter.limit("10/minute")
def start_session(request: Request, payload: StartSessionRequest) -> StartSessionResponse:
    if settings.recaptcha_enabled:
        if not payload.recaptcha_token:
            raise HTTPException(status_code=400, detail="reCAPTCHA verification is required.")
        _verify_recaptcha_token(payload.recaptcha_token, request)

    return interview_manager.start_session(mode=payload.mode)


@router.post("/transcribe", response_model=TranscribeResponse)
@limiter.limit("10/minute")
def transcribe(request: Request, payload: TranscribeRequest) -> TranscribeResponse:
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
# Core interview submission route: limited to 10 requests/minute per client IP.
@limiter.limit("10/minute")
def respond(request: Request, payload: InterviewRespondRequest) -> InterviewRespondResponse:
    try:
        return interview_manager.respond(session_id=payload.session_id, text=payload.text)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/interview/next", response_model=NextQuestionResponse)
@limiter.limit("10/minute")
def next_question(request: Request, payload: NextQuestionRequest) -> NextQuestionResponse:
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
        log = interview_manager.get_conversation_output(session_id)
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


@router.get("/tts/voices", response_model=TextToSpeechVoiceList)
def list_text_to_speech_voices(language_code: str | None = None) -> TextToSpeechVoiceList:
    try:
        return text_to_speech_service.list_voices(language_code=language_code)
    except Exception as exc:  # pragma: no cover - external service dependent
        raise HTTPException(status_code=502, detail=f"Text-to-Speech voice listing failed: {exc}") from exc


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


def _verify_recaptcha_token(token: str, request: Request) -> None:
    clean_token = token.strip()
    if not clean_token:
        raise HTTPException(status_code=400, detail="reCAPTCHA verification is required.")

    project_id = settings.google_cloud_project.strip()
    site_key = settings.recaptcha_site_key.strip()
    expected_action = settings.recaptcha_expected_action.strip()
    min_score = settings.recaptcha_min_score

    if not project_id or not site_key:
        logger.error(
            "reCAPTCHA Enterprise is enabled but missing project_id or site_key "
            "(project_id_present=%s, site_key_present=%s)",
            bool(project_id),
            bool(site_key),
        )
        raise HTTPException(
            status_code=500,
            detail="reCAPTCHA verification is not configured on the server.",
        )

    event = recaptchaenterprise_v1.Event(
        token=clean_token,
        site_key=site_key,
        expected_action=expected_action,
        user_ip_address=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", ""),
    )
    assessment = recaptchaenterprise_v1.Assessment(event=event)
    assessment_request = recaptchaenterprise_v1.CreateAssessmentRequest(
        parent=f"projects/{project_id}",
        assessment=assessment,
    )

    try:
        response = recaptchaenterprise_v1.RecaptchaEnterpriseServiceClient().create_assessment(
            request=assessment_request,
            timeout=settings.recaptcha_verify_timeout_seconds,
        )
    except Exception as exc:  # pragma: no cover - external service dependent
        logger.exception("reCAPTCHA Enterprise assessment request failed.")
        raise HTTPException(
            status_code=502,
            detail=f"reCAPTCHA verification failed: {exc}",
        ) from exc

    token_properties = response.token_properties
    risk_analysis = response.risk_analysis
    invalid_reason = _enum_name(
        recaptchaenterprise_v1.TokenProperties.InvalidReason,
        token_properties.invalid_reason,
    )
    risk_reasons = _enum_names(
        recaptchaenterprise_v1.RiskAnalysis.ClassificationReason,
        risk_analysis.reasons,
    )

    logger.info(
        "reCAPTCHA assessment received: valid=%s action=%s expected_action=%s "
        "score=%.3f min_score=%.3f hostname=%s invalid_reason=%s reasons=%s "
        "assessment=%s",
        token_properties.valid,
        token_properties.action,
        expected_action,
        risk_analysis.score,
        min_score,
        token_properties.hostname,
        invalid_reason,
        risk_reasons,
        response.name,
    )

    if not token_properties.valid:
        raise HTTPException(
            status_code=403,
            detail=f"reCAPTCHA token is invalid ({invalid_reason}).",
        )

    if expected_action and token_properties.action != expected_action:
        logger.warning(
            "reCAPTCHA action mismatch: actual=%s expected=%s assessment=%s",
            token_properties.action,
            expected_action,
            response.name,
        )
        raise HTTPException(status_code=403, detail="reCAPTCHA action mismatch.")

    if risk_analysis.score < min_score:
        logger.warning(
            "reCAPTCHA score below threshold: score=%.3f min_score=%.3f reasons=%s "
            "assessment=%s",
            risk_analysis.score,
            min_score,
            risk_reasons,
            response.name,
        )
        raise HTTPException(
            status_code=403,
            detail="reCAPTCHA verification did not meet the required score.",
        )


def _enum_name(enum_cls: type, value: object) -> str:
    try:
        return enum_cls(value).name
    except Exception:
        return str(value)


def _enum_names(enum_cls: type, values: list[object]) -> list[str]:
    return [_enum_name(enum_cls, value) for value in values]

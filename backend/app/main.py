from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .interview_engine import InterviewEngine
from .llm_service import GeminiInterviewEvaluator
from .logging_store import SessionStore
from .models import StartSessionRequest, StartSessionResponse, TextTurnRequest, TurnResponse
from .speech_service import SpeechToTextService


settings = get_settings()
store = SessionStore(logs_dir=settings.logs_dir)
evaluator = GeminiInterviewEvaluator(
    project=settings.google_cloud_project,
    location=settings.google_cloud_location,
    model_name=settings.gemini_model,
)
engine = InterviewEngine(store=store, evaluator=evaluator)
speech_service = SpeechToTextService(language_code=settings.speech_language_code)

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/session/start", response_model=StartSessionResponse)
def start_session(payload: StartSessionRequest | None = None) -> StartSessionResponse:
    participant_id = payload.participant_id if payload else None
    session = engine.start_session(participant_id=participant_id, company_name=settings.company_name)
    return StartSessionResponse(
        session_id=session.session_id,
        message=session.turns[-1].text,
        current_question_index=session.current_question_index,
        total_questions=len(session.agenda),
        interview_complete=session.completed,
    )


@app.post("/api/session/{session_id}/text-turn", response_model=TurnResponse)
async def text_turn(session_id: str, payload: TextTurnRequest) -> TurnResponse:
    try:
        result = await run_in_threadpool(engine.process_transcript, session_id, payload.text)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return TurnResponse(
        session_id=result.session.session_id,
        transcript=result.transcript,
        assistant_message=result.assistant_message,
        current_question_index=result.session.current_question_index,
        total_questions=len(result.session.agenda),
        interview_complete=result.session.completed,
        question_completed=result.question_completed,
        completion_confidence=result.completion_confidence,
    )


@app.post("/api/session/{session_id}/voice-turn", response_model=TurnResponse)
async def voice_turn(session_id: str, audio: UploadFile = File(...)) -> TurnResponse:
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Audio upload is empty")

    try:
        transcript = await run_in_threadpool(speech_service.transcribe_webm_opus, audio_bytes)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not transcript:
        transcript = ""

    try:
        result = await run_in_threadpool(engine.process_transcript, session_id, transcript)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return TurnResponse(
        session_id=result.session.session_id,
        transcript=result.transcript,
        assistant_message=result.assistant_message,
        current_question_index=result.session.current_question_index,
        total_questions=len(result.session.agenda),
        interview_complete=result.session.completed,
        question_completed=result.question_completed,
        completion_confidence=result.completion_confidence,
    )


@app.get("/api/session/{session_id}/log")
def get_session_log(session_id: str) -> dict:
    session = store.load(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return session.model_dump(mode="json")


frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

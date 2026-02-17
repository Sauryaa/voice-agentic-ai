# Mayo Clinic Voice Interview Agent (Prototype)

This repo now contains a web-based prototype AI agent for agenda-guided headache interviews.

- Voice input: browser recording + Google Speech-to-Text
- Adaptive progression: Gemini checks if each answer is complete before moving forward
- Structured agenda: fixed 8 interview questions (provided in your brief)
- JSON conversation logging: full turn history with speaker labels and metadata

## Architecture

- Backend: FastAPI (`backend/app/main.py`)
- AI evaluation: Gemini on Vertex AI (`backend/app/llm_service.py`)
- Speech transcription: Google Cloud Speech-to-Text (`backend/app/speech_service.py`)
- Session/log store: file-based JSON logs (`backend/logs/*.json`)
- Frontend: static HTML/CSS/JS (`frontend/`)

## Local Run

1. Create a Python environment and install backend dependencies:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Configure environment variables:

```bash
cp .env.example .env
```

Edit `backend/.env`:
- `GOOGLE_CLOUD_PROJECT`
- `GOOGLE_CLOUD_LOCATION` (e.g. `us-central1`)
- optional: `GEMINI_MODEL`, `SPEECH_LANGUAGE_CODE`, `CORS_ALLOW_ORIGINS`

3. Authenticate Google Cloud credentials (local dev):

```bash
gcloud auth application-default login
```

4. Start server:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

5. Open the app:

`http://localhost:8080`

## API Endpoints

- `POST /api/session/start`
- `POST /api/session/{session_id}/voice-turn` (`multipart/form-data`, field `audio`)
- `POST /api/session/{session_id}/text-turn`
- `GET /api/session/{session_id}/log`
- `GET /api/health`

## Cloud Run Deployment (GCP)

From repo root:

```bash
gcloud run deploy voice-agentic-ai \
  --source . \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID,GOOGLE_CLOUD_LOCATION=us-central1
```

Important IAM/service setup:
- Enable APIs: Vertex AI API, Cloud Speech-to-Text API, Cloud Run API
- Grant Cloud Run service account:
  - `roles/aiplatform.user`
  - `roles/speech.client`

## Notes About the Adaptive Flow

- The app advances to the next question only when Gemini marks the current answer as complete.
- If incomplete, the agent asks a follow-up and stays on the same agenda question.
- If Gemini is unavailable, a conservative heuristic fallback is used.

## Files Added

- `backend/app/config.py`
- `backend/app/agenda.py`
- `backend/app/models.py`
- `backend/app/logging_store.py`
- `backend/app/speech_service.py`
- `backend/app/llm_service.py`
- `backend/app/interview_engine.py`
- `backend/app/main.py`
- `backend/requirements.txt`
- `backend/.env.example`
- `frontend/index.html`
- `frontend/styles.css`
- `frontend/app.js`
- `Dockerfile`
- `.dockerignore`
- `.gitignore`

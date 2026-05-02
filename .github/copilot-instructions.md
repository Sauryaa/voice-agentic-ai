# Copilot Instructions: Voice Health Interview Prototype

Web-based voice chatbot for conducting structured headache interviews using FastAPI, Google Cloud Speech-to-Text, and Vertex AI Gemini.

## Build, Test, and Run

### Local Development

```bash
# Setup (from project root)
python -m venv .venv
source .venv/bin/activate  # or `.venv\Scripts\activate` on Windows
pip install -r backend/requirements.txt
cp .env.example .env

# Run the server
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8080
```

Access the frontend at `http://localhost:8080`.

### Authentication

Requires Google Cloud Application Default Credentials:

```bash
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
```

### Deployment

Deploy to Cloud Run (from project root):

```bash
./deploy.sh           # Default tag: timestamp-based
./deploy.sh v2.1      # Custom tag
```

The deployment script:
- Builds Docker image locally
- Pushes to Artifact Registry
- Deploys to Cloud Run, creating the service on first deploy if needed
- Uses `PROJECT_ID` or your active `gcloud` project
- Uses service account: `voice-agentic-ai-runner@YOUR_PROJECT_ID.iam.gserviceaccount.com`

## Architecture

### Project Structure

```
backend/app/
  main.py                    # FastAPI app, CORS, static file mounting
  config.py                  # Pydantic Settings with .env support
  limiter.py                 # SlowAPI rate limiter instance
  
  routes/
    health.py                # Health check endpoint
    interview.py             # All /api/* endpoints
  
  services/
    interview_manager.py     # Session state, question flow logic
    gemini_agent.py          # Answer evaluation via Vertex AI
    speech_to_text.py        # Google Cloud Speech-to-Text wrapper
  
  models/
    schemas.py               # Pydantic models for API contracts
  
  prompts/
    interview_prompts.py     # Question set, evaluation prompts

frontend/
  index.html                 # Single-page UI
  app.js                     # Browser audio capture, session management
  styles.css
```

### Key Flows

**Session lifecycle:**
1. `POST /api/session/start` → creates in-memory session, returns first question
2. User records answer → frontend transcribes via `POST /api/transcribe`
3. `POST /api/interview/respond` → Gemini evaluates if answer is complete
4. If incomplete & attempts < max: return clarification prompt (same question_id)
5. If complete: advance to next question or mark interview complete
6. `GET /api/session/{id}/download` → export structured JSON transcript

**Answer evaluation (gemini_agent.py):**
- Uses Gemini to parse answer quality based on question context
- Falls back to heuristics if Gemini unavailable (word count, keyword matching)
- Returns: `{is_complete, reason, follow_up_question, acknowledgment}`
- Heuristics have question-specific rules (e.g., Q5 must contain 0-10, Q6 must mention time units)

**Session state (interview_manager.py):**
- In-memory only (no database)
- Thread-safe with RLock
- Tracks: current_question_index, active_prompt, turn-by-turn history, clarification attempts
- All turns stored with: speaker, type, text, question_id, timestamp

**Frontend modes:**
- `user_controlled`: user manually starts/stops recording
- `agent_controlled`: browser TTS speaks prompts, auto-stops after 3s silence (basic amplitude threshold, not production VAD)

### API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Backend health check |
| POST | `/api/session/start` | Create session, get first question |
| POST | `/api/transcribe` | Convert audio to text (Google STT) |
| POST | `/api/interview/respond` | Submit answer, get evaluation |
| POST | `/api/interview/next` | Force skip to next question |
| GET | `/api/session/{id}/log` | Get session transcript |
| GET | `/api/session/{id}/download` | Download JSON transcript |

All interview endpoints are rate-limited to 10 requests/minute per client IP via SlowAPI.

## Key Conventions

### Environment Configuration

Settings in `backend/app/config.py` use Pydantic Settings with `.env` support. All settings have defaults except Google Cloud project/location. Key variables:

- `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `GEMINI_MODEL`
- `MAX_CLARIFICATIONS_PER_QUESTION=2` - max follow-ups before forcing next question
- `MINIMUM_ANSWER_WORD_COUNT=5` - heuristic threshold
- `INCLUDE_ACKNOWLEDGMENT_TURNS=false` - whether Gemini's acknowledgments are logged as turns

### Session Management

- Sessions live in-memory (non-persistent) in `InterviewManager._sessions` dict
- Session ID is UUID4, generated on `/api/session/start`
- No cleanup implemented; sessions persist until server restart
- Thread-safe access via `_lock` (RLock)

### Turn Types and Logging

Every interaction is a "turn" with fields:
- `turn_index`: sequential counter starting at 1
- `speaker`: "agent" or "interviewee"
- `question_id`: 1-8 (or null for completion)
- `type`: "question", "answer", "clarification", "acknowledgment", "completion"
- `text`: actual content
- `timestamp`: UTC datetime

The JSON export maintains strict turn order. No confidence scores are included.

### Question Flow Logic

Fixed 8-question agenda (`INTERVIEW_QUESTIONS` in `prompts/interview_prompts.py`). Questions asked in order, no branching. Logic:

1. Ask question Q (type: "question")
2. Receive answer → evaluate
3. If incomplete AND clarification_attempts < max:
   - Increment attempt counter
   - Ask clarification (type: "clarification", same question_id)
   - Go to step 2
4. If complete OR max attempts reached:
   - Optionally add acknowledgment turn
   - Advance to Q+1 or mark complete

### Gemini Prompt Engineering

`build_answer_evaluation_prompt()` in `prompts/interview_prompts.py` constructs structured JSON request prompts:
- Includes question context, cumulative answer, attempt count
- Enforces strict JSON schema response
- Policies: prefer completion at max attempts, keep follow-ups <25 words, single follow-up per evaluation

The model is initialized once at service startup in `GeminiInterviewAgent.__init__`.

### Audio Processing

Frontend uses MediaRecorder API with `audio/webm` (default mime type). Audio sent to backend as base64-encoded string. Backend:
- Strips data URI prefix if present
- Validates base64 in `_decode_audio_payload()`
- Passes raw bytes to Google Cloud Speech-to-Text
- Accepts optional `sample_rate_hz` and `language_code` params (defaults to `STT_LANGUAGE_CODE` from env)

Agent-controlled silence detection is browser-side only (Web Audio API amplitude analysis). Not used in STT.

### Error Handling

- `KeyError` → 404 (session not found)
- `ValueError` → 400 (invalid payload or state)
- External service failures (Gemini, STT) → 502 with descriptive message
- Rate limit exceeded → 429 with stable JSON payload via custom handler

### CORS Policy

Controlled via `CORS_ORIGINS` env var (comma-separated or `*`). Frontend served from same origin by mounting `/frontend` as static files, so `*` works for local dev.

### Deployment Context

- Target: Cloud Run in `us-central1`
- Service name: `voice-agentic-ai`
- Artifact Registry: `us-central1-docker.pkg.dev/YOUR_PROJECT_ID/voice-agentic-ai/voice-agentic-ai`
- Runtime service account needs: `roles/aiplatform.user`, `roles/speech.client`, `roles/secretmanager.secretAccessor`
- Dockerfile uses Python 3.11-slim, sets `PYTHONPATH=/app`, exposes port 8080

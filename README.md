# Voice Health Interview Prototype

Web-based voice chatbot prototype for an agenda-guided headache interview.

- Backend: FastAPI (Python)
- Speech transcription: Google Cloud Speech-to-Text
- Adaptive follow-up logic: Vertex AI Gemini
- Frontend: static HTML/CSS/JavaScript with browser microphone APIs
- Deployment target: Cloud Run

## What this prototype does

- Runs an 8-question headache interview in fixed order.
- Supports two modes:
  - `user_controlled`: user starts/stops recording each answer.
  - `agent_controlled`: browser speaks each prompt, auto-records, and stops after ~3 seconds of silence.
- Uses Gemini to decide if an answer is complete or needs clarification.
- Stores structured turn-by-turn JSON transcript in-memory per session.
- Exports transcript using **Download JSON** (pretty-printed indented JSON).
- Includes a live microphone input test meter.

## Question set

1. Can you briefly tell me about the headache that makes you come in today?
2. Other than the headache, have you noticed any weakness, numbness or problems with balance or coordination?
3. Do your headaches tend to start on one or both sides of the head? If one side, does it go to the other side as well when it is severe?
4. How would you describe your headaches? How do they usually feel?
5. If you did not take any medication, how would you rate the pain intensity of your average headache from 0 (meaning No Pain) to 10 (meaning Worst Pain Imaginable)?
6. How long does your typical headache last?
7. What medications and on what dosage are you currently taking for headache? Let's start with the medications you take as needed.
8. Do you take any medications on a regular basis for headache, as prevention?

## Project structure

```
backend/
  app/
    main.py
    config.py
    routes/
      health.py
      interview.py
    services/
      speech_to_text.py
      gemini_agent.py
      interview_manager.py
    models/
      schemas.py
    prompts/
      interview_prompts.py
  requirements.txt
frontend/
  index.html
  styles.css
  app.js
.env.example
Dockerfile
cloudbuild.yaml
```

## Prerequisites

- Python 3.11+
- Google Cloud project with APIs enabled:
  - Vertex AI API
  - Cloud Speech-to-Text API
- Application Default Credentials for local development:

```bash
gcloud auth application-default login
gcloud config set project voice-agentic-ai-487022
```

## Local setup

1. Create and activate a virtual environment.
2. Install dependencies.
3. Copy `.env.example` to `.env` and adjust values if needed.
4. Run FastAPI server.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8080
```

Open `http://localhost:8080`.

## Environment variables

See `.env.example`. Key values:

- `GOOGLE_CLOUD_PROJECT=voice-agentic-ai-487022`
- `GOOGLE_CLOUD_LOCATION=us-central1`
- `GEMINI_MODEL=gemini-2.5-flash`
- `CORS_ORIGINS=*` (development default)

## API endpoints

- `GET /health`
- `POST /api/session/start`
- `POST /api/transcribe`
- `POST /api/interview/respond`
- `POST /api/interview/next`
- `GET /api/session/{session_id}/log`
- `GET /api/session/{session_id}/download`

## JSON logging notes

Transcript JSON includes session metadata, ordered turns, speaker labels, question IDs, turn type, and completion status.

No confidence field is included in this prototype because a stable and interpretable confidence definition was not established across all stages.

## Agent-controlled mode note

The "auto-stop after silence" behavior is a browser-side approximation based on Web Audio API amplitude thresholding plus a 3-second silence timer. It is practical for prototype use but not production-grade VAD.

## Deploying the second prototype

This project includes `deploy.sh` to publish a new container image and deploy it as a new revision of an existing Cloud Run service (same service name, same URL).

### Required runtime service account

Use service account:

- `voice-agentic-ai-runner@voice-agentic-ai-487022.iam.gserviceaccount.com`

Grant runtime roles:

- `roles/aiplatform.user`
- `roles/speech.client`
- `roles/secretmanager.secretAccessor`

### One-command deploy (local Docker + Artifact Registry + Cloud Run)

From project root:

```bash
./deploy.sh
```

Use a custom tag:

```bash
./deploy.sh v2
./deploy.sh v2.1
```

`deploy.sh` performs these steps:

1. Verifies `gcloud` and `docker`.
2. Sets the project to `voice-agentic-ai-487022`.
3. Lists Cloud Run services in `us-central1` for service-name verification.
4. Verifies service `voice-agentic-ai` exists before deploy.
5. Ensures Artifact Registry repository `voice-agentic-ai` exists (creates it if missing).
6. Configures Docker auth for `us-central1-docker.pkg.dev`.
7. Builds image locally with Docker.
8. Pushes image to Artifact Registry.
9. Deploys a new revision to Cloud Run with `--allow-unauthenticated`.

### Helper commands

List Cloud Run services in region:

```bash
gcloud run services list --region=us-central1 --project=voice-agentic-ai-487022
```

Create Artifact Registry repository if needed:

```bash
gcloud artifacts repositories create voice-agentic-ai \
  --repository-format=docker \
  --location=us-central1 \
  --description="Docker images for voice-agentic-ai Cloud Run deployments" \
  --project=voice-agentic-ai-487022
```

Artifact Registry image path format used by the script:

```text
us-central1-docker.pkg.dev/voice-agentic-ai-487022/voice-agentic-ai/voice-agentic-ai:<TAG>
```

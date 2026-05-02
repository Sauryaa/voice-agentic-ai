# Voice Health Interview Prototype

Voice-based, agenda-guided Mayo Clinic prototype for collecting a structured headache history. The FastAPI backend serves a static browser UI, manages interview state, calls Google Cloud Speech-to-Text for transcription, uses Vertex AI Gemini for natural question phrasing and answer completeness checks, and exports reviewable JSON logs.

## Project Overview

- Interview agenda: 10 headache questions from the supervisor XLSX schema (`Feature`, `Question`).
- Base persona: headache specialist role-play instructions from `base prompt instructions.txt`.
- Flow: one question at a time, with concise clarification before moving forward when answers are incomplete.
- Logs: download JSON in the sample-compatible `{"dialogue": [...]}` structure, including `feature`, original `question`, `actual_question_asked`, `answer`, and `conversation_narrative`.
- Recording: browser recording caps at 15 minutes and agent-controlled mode moves forward after 1.5 seconds of silence.
- Voice utilities: `GET /api/tts/voices` and `python3 -m backend.list_tts_voices` list Google Cloud Text-to-Speech voices.

## Tech Stack

- Backend: Python, FastAPI, Uvicorn, Pydantic settings.
- Frontend: static HTML, CSS, JavaScript, Web Audio API, MediaRecorder API, browser speech synthesis.
- Speech-to-text: Google Cloud Speech-to-Text.
- LLM: Vertex AI Gemini 2.5 Flash.
- Text-to-speech voice inventory: Google Cloud Text-to-Speech voice listing API.
- Deployment: Docker, Google Cloud Run, optional Cloud Build and Artifact Registry.

## Project Structure

```text
backend/
  app/
    main.py
    config.py
    routes/
      health.py
      interview.py
      public_config.py
    services/
      gemini_agent.py
      interview_manager.py
      speech_to_text.py
      text_to_speech.py
    prompts/
      interview_prompts.py
    models/
      schemas.py
  list_tts_voices.py
  requirements.txt
frontend/
  index.html
  styles.css
  app.js
data/
  headache_questions-ForVoicePrototyping.xlsx
  base prompt instructions.txt
  conversation_sample_output.json
.env.example
Dockerfile
cloudbuild.yaml
deploy.sh
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
.venv/bin/pip install -r backend/requirements.txt
cp .env.example .env
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
```

For local testing with the supervisor XLSX, set `QUESTION_BANK_PATH` in `.env`:

```bash
QUESTION_BANK_PATH=data/headache_questions-ForVoicePrototyping.xlsx
```

If `QUESTION_BANK_PATH` is empty or unavailable, the app uses the same 10-question fallback agenda embedded in `backend/app/prompts/interview_prompts.py`.

## Environment Variables

- `GOOGLE_CLOUD_PROJECT`: Google Cloud project ID.
- `GOOGLE_CLOUD_LOCATION`: Vertex AI region, for example `us-central1`.
- `GEMINI_MODEL`: Gemini model name, default `gemini-2.5-flash`.
- `STT_LANGUAGE_CODE`: Speech-to-Text language, default `en-US`.
- `SILENCE_TIMEOUT_SECONDS`: silence wait before auto-stop, default `1.5`.
- `MAX_RECORDING_SECONDS`: max recording/session capture length, default `900`.
- `QUESTION_BANK_PATH`: optional XLSX path with `Feature` and `Question` columns.
- `MAX_CLARIFICATIONS_PER_QUESTION`: max follow-ups before moving forward.
- `MINIMUM_ANSWER_WORD_COUNT`: heuristic fallback threshold when Gemini is unavailable.
- `GEMINI_TEMPERATURE`: answer-evaluation temperature.
- `GEMINI_QUESTION_TEMPERATURE`: question-phrasing temperature.
- `INCLUDE_ACKNOWLEDGMENT_TURNS`: optionally log short acknowledgments.
- `CORS_ORIGINS`: comma-separated allowed origins, default `*`.
- `RECAPTCHA_SITE_KEY`: enables reCAPTCHA Enterprise when set.
- `RECAPTCHA_EXPECTED_ACTION`, `RECAPTCHA_MIN_SCORE`, `RECAPTCHA_VERIFY_TIMEOUT_SECONDS`: reCAPTCHA settings.

Keep real values in `.env` only. `.env.example` is intentionally safe to commit and contains placeholders.

## Run Locally

```bash
source .venv/bin/activate
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8080
```

Open `http://localhost:8080`.

Useful checks:

```bash
curl http://localhost:8080/health
curl http://localhost:8080/api/public-config
curl "http://localhost:8080/api/tts/voices?language_code=en-US"
python3 -m backend.list_tts_voices --language-code en-US
```

## Test The Interview Flow

1. Start the local server and open the UI.
2. Click **Enable Microphone** and verify the meter moves.
3. Click **Start Interview**.
4. In user-controlled mode, record one answer at a time. In agent-controlled mode, the browser speaks a prompt, records, and auto-stops after silence.
5. Confirm the prompt does not advance until the backend marks the answer complete or the clarification limit is reached.
6. Click **Download JSON** and verify the file has:

```json
{
  "dialogue": [
    {
      "feature": "Overview",
      "question": "Can you briefly tell me about the headache that makes you come in today?",
      "actual_question_asked": "Can you briefly tell me about the headache that makes you come in today?",
      "answer": "...",
      "conversation_narrative": ["Agent: ...", "Interviewee: ..."]
    }
  ]
}
```

You can also inspect the full session log, including turn timestamps and speaker labels:

```bash
curl http://localhost:8080/api/session/SESSION_ID/log
```

## Google Cloud Run Deployment

The app is Cloud Run-ready as a single container: Uvicorn runs FastAPI, and FastAPI serves the static frontend from `frontend/`.

Enable required APIs:

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  aiplatform.googleapis.com \
  speech.googleapis.com \
  texttospeech.googleapis.com \
  recaptchaenterprise.googleapis.com
```

Create a runtime service account:

```bash
export PROJECT_ID="YOUR_PROJECT_ID"
export RUNTIME_SERVICE_ACCOUNT="voice-agentic-ai-runner@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud iam service-accounts create voice-agentic-ai-runner \
  --display-name="Voice interview Cloud Run runtime" \
  --project="${PROJECT_ID}"

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${RUNTIME_SERVICE_ACCOUNT}" \
  --role="roles/aiplatform.user"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${RUNTIME_SERVICE_ACCOUNT}" \
  --role="roles/speech.client"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${RUNTIME_SERVICE_ACCOUNT}" \
  --role="roles/recaptchaenterprise.agent"
```

The Text-to-Speech voice listing endpoint uses Application Default Credentials and the Cloud Text-to-Speech API. Google documents `voices:list` as requiring the `cloud-platform` OAuth scope.

Deploy from source:

```bash
export PROJECT_ID="YOUR_PROJECT_ID"
export REGION="us-central1"
export SERVICE_NAME="voice-agentic-ai"
export RUNTIME_SERVICE_ACCOUNT="voice-agentic-ai-runner@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud config set project "${PROJECT_ID}"

gcloud run deploy "${SERVICE_NAME}" \
  --source . \
  --region "${REGION}" \
  --allow-unauthenticated \
  --service-account "${RUNTIME_SERVICE_ACCOUNT}" \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=${REGION},GEMINI_MODEL=gemini-2.5-flash,CORS_ORIGINS=*,SILENCE_TIMEOUT_SECONDS=1.5,MAX_RECORDING_SECONDS=900,QUESTION_BANK_PATH=data/headache_questions-ForVoicePrototyping.xlsx"
```

If reCAPTCHA Enterprise is required, append:

```text
,RECAPTCHA_SITE_KEY=YOUR_SITE_KEY,RECAPTCHA_EXPECTED_ACTION=start_interview,RECAPTCHA_MIN_SCORE=0.5
```

## Deploy With deploy.sh

```bash
export PROJECT_ID="YOUR_PROJECT_ID"
export REGION="us-central1"
export SERVICE_NAME="voice-agentic-ai"
export RUNTIME_SERVICE_ACCOUNT="voice-agentic-ai-runner@${PROJECT_ID}.iam.gserviceaccount.com"
./deploy.sh
```

The script builds the Docker image, pushes it to Artifact Registry, and deploys FastAPI/Uvicorn to Cloud Run. It passes `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `CORS_ORIGINS`, `SILENCE_TIMEOUT_SECONDS`, `MAX_RECORDING_SECONDS`, and optional reCAPTCHA settings as runtime environment variables.

## Notes

- Session state is in memory. Logs are lost if the container restarts or traffic lands on another instance.
- Browser text-to-speech is used for speaking interview prompts; Google Cloud Text-to-Speech voice listing is available for selecting future server-side TTS voices.
- Do not commit `.env` or service account keys.

#!/usr/bin/env bash
set -euo pipefail

# Deploys a Cloud Run service using:
# local Docker build -> Artifact Registry push -> Cloud Run deploy
# Configuration can be overridden with environment variables.

REGION="${REGION:-${GOOGLE_CLOUD_LOCATION:-us-central1}}"
SERVICE_NAME="${SERVICE_NAME:-voice-agentic-ai}"
REPOSITORY="${REPOSITORY:-${SERVICE_NAME}}"
IMAGE_NAME="${IMAGE_NAME:-${SERVICE_NAME}}"
PROJECT_ID="${PROJECT_ID:-${GOOGLE_CLOUD_PROJECT:-}}"
RUNTIME_SERVICE_ACCOUNT="${RUNTIME_SERVICE_ACCOUNT:-}"
DEFAULT_TAG="$(date +%Y%m%d-%H%M%S)"
TAG="${1:-${IMAGE_TAG:-${DEFAULT_TAG}}}"

ENV_VARS=(
  "GOOGLE_CLOUD_LOCATION=${REGION}"
  "CORS_ORIGINS=${CORS_ORIGINS:-*}"
  "SILENCE_TIMEOUT_SECONDS=${SILENCE_TIMEOUT_SECONDS:-1.5}"
  "MAX_RECORDING_SECONDS=${MAX_RECORDING_SECONDS:-900}"
  "QUESTION_BANK_PATH=${QUESTION_BANK_PATH:-data/headache_questions-ForVoicePrototyping.xlsx}"
)

if [[ -n "${RECAPTCHA_SITE_KEY:-}" ]]; then
  ENV_VARS+=(
    "RECAPTCHA_SITE_KEY=${RECAPTCHA_SITE_KEY}"
  )
fi

if [[ -n "${RECAPTCHA_EXPECTED_ACTION:-}" ]]; then
  ENV_VARS+=("RECAPTCHA_EXPECTED_ACTION=${RECAPTCHA_EXPECTED_ACTION}")
fi

if [[ -n "${RECAPTCHA_MIN_SCORE:-}" ]]; then
  ENV_VARS+=("RECAPTCHA_MIN_SCORE=${RECAPTCHA_MIN_SCORE}")
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

echo "=== Voice Agentic AI deploy ==="

echo "[1/9] Checking required CLIs..."
command -v gcloud >/dev/null 2>&1 || {
  echo "Error: gcloud is not installed or not on PATH." >&2
  exit 1
}
command -v docker >/dev/null 2>&1 || {
  echo "Error: docker is not installed or not on PATH." >&2
  exit 1
}

if [[ -z "${PROJECT_ID}" ]]; then
  PROJECT_ID="$(gcloud config get-value project 2>/dev/null || true)"
fi

if [[ -z "${PROJECT_ID}" || "${PROJECT_ID}" == "(unset)" ]]; then
  echo "Error: PROJECT_ID is not set and no active gcloud project was found." >&2
  echo "Set PROJECT_ID or run: gcloud config set project YOUR_PROJECT_ID" >&2
  exit 1
fi

ENV_VARS=("GOOGLE_CLOUD_PROJECT=${PROJECT_ID}" "${ENV_VARS[@]}")
ENV_VARS_CSV="$(IFS=,; echo "${ENV_VARS[*]}")"

if [[ -z "${RUNTIME_SERVICE_ACCOUNT}" ]]; then
  RUNTIME_SERVICE_ACCOUNT="voice-agentic-ai-runner@${PROJECT_ID}.iam.gserviceaccount.com"
fi

if ! gcloud iam service-accounts describe "${RUNTIME_SERVICE_ACCOUNT}" \
  --project "${PROJECT_ID}" >/dev/null 2>&1; then
  echo "Error: runtime service account '${RUNTIME_SERVICE_ACCOUNT}' was not found." >&2
  echo "Create it and grant roles/aiplatform.user, roles/speech.client, and roles/recaptchaenterprise.agent." >&2
  exit 1
fi

IMAGE_URL="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/${IMAGE_NAME}:${TAG}"

echo "Project:      ${PROJECT_ID}"
echo "Region:       ${REGION}"
echo "Service:      ${SERVICE_NAME}"
echo "Repository:   ${REPOSITORY}"
echo "Image:        ${IMAGE_URL}"
echo "Runtime SA:   ${RUNTIME_SERVICE_ACCOUNT}"

echo

echo "[2/9] Setting gcloud project..."
gcloud config set project "${PROJECT_ID}" >/dev/null

echo "[3/9] Listing Cloud Run services in ${REGION} (verification helper)..."
gcloud run services list --region="${REGION}" --project="${PROJECT_ID}"

echo "[4/9] Checking whether Cloud Run service exists..."
if gcloud run services describe "${SERVICE_NAME}" --region="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "Cloud Run service '${SERVICE_NAME}' already exists. A new revision will be deployed."
else
  echo "Cloud Run service '${SERVICE_NAME}' does not exist yet. It will be created."
fi

echo "[5/9] Ensuring Artifact Registry repository exists..."
if gcloud artifacts repositories describe "${REPOSITORY}" \
  --location="${REGION}" \
  --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "Artifact Registry repository '${REPOSITORY}' already exists."
else
  echo "Creating Artifact Registry repository '${REPOSITORY}'..."
  gcloud artifacts repositories create "${REPOSITORY}" \
    --repository-format=docker \
    --location="${REGION}" \
    --description="Docker images for ${SERVICE_NAME} Cloud Run deployments" \
    --project="${PROJECT_ID}"
fi

echo "[6/9] Configuring Docker auth for Artifact Registry..."
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

echo "[7/9] Building Docker image locally..."
docker build --platform linux/amd64 -t "${IMAGE_URL}" .

echo "[8/9] Pushing image to Artifact Registry..."
docker push "${IMAGE_URL}"

echo "[9/9] Deploying Cloud Run service '${SERVICE_NAME}'..."
DEPLOY_ARGS=(
  run deploy "${SERVICE_NAME}"
  --image "${IMAGE_URL}"
  --region "${REGION}"
  --platform managed
  --allow-unauthenticated
  --service-account "${RUNTIME_SERVICE_ACCOUNT}"
  --set-env-vars "${ENV_VARS_CSV}"
  --project "${PROJECT_ID}"
)

gcloud "${DEPLOY_ARGS[@]}"

SERVICE_URL="$(gcloud run services describe "${SERVICE_NAME}" --region="${REGION}" --project="${PROJECT_ID}" --format='value(status.url)')"

echo

echo "Deploy complete."
echo "Service URL: ${SERVICE_URL}"
echo "New image:   ${IMAGE_URL}"
echo "If the URL above matches your existing endpoint, the same browser link is now serving the new revision."

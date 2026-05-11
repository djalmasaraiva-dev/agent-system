#!/usr/bin/env bash
# Deploy the agent system to Cloud Run.
#
# Prereqs:
#   - gcloud CLI authenticated against the target project.
#   - Artifact Registry repo `${SERVICE}` exists in ${LOCATION}.
#   - The runtime service account has these roles in the project:
#       roles/aiplatform.user
#       roles/bigquery.jobUser
#       roles/bigquery.dataViewer  (or finer-grained on the dataset)
#       roles/logging.logWriter
#       roles/cloudtrace.agent
#   - Enable IAP for Cloud Run via an external HTTPS LB +
#     `gcloud iap web add-iam-policy-binding ...` after first deploy.
#
# Usage:
#   PROJECT_ID=acme-financials SERVICE=agent-system bash deployment/cloudrun_deploy.sh
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-acme-financials}"
LOCATION="${LOCATION:-us-central1}"
SERVICE="${SERVICE:-agent-system}"
RUNTIME_SA="${RUNTIME_SA:-${SERVICE}-runtime@${PROJECT_ID}.iam.gserviceaccount.com}"
IMAGE="${IMAGE:-${LOCATION}-docker.pkg.dev/${PROJECT_ID}/${SERVICE}/${SERVICE}:$(git rev-parse --short HEAD 2>/dev/null || date +%s)}"

# Models — override at the call site if you need to pin Gemini 2.5 stable.
COORDINATOR_MODEL="${COORDINATOR_MODEL:-gemini-3.1-pro-preview}"
RESEARCH_MODEL="${RESEARCH_MODEL:-gemini-3.1-pro-preview}"
DATA_MODEL="${DATA_MODEL:-gemini-3-flash-preview}"
REPORTER_MODEL="${REPORTER_MODEL:-gemini-3-flash-preview}"

# Identity envelope metadata
AGENT_NAME="${AGENT_NAME:-coordinator}"
AGENT_VERSION="${AGENT_VERSION:-0.1.0}"
AGENT_OWNER_EMAIL="${AGENT_OWNER_EMAIL:?owner email is required}"
AGENT_FALLBACK_OWNER_EMAIL="${AGENT_FALLBACK_OWNER_EMAIL:?fallback owner is required}"
AGENT_BUSINESS_UNIT="${AGENT_BUSINESS_UNIT:-Risk & Analytics}"
AGENT_CLASSIFICATION="${AGENT_CLASSIFICATION:-high-risk-data-access}"

# IAP audience format: /projects/PROJECT_NUMBER/global/backendServices/SERVICE_ID
IAP_EXPECTED_AUDIENCE="${IAP_EXPECTED_AUDIENCE:-}"
IAP_REQUIRED="${IAP_REQUIRED:-true}"

# BigQuery
BIGQUERY_DATASET="${BIGQUERY_DATASET:-analytics}"
BIGQUERY_LOCATION="${BIGQUERY_LOCATION:-US}"
BIGQUERY_MAX_BYTES_BILLED="${BIGQUERY_MAX_BYTES_BILLED:-1073741824}"

echo "==> Project: ${PROJECT_ID}    Location: ${LOCATION}    Service: ${SERVICE}"
echo "==> Image:   ${IMAGE}"
echo "==> Runtime SA: ${RUNTIME_SA}"

# 1. Build & push image with Cloud Build (no local Docker required).
echo "==> Building image with Cloud Build"
gcloud builds submit \
  --project="${PROJECT_ID}" \
  --region="${LOCATION}" \
  --tag "${IMAGE}" \
  .

# 2. Deploy to Cloud Run with the runtime service account and ingress restricted
#    to internal-and-cloud-load-balancing so IAP can sit in front.
echo "==> Deploying Cloud Run service"
gcloud run deploy "${SERVICE}" \
  --project="${PROJECT_ID}" \
  --region="${LOCATION}" \
  --image="${IMAGE}" \
  --service-account="${RUNTIME_SA}" \
  --ingress="internal-and-cloud-load-balancing" \
  --no-allow-unauthenticated \
  --cpu=2 \
  --memory=2Gi \
  --concurrency=20 \
  --timeout=600 \
  --min-instances=0 \
  --max-instances=10 \
  --port=8080 \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT_ID}" \
  --set-env-vars="GOOGLE_CLOUD_LOCATION=${LOCATION}" \
  --set-env-vars="GOOGLE_GENAI_USE_VERTEXAI=true" \
  --set-env-vars="COORDINATOR_MODEL=${COORDINATOR_MODEL}" \
  --set-env-vars="RESEARCH_MODEL=${RESEARCH_MODEL}" \
  --set-env-vars="DATA_MODEL=${DATA_MODEL}" \
  --set-env-vars="REPORTER_MODEL=${REPORTER_MODEL}" \
  --set-env-vars="AGENT_NAME=${AGENT_NAME}" \
  --set-env-vars="AGENT_VERSION=${AGENT_VERSION}" \
  --set-env-vars="AGENT_OWNER_EMAIL=${AGENT_OWNER_EMAIL}" \
  --set-env-vars="AGENT_FALLBACK_OWNER_EMAIL=${AGENT_FALLBACK_OWNER_EMAIL}" \
  --set-env-vars="^@^AGENT_BUSINESS_UNIT=${AGENT_BUSINESS_UNIT}" \
  --set-env-vars="AGENT_CLASSIFICATION=${AGENT_CLASSIFICATION}" \
  --set-env-vars="BIGQUERY_DATASET=${BIGQUERY_DATASET}" \
  --set-env-vars="BIGQUERY_LOCATION=${BIGQUERY_LOCATION}" \
  --set-env-vars="BIGQUERY_MAX_BYTES_BILLED=${BIGQUERY_MAX_BYTES_BILLED}" \
  --set-env-vars="IAP_EXPECTED_AUDIENCE=${IAP_EXPECTED_AUDIENCE}" \
  --set-env-vars="IAP_REQUIRED=${IAP_REQUIRED}" \
  --set-env-vars="ENABLE_CLOUD_TRACE=true" \
  --set-env-vars="SERVICE_NAME=${SERVICE}"

cat <<EOF

✅ Deploy complete.

Next steps:
  1. Configure an external HTTPS load balancer with this Cloud Run service as a
     serverless NEG backend.
  2. Enable IAP on that backend service:
       gcloud iap web enable --resource-type=backend-services --service=BACKEND_SVC
  3. Compute the audience and set IAP_EXPECTED_AUDIENCE on the service:
       /projects/PROJECT_NUMBER/global/backendServices/BACKEND_SVC_ID
  4. Bind viewers / invokers via:
       gcloud iap web add-iam-policy-binding \\
         --resource-type=backend-services --service=BACKEND_SVC \\
         --member='user:analyst@example.com' --role='roles/iap.httpsResourceAccessor'
  5. Verify:
       curl -H "Authorization: Bearer \$(gcloud auth print-identity-token)" \\
         https://YOUR_LB_HOST/.well-known/agent-identity
EOF

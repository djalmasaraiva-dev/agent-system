#!/usr/bin/env bash
# One-shot IAM setup for the agent-system runtime service account.
# Idempotent — safe to re-run.
#
# Usage:
#   PROJECT_ID=acme-financials SERVICE=agent-system bash deployment/setup_iam.sh
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-acme-financials}"
LOCATION="${LOCATION:-us-central1}"
SERVICE="${SERVICE:-agent-system}"
SA_NAME="${SERVICE}-runtime"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
REPO_NAME="${REPO_NAME:-${SERVICE}}"

echo "==> Enabling required APIs"
gcloud services enable \
  --project="${PROJECT_ID}" \
  aiplatform.googleapis.com \
  bigquery.googleapis.com \
  run.googleapis.com \
  iap.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  cloudtrace.googleapis.com \
  logging.googleapis.com

echo "==> Creating Artifact Registry repo (if missing)"
gcloud artifacts repositories describe "${REPO_NAME}" \
  --project="${PROJECT_ID}" --location="${LOCATION}" >/dev/null 2>&1 || \
gcloud artifacts repositories create "${REPO_NAME}" \
  --project="${PROJECT_ID}" --location="${LOCATION}" \
  --repository-format=docker \
  --description="Agent-system container images"

echo "==> Creating runtime service account (if missing)"
gcloud iam service-accounts describe "${SA_EMAIL}" \
  --project="${PROJECT_ID}" >/dev/null 2>&1 || \
gcloud iam service-accounts create "${SA_NAME}" \
  --project="${PROJECT_ID}" \
  --display-name="Agent system runtime"

echo "==> Granting minimum roles on project"
for role in \
  roles/aiplatform.user \
  roles/bigquery.jobUser \
  roles/bigquery.dataViewer \
  roles/logging.logWriter \
  roles/cloudtrace.agent \
  roles/monitoring.metricWriter
do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="${role}" \
    --condition=None \
    --quiet >/dev/null
  echo "    ✓ ${role}"
done

cat <<EOF

✅ IAM setup complete.

Runtime SA: ${SA_EMAIL}

Recommendation: scope BigQuery dataViewer to the dataset only:
  bq update --source <(printf '{"access":[{"role":"READER","userByEmail":"%s"}]}' "${SA_EMAIL}") \\
            ${PROJECT_ID}:analytics
EOF

# agent-system

Production-grade reference implementation accompanying the Medium article
**"When Agents Call Agents: Governing Identity in Multi-Agent ADK Systems on Google Cloud"**.

A multi-agent system built with Google's **Agent Development Kit (ADK)** that
demonstrates the runtime side of cross-platform agent identity governance:

- Four agents wired with the `LlmAgent + AgentTool` pattern — `coordinator`
  delegates to `research_agent`, `data_agent`, and `reporter_agent`.
- Real BigQuery tool with **dry-run cost guard**, SELECT-only allow-list, and
  parameterized queries.
- `/.well-known/agent-identity` **identity bridge** that exposes a portable
  envelope an upstream IGA (SailPoint, Saviynt, Okta, BeyondTrust, …) can
  ingest.
- **IAP JWT verification** (ES256, public-key rotation, fail-closed) on every
  governance route.
- **Governance callbacks** that emit structured JSON audit log entries through
  `before_*_callback` / `after_*_callback` hooks — Cloud Logging-ready by
  construction.
- **Loop guards** (per-agent tool-call cap, repeat-call detection) so a
  runaway LLM cannot burn through quota or escalate beyond its scope.
- **62 unit tests**, `ruff` + `mypy --strict` clean.

The architecture maps directly to the article's Layer 1 / Layer 2 framing:
runtime identity, authorization, runtime protection, and audit evidence sit
in this codebase; lifecycle ownership (HR-anchored certification, partner IGA)
sits above it.

## Layout (Agent Starter Pack convention)

```
agent-system/
├── app/
│   ├── agent.py                # root coordinator
│   ├── agent_engine_app.py     # Vertex AI Agent Engine wrapper
│   ├── server.py               # FastAPI: /healthz, /readyz, /invoke, /.well-known/*
│   ├── config.py               # Pydantic Settings
│   ├── agents/
│   │   ├── research.py         # google_search
│   │   ├── data.py             # BigQuery (cost-guarded)
│   │   ├── reporter.py         # synthesis only
│   │   └── prompts.py          # GLOBAL_INSTRUCTION + per-agent prompts
│   ├── tools/
│   │   └── bigquery.py         # dry-run + max_bytes_billed + row cap
│   ├── identity/
│   │   ├── models.py           # AgentIdentity Pydantic envelope
│   │   ├── registry.py         # per-agent topology
│   │   ├── iap_auth.py         # X-Goog-IAP-JWT-Assertion verifier
│   │   └── router.py           # /.well-known/agent-identity[/{name}]
│   ├── shared_libraries/
│   │   ├── callbacks.py        # before/after_agent/model/tool
│   │   └── safety.py           # GenerateContentConfig + safety_settings
│   └── utils/
│       ├── logging.py          # structlog with stdlib JSON fallback
│       └── tracing.py          # OpenTelemetry → Cloud Trace
├── deployment/
│   ├── setup_iam.sh            # APIs, runtime SA, Artifact Registry
│   ├── cloudrun_deploy.sh      # Cloud Build + Cloud Run with IAP guidance
│   └── agent_engine_deploy.py  # Vertex AI Agent Engine
├── tests/
│   ├── unit/                   # 62 tests, runs offline against mocks
│   └── load_test/              # Locust
├── Dockerfile
├── Makefile
├── dev.sh                      # ./dev.sh web | server | test | lint
├── prepare_screenshots.sh
├── pyproject.toml
└── uv.lock
```

## Quick start

```bash
# 1. Install deps (uv handles Python 3.11 + venv)
make install   # equivalent: uv sync --all-extras

# 2. Configure
cp .env.example .env
# edit .env to point at your GCP project

# 3. Authenticate
gcloud auth application-default login
gcloud config set project YOUR_PROJECT

# 4. Provision IAM (one-shot, idempotent)
PROJECT_ID=YOUR_PROJECT bash deployment/setup_iam.sh

# 5. Run locally
./dev.sh web         # ADK web playground at http://localhost:8000
./dev.sh server      # FastAPI on :8081 with /.well-known/agent-identity
./dev.sh test        # pytest (62 tests)
./dev.sh lint        # ruff + mypy
```

## Models

Pinned to Gemini 3.1 — the system explicitly targets the latest Gemini family
available on Vertex AI and does not provide a 2.x fallback path.

- `coordinator` / `research_agent` → `gemini-3.1-pro-preview`
- `data_agent` / `reporter_agent`   → `gemini-3-flash-preview`

> Vertex AI Gemini 3 preview models currently require `GOOGLE_CLOUD_LOCATION=global`.
> Enable the preview tier in Model Garden if you see `404 Publisher Model not found`.

## What the agents actually do

Send any of these to the coordinator (via `./dev.sh web` or `POST /invoke`):

| Question | Expected path |
|---|---|
| _"Summarize what Google announced about Agent Identity at Cloud Next 2026."_ | `research_agent` only |
| _"List the schema of `usa_names` and show 10 records."_ | `data_agent` only |
| _"Compare our analytics with BIS 2025 benchmarks."_ | `research_agent` + `data_agent` in parallel, then `reporter_agent` |
| _"Who can ultimately cause a write to the customer table?"_ | Honest refusal — agent surfaces Layer 1 boundary in **Caveats** |

## Identity bridge

Once the FastAPI server is running:

```bash
curl -s http://localhost:8081/.well-known/agent-identity | jq
curl -s http://localhost:8081/.well-known/agents | jq
curl -s http://localhost:8081/.well-known/agent-identity/data_agent | jq
```

Returns the portable envelope an IGA platform can ingest — see
`app/identity/models.py:AgentIdentity` for the exact schema.

## Deploy

```bash
make deploy-cloudrun       # Cloud Build + Cloud Run + IAP setup guidance
make deploy-agent-engine   # Vertex AI Agent Engine (managed runtime)
```

## License

Apache 2.0. See [LICENSE](LICENSE).

## Citation

If you reference this implementation in a paper or post, please link the
companion article (forthcoming on the Google Cloud Medium publication, 2026).

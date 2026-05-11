<div align="center">

# agent-system

**Multi-agent ADK reference implementation with a cross-platform identity bridge**

A production-shaped reference implementation built with Google's
[Agent Development Kit (ADK)](https://github.com/google/adk-python) and
[Vertex AI Agent Engine](https://cloud.google.com/vertex-ai/docs/agent-engine).
Companion code to the Medium article
**["When Agents Call Agents: Governing Identity in Multi-Agent ADK Systems on Google Cloud"](https://medium.com/google-cloud)**.

[![Python](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/)
[![ADK](https://img.shields.io/badge/google--adk-1.33-4285F4.svg)](https://github.com/google/adk-python)
[![Vertex AI](https://img.shields.io/badge/Vertex_AI-Agent_Engine-34A853.svg)](https://cloud.google.com/vertex-ai/docs/agent-engine)
[![License](https://img.shields.io/badge/license-Apache_2.0-EA4335.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-62%20passing-success.svg)](tests/)

</div>

---

## Why this exists

Most agent samples show a single LLM with a tool list. Production multi-agent
systems running in regulated environments have a different shape: many agents,
crossing many platforms, each needing **a unique attested identity, an enforced
scope of action, and an audit trail an external auditor can use**.

This repo materializes that shape in code, against a real GCP project,
end-to-end:

- **4 LlmAgents** (`coordinator`, `research_agent`, `data_agent`,
  `reporter_agent`) wired via `AgentTool` delegation with `output_key` session
  state.
- **Cost-guarded BigQuery tool** — dry-run + `maximum_bytes_billed` enforced
  before any byte is scanned.
- **`/.well-known/agent-identity` bridge** — exposes a portable
  `AgentIdentity` envelope (SPIFFE ID, classification, `data_scopes`, owner,
  fallback owner) that any IGA platform can ingest.
- **IAP JWT verification** on every governance route (ES256 with public-key
  rotation, fail-closed when `IAP_REQUIRED=true`).
- **Governance callbacks** that emit structured JSON audit log entries through
  `before_*_callback` / `after_*_callback` hooks — Cloud Logging-ready by
  construction, PII-safe by design (logs argument *keys*, not values).
- **Loop guards** — per-agent tool-call cap and repeat-call detection so a
  runaway LLM cannot burn through quota or escalate beyond its scope.

The architecture maps directly to the article's Layer 1 / Layer 2 framing:
runtime identity, authorization, runtime protection, and audit evidence live
in this codebase; lifecycle ownership (HR-anchored certification, partner IGA)
sits above it.

---

## Architecture

```text
                       ┌─────────────────────────┐
HTTP /invoke ─▶ IAP ─▶ │      coordinator        │  gemini-3.1-pro-preview
                       │  (global_instruction)   │
                       └────┬────────┬────────┬──┘
                            │        │        │
              AgentTool ────┘        │        └──── AgentTool
                            │        │
                            ▼        ▼
               ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
               │ research_agent  │  │   data_agent    │  │ reporter_agent  │
               │   gemini-3.1    │  │   gemini-3      │  │   gemini-3      │
               │  google_search  │  │  flash-preview  │  │  flash-preview  │
               └─────────────────┘  └────────┬────────┘  └─────────────────┘
                                             │
                                             ▼
                                ┌────────────────────────┐
                                │  BigQuery cost guard   │
                                │  list_tables           │
                                │  describe_table        │
                                │  bigquery_query        │
                                └────────────────────────┘

Every tool call →  before_tool_callback (allow-list + loop guard)
                →  after_tool_callback (audit log + cost telemetry)
                →  Cloud Logging (structured JSON, joinable by invocation_id)
```

The companion `/.well-known/agent-identity` endpoint exposes the same
topology as a JSON envelope for upstream IGA consumption.

---

## Repository layout

Follows the [Google Agent Starter Pack](https://github.com/GoogleCloudPlatform/agent-starter-pack)
convention so the code is immediately recognizable to anyone familiar with
Google's official agent templates.

```
agent-system/
├── app/
│   ├── agent.py                # root coordinator
│   ├── agent_engine_app.py     # Vertex AI Agent Engine wrapper
│   ├── server.py               # FastAPI: /healthz, /readyz, /invoke, /.well-known/*
│   ├── config.py               # Pydantic Settings
│   ├── agents/
│   │   ├── research.py         # google_search builtin
│   │   ├── data.py             # cost-guarded BigQuery
│   │   ├── reporter.py         # markdown synthesis
│   │   └── prompts.py          # GLOBAL_INSTRUCTION + per-agent prompts
│   ├── tools/bigquery.py       # dry-run + max_bytes_billed + row cap
│   ├── identity/
│   │   ├── models.py           # AgentIdentity Pydantic envelope
│   │   ├── registry.py         # per-agent topology + SPIFFE id
│   │   ├── iap_auth.py         # X-Goog-IAP-JWT-Assertion verifier
│   │   └── router.py           # /.well-known/agent-identity[/{name}]
│   ├── shared_libraries/
│   │   ├── callbacks.py        # governance hooks
│   │   └── safety.py           # GenerateContentConfig + safety_settings
│   └── utils/{logging,tracing}.py
├── deployment/
│   ├── setup_iam.sh            # APIs + runtime SA + Artifact Registry
│   ├── cloudrun_deploy.sh      # Cloud Build + Cloud Run + IAP setup guidance
│   └── agent_engine_deploy.py  # Vertex AI Agent Engine
├── tests/
│   ├── unit/                   # 62 tests; runs offline against mocks
│   └── load_test/load_test.py  # Locust
├── Dockerfile · Makefile · dev.sh · pyproject.toml · uv.lock
└── README.md · LICENSE
```

---

## Quick start

### Prerequisites

- Python 3.11 (managed by `uv` — `curl -LsSf https://astral.sh/uv/install.sh | sh`)
- A Google Cloud project with Vertex AI access and BigQuery enabled
- `gcloud` CLI authenticated

### Five-minute setup

```bash
git clone https://github.com/djalmasaraiva-dev/agent-system.git
cd agent-system

# 1. Install dependencies into an isolated venv
make install                                     # uv sync --all-extras

# 2. Configure
cp .env.example .env
# Edit .env: set GOOGLE_CLOUD_PROJECT and AGENT_OWNER_EMAIL

# 3. Authenticate ADC + select project
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID

# 4. Provision IAM (idempotent)
PROJECT_ID=YOUR_PROJECT_ID bash deployment/setup_iam.sh

# 5. Run
./dev.sh test                                    # 62 unit tests
./dev.sh web                                     # http://localhost:8000
```

### One-command development helpers

```bash
./dev.sh web                  # ADK web playground
./dev.sh server               # FastAPI on :8081 (production-shaped surface)
./dev.sh test                 # pytest
./dev.sh lint                 # ruff + ruff format + mypy
./dev.sh run app              # interactive CLI
```

---

## Models

Pinned to **Gemini 3.1** — the system explicitly targets the latest Gemini
family available on Vertex AI.

| Role | Model |
|---|---|
| `coordinator` (orchestration) | `gemini-3.1-pro-preview` |
| `research_agent` (Google Search) | `gemini-3.1-pro-preview` |
| `data_agent` (BigQuery analytics) | `gemini-3-flash-preview` |
| `reporter_agent` (synthesis) | `gemini-3-flash-preview` |

> Gemini 3 preview models on Vertex AI currently require
> `GOOGLE_CLOUD_LOCATION=global`. Enable the preview tier in
> [Model Garden](https://console.cloud.google.com/vertex-ai/model-garden) if
> you see `404 Publisher Model not found`.

---

## What the agents actually do

Send any of these to the coordinator (via `./dev.sh web` or `POST /invoke`):

| Question | Path | Agents touched |
|---|---|---|
| _"Summarize what Google announced about Agent Identity at Cloud Next 2026."_ | public sources | `research_agent` + `reporter_agent` |
| _"List the schema of `usa_names` and show 10 records."_ | internal data | `data_agent` + `reporter_agent` |
| _"Compare our analytics with BIS 2025 benchmarks."_ | mixed | `research_agent` ∥ `data_agent` → `reporter_agent` |
| _"Who can ultimately cause a write to the customer table?"_ | **honest refusal** | agent surfaces Layer 1 boundary in **Caveats** |

The last question is the article's argument materialized: the agent
investigates within its declared `data_scopes`, reports what it can verify,
and explicitly names what cannot be answered without IAM + IGA — instead of
fabricating an answer.

---

## The identity bridge in action

With `./dev.sh server` running on `:8081`:

```bash
# The current service's agent envelope (single agent per Cloud Run instance):
curl -s http://localhost:8081/.well-known/agent-identity | jq

# The full topology (4 agents) — what an IGA connector ingests:
curl -s http://localhost:8081/.well-known/agents | jq

# Specific agent by name:
curl -s http://localhost:8081/.well-known/agent-identity/data_agent | jq
```

Example response (data_agent):

```json
{
  "agent_id": "data_agent-0.1.0",
  "name": "data_agent",
  "version": "0.1.0",
  "platform": "gemini-enterprise",
  "spiffe_id": "spiffe://agents.global.org-acme-financials.system.id.goog/resources/aiplatform/projects/acme-financials/locations/global/reasoningEngines/data_agent",
  "owner_email": "risk-analytics-lead@example.com",
  "fallback_owner_email": "ai-platform-ops@example.com",
  "business_unit": "Risk & Analytics",
  "model": "gemini-3-flash-preview",
  "tools": ["bigquery_query", "list_tables", "describe_table"],
  "inbound_callers": ["coordinator"],
  "outbound_callees": [],
  "classification": "high-risk-data-access",
  "data_scopes": ["bigquery:acme-financials.analytics.*"]
}
```

The exact Pydantic schema lives in
[`app/identity/models.py`](app/identity/models.py).

---

## Governance in code

Every tool call passes through the callback chain in
[`app/shared_libraries/callbacks.py`](app/shared_libraries/callbacks.py):

| Callback | What it does |
|---|---|
| `before_agent_callback` | Stamps invocation with timing + caller identity into session state |
| `before_model_callback` | Per-session RPM rate limit (default 30/min) |
| `before_tool_callback` | Allow-list check, total-calls cap (15/agent), repeat-call detection |
| `after_tool_callback` | Emits `tool.call.ok` with `bytes_billed`, `row_count`, `code` |
| `after_model_callback` | Logs token usage for per-agent cost accounting |

The resulting log is Cloud Logging-ready by construction, **PII-safe by
default** (argument *keys* are logged, not values), and joinable on
`invocation_id` to reconstruct any agent call graph in a single SQL query.

---

## Deployment

Two managed paths, both scripted:

### Cloud Run + IAP

```bash
make deploy-cloudrun
```

Builds the image with Cloud Build, deploys with `--no-allow-unauthenticated`
and `--ingress=internal-and-cloud-load-balancing`, then prints exact
instructions to put an external HTTPS LB + IAP in front and bind viewers.

### Vertex AI Agent Engine

```bash
make deploy-agent-engine
```

Uploads via `vertexai.agent_engines.create()` with the
[`AdkApp`](app/agent_engine_app.py) wrapper. Returns a managed reasoning
engine with auto-provisioned Agent Identity, native session persistence, and
built-in observability.

---

## Testing and quality

```bash
./dev.sh test                # 62 unit tests, ~1s
./dev.sh lint                # ruff check + ruff format --check + mypy --strict
make test-cov                # 76% line coverage (lower in tracing.py / server.py
                             #                    by design — best-effort paths)
```

The unit tests run **fully offline** — BigQuery and Vertex AI clients are
mocked. Real GCP credentials are only needed for end-to-end deployment.

Test breakdown:

| Module | Coverage |
|---|---|
| `tests/unit/test_identity_models.py` | AgentIdentity schema, SPIFFE format |
| `tests/unit/test_iap_auth.py` | ES256, audience, expiry, issuer, key rotation |
| `tests/unit/test_identity_endpoint.py` | `/.well-known/agent-identity` happy path + fail-closed |
| `tests/unit/test_bigquery_tool.py` | Cost guard, SELECT-only allow-list, parameter binding |
| `tests/unit/test_callbacks.py` | Allow-list, audit log, loop guards, no-PII guarantee |
| `tests/unit/test_agents_smoke.py` | Wiring, `output_key`, `global_instruction` |
| `tests/unit/test_agent_engine_wrapper.py` | Reasoning Engine pickle stability |

---

## Companion article

The architectural reasoning, the customer story (a research agent that ran
for 47 days with hallucinated citations before anyone noticed), and the
Layer 1 / Layer 2 framing live in the Medium piece:

**["When Agents Call Agents: Governing Identity in Multi-Agent ADK Systems on Google Cloud"](https://medium.com/google-cloud)**
by Djalma Junior (GFT Technologies) and Marcelo Amaral (Google Cloud).

---

## Roadmap

- [ ] Workflow graph orchestration via ADK 2.0 `Workflow(BaseNode)` once GA
- [ ] HITL approval node for `data_agent` queries above a cost threshold
- [ ] `BigQueryAgentAnalyticsPlugin` integration for cache-metadata logging
- [ ] Terraform module for one-shot project provisioning

---

## License

[Apache 2.0](LICENSE). Free to use, fork, and adapt — attribution appreciated
but not required.

---

## Citation

If you reference this implementation in a paper, talk, or post:

```text
Junior, D. and Amaral, M. (2026).
agent-system: a multi-agent ADK reference implementation with cross-platform
identity bridge. https://github.com/djalmasaraiva-dev/agent-system
```

"""Per-process registry of `AgentIdentity` envelopes.

In production each Cloud Run service hosts a single agent and exposes its own
`/.well-known/agent-identity`. The registry maps `agent_name -> AgentIdentity`
so the same image can be reused across multiple services with the agent
selected at boot via env (`AGENT_NAME`).

The registry is also the single source of truth the IGA can pull from when it
walks our deployment via the cross-platform connector — anything in production
without an entry here is "discovery by absence" and flagged for governance.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.config import get_settings
from app.identity.models import AgentIdentity

_PLATFORM = "gemini-enterprise"


def _spiffe_id(agent_name: str) -> str:
    """Construct a SPIFFE ID matching the Gemini Enterprise Agent Platform pattern.

    spiffe://agents.global.org-{ORG_ID}.system.id.goog/resources/aiplatform/projects/{PROJECT_NUMBER}/locations/{LOCATION}/reasoningEngines/{AGENT_NAME}

    For local/dev we use the project ID as a stand-in for ORG_ID/PROJECT_NUMBER;
    in production the runtime injects the real values via Workload Identity.
    """
    s = get_settings()
    return (
        f"spiffe://agents.global.org-{s.google_cloud_project}.system.id.goog/"
        f"resources/aiplatform/projects/{s.google_cloud_project}/"
        f"locations/{s.google_cloud_location}/reasoningEngines/{agent_name}"
    )


def _build_default_registry() -> dict[str, AgentIdentity]:
    """Compose the registry from settings + the static topology of this app."""
    s = get_settings()
    now = datetime.now(UTC)

    def make(
        *,
        agent_name: str,
        model: str,
        tools: list[str],
        inbound: list[str],
        outbound: list[str],
        classification: str,
        data_scopes: list[str],
        context: str,
    ) -> AgentIdentity:
        return AgentIdentity(
            agent_id=f"{agent_name}-{s.agent_version}",
            name=agent_name,
            version=s.agent_version,
            platform=_PLATFORM,
            spiffe_id=_spiffe_id(agent_name),
            owner_email=s.agent_owner_email,
            fallback_owner_email=s.agent_fallback_owner_email,
            business_unit=s.agent_business_unit,
            created_at=now,
            last_reviewed_at=None,
            model=model,
            tools=tools,
            inbound_callers=inbound,
            outbound_callees=outbound,
            classification=classification,
            data_scopes=data_scopes,
            business_context=context or s.agent_business_context,
            decommission_after=s.agent_decommission_after,
        )

    coordinator = make(
        agent_name="coordinator",
        model=s.coordinator_model,
        tools=["agent_tool:research_agent", "agent_tool:data_agent", "agent_tool:reporter_agent"],
        inbound=["analyst-ui", "iap-frontend"],
        outbound=["research_agent", "data_agent", "reporter_agent"],
        classification=s.agent_classification,
        data_scopes=[],
        context=(
            "Orchestrates the research+data+reporter workflow for analyst questions. "
            "Owner accountable via the IGA layer."
        ),
    )
    research = make(
        agent_name="research_agent",
        model=s.research_model,
        tools=["google_search"],
        inbound=["coordinator"],
        outbound=[],
        classification="low-risk",
        data_scopes=["public:web"],
        context="Public-source research via Google Search.",
    )
    data = make(
        agent_name="data_agent",
        model=s.data_model,
        tools=["bigquery_query", "list_tables", "describe_table"],
        inbound=["coordinator"],
        outbound=[],
        classification="high-risk-data-access",
        data_scopes=[
            f"bigquery:{s.google_cloud_project}.{s.bigquery_dataset}.*",
        ],
        context=(
            "Runs read-only BigQuery analyses against the analytics dataset. "
            "Bytes-billed cost guard and SELECT-only allow-list enforced in code."
        ),
    )
    reporter = make(
        agent_name="reporter_agent",
        model=s.reporter_model,
        tools=[],
        inbound=["coordinator"],
        outbound=[],
        classification="low-risk",
        data_scopes=[],
        context="Composes the final analyst-facing brief from research and data outputs.",
    )

    return {
        "coordinator": coordinator,
        "research_agent": research,
        "data_agent": data,
        "reporter_agent": reporter,
    }


_REGISTRY: dict[str, AgentIdentity] | None = None


def reset_registry() -> None:
    """Test hook: clear the cached registry so settings overrides take effect."""
    global _REGISTRY
    _REGISTRY = None


def get_registry() -> dict[str, AgentIdentity]:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_default_registry()
    return _REGISTRY


def get_current_identity() -> AgentIdentity:
    """Return the identity for the agent this service is configured to host.

    Falls back to the coordinator when AGENT_NAME doesn't match any known agent.
    """
    s = get_settings()
    reg = get_registry()
    return reg.get(s.agent_name, reg["coordinator"])


def list_identities() -> list[AgentIdentity]:
    return list(get_registry().values())

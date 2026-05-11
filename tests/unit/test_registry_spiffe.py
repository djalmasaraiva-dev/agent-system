"""Tests for the AgentIdentity registry — SPIFFE format and topology shape."""

from __future__ import annotations

import re

from app.identity.registry import get_registry, list_identities, reset_registry


def test_registry_has_expected_agents() -> None:
    reset_registry()
    reg = get_registry()
    assert set(reg.keys()) == {"coordinator", "research_agent", "data_agent", "reporter_agent"}


def test_spiffe_ids_match_gemini_enterprise_pattern() -> None:
    """Article spec:
    spiffe://agents.global.org-{ORG_ID}.system.id.goog/resources/aiplatform/projects/{PROJECT_NUMBER}/locations/{LOCATION}/reasoningEngines/{AGENT_NAME}
    """
    reset_registry()
    pattern = re.compile(
        r"^spiffe://agents\.global\.org-[\w-]+\.system\.id\.goog/"
        r"resources/aiplatform/projects/[\w-]+/locations/[\w-]+/"
        r"reasoningEngines/[\w-]+$"
    )
    for identity in list_identities():
        assert identity.spiffe_id is not None
        assert pattern.match(identity.spiffe_id), identity.spiffe_id
        # The trailing component must be the agent name itself.
        assert identity.spiffe_id.endswith(f"/reasoningEngines/{identity.name}")


def test_data_agent_scopes_include_bigquery_dataset() -> None:
    reset_registry()
    reg = get_registry()
    data = reg["data_agent"]
    assert data.classification == "high-risk-data-access"
    assert any(s.startswith("bigquery:") for s in data.data_scopes)


def test_research_agent_classification_is_low_risk() -> None:
    reset_registry()
    reg = get_registry()
    assert reg["research_agent"].classification == "low-risk"


def test_coordinator_outbound_lists_all_specialists() -> None:
    reset_registry()
    reg = get_registry()
    coord = reg["coordinator"]
    assert set(coord.outbound_callees) == {"research_agent", "data_agent", "reporter_agent"}
    assert "analyst-ui" in coord.inbound_callers


def test_owner_email_propagates_from_settings() -> None:
    """Settings → registry wiring must work end-to-end."""
    reset_registry()
    for identity in list_identities():
        assert identity.owner_email == "owner@example.com"
        assert identity.fallback_owner_email == "fallback@example.com"

"""Schema-level tests for the AgentIdentity envelope (article spec)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.identity.models import AgentIdentity


def _valid_payload() -> dict:
    return {
        "agent_id": "data-agent-prod-001",
        "name": "data_agent",
        "version": "2.4.1",
        "platform": "gemini-enterprise",
        "spiffe_id": (
            "spiffe://agents.global.org-123456789.system.id.goog/"
            "resources/aiplatform/projects/847291/"
            "locations/us-central1/reasoningEngines/data-agent-prod-001"
        ),
        "owner_email": "risk-analytics-lead@example.com",
        "fallback_owner_email": "ai-platform-ops@example.com",
        "business_unit": "Risk & Analytics",
        "created_at": datetime(2026, 3, 15, 14, 32, tzinfo=UTC),
        "last_reviewed_at": datetime(2026, 4, 28, tzinfo=UTC),
        "model": "gemini-3-pro",
        "tools": ["bigquery_query", "list_tables"],
        "inbound_callers": ["coordinator"],
        "outbound_callees": [],
        "classification": "high-risk-data-access",
        "data_scopes": ["bigquery:analytics.customer_metrics"],
        "business_context": "Provides aggregated risk metrics.",
        "decommission_after": datetime(2026, 9, 30, tzinfo=UTC),
    }


def test_valid_envelope_round_trips() -> None:
    payload = _valid_payload()
    identity = AgentIdentity.model_validate(payload)
    dumped = identity.model_dump()
    assert dumped["agent_id"] == "data-agent-prod-001"
    assert dumped["classification"] == "high-risk-data-access"
    assert dumped["spiffe_id"].endswith("/data-agent-prod-001")


def test_invalid_owner_email_rejected() -> None:
    payload = _valid_payload()
    payload["owner_email"] = "not-an-email"
    with pytest.raises(ValidationError):
        AgentIdentity.model_validate(payload)


def test_invalid_classification_rejected() -> None:
    payload = _valid_payload()
    payload["classification"] = "bogus-tier"
    with pytest.raises(ValidationError):
        AgentIdentity.model_validate(payload)


def test_optional_fields_default_to_none() -> None:
    payload = _valid_payload()
    payload.pop("last_reviewed_at")
    payload.pop("decommission_after")
    payload.pop("spiffe_id")
    identity = AgentIdentity.model_validate(payload)
    assert identity.last_reviewed_at is None
    assert identity.decommission_after is None
    assert identity.spiffe_id is None

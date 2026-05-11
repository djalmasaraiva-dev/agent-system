"""End-to-end test of the /.well-known/agent-identity endpoint.

We mount only the identity router (not the full FastAPI app) so we don't pull
in the ADK Runner / Vertex AI for what is purely a metadata test.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.identity.router import router as identity_router


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(identity_router)
    return TestClient(app)


def test_get_well_known_agent_identity_returns_envelope(client: TestClient) -> None:
    resp = client.get("/.well-known/agent-identity")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["name"] == "coordinator"
    assert data["platform"] == "gemini-enterprise"
    assert data["spiffe_id"].startswith("spiffe://agents.global.")
    assert data["owner_email"]
    assert data["fallback_owner_email"]
    assert "research_agent" in data["outbound_callees"]
    assert "data_agent" in data["outbound_callees"]
    assert "reporter_agent" in data["outbound_callees"]


def test_list_well_known_agents_returns_full_topology(client: TestClient) -> None:
    resp = client.get("/.well-known/agents")
    assert resp.status_code == 200
    payload = resp.json()
    names = {a["name"] for a in payload}
    assert names == {"coordinator", "research_agent", "data_agent", "reporter_agent"}


def test_get_identity_by_name_returns_data_agent(client: TestClient) -> None:
    resp = client.get("/.well-known/agent-identity/data_agent")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "data_agent"
    assert data["classification"] == "high-risk-data-access"
    assert any(s.startswith("bigquery:") for s in data["data_scopes"])


def test_get_identity_by_name_unknown_404(client: TestClient) -> None:
    resp = client.get("/.well-known/agent-identity/no_such_agent")
    assert resp.status_code == 404


def test_iap_required_without_audience_returns_500(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    """Misconfigured deployment fails closed."""
    from app import config

    monkeypatch.setenv("IAP_REQUIRED", "true")
    monkeypatch.setenv("IAP_EXPECTED_AUDIENCE", "")
    config.get_settings.cache_clear()
    try:
        resp = client.get("/.well-known/agent-identity")
        assert resp.status_code == 500
    finally:
        config.get_settings.cache_clear()

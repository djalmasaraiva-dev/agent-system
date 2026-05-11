"""Health endpoint smoke tests against the real FastAPI app.

We don't import `app.server` at module load — the import boots ADK / Vertex AI
which can fail on machines without ADC. These tests skip in that case.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def client():
    try:
        from fastapi.testclient import TestClient

        from app.server import app
    except Exception as exc:
        pytest.skip(f"server boot failed (likely missing ADC): {exc}")
    return TestClient(app)


def test_healthz(client) -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_readyz_reports_status(client) -> None:
    resp = client.get("/readyz")
    assert resp.status_code == 200
    body = resp.json()
    assert "status" in body
    assert "credentials" in body
    assert "agent" in body

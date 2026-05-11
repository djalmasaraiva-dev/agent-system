"""Tests for the BigQuery tool — client patched, no real GCP calls."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from app.tools import bigquery as bq


@pytest.fixture(autouse=True)
def _reset_client_cache() -> None:
    bq._client.cache_clear()
    yield
    bq._client.cache_clear()


def _stub_client(
    *,
    estimated_bytes: int = 1024,
    rows: list[dict[str, Any]] | None = None,
    schema: list[tuple[str, str]] | None = None,
    raise_on_dryrun: Exception | None = None,
) -> MagicMock:
    rows = rows or [{"customer_id": "C1", "exposure": 10.5}]
    schema = schema or [("customer_id", "STRING"), ("exposure", "FLOAT64")]

    class StubField:
        def __init__(self, n: str, t: str) -> None:
            self.name = n
            self.field_type = t

    class StubResult:
        def __init__(self) -> None:
            self.schema = [StubField(n, t) for n, t in schema]
            self.total_rows = len(rows)

        def __iter__(self):
            return iter(rows)

    class StubRow(dict):
        pass

    schema_objs = [StubField(n, t) for n, t in schema]

    def make_iter():
        return [StubRow(r) for r in rows]

    dry_job = MagicMock()
    dry_job.total_bytes_processed = estimated_bytes

    real_job = MagicMock()
    real_job.total_bytes_processed = estimated_bytes
    real_job.total_bytes_billed = estimated_bytes
    real_job.job_id = "job-test-123"

    class RealResult:
        schema = schema_objs
        total_rows = len(rows)

        def __iter__(self):
            return iter(make_iter())

    real_job.result = MagicMock(return_value=RealResult())

    client = MagicMock()
    if raise_on_dryrun:
        client.query.side_effect = [raise_on_dryrun, real_job]
    else:
        client.query.side_effect = [dry_job, real_job]
    return client


def test_only_select_allowed() -> None:
    out = bq.bigquery_query("DELETE FROM analytics.customer_metrics WHERE 1=1")
    assert out["code"] == "FORBIDDEN_STATEMENT"


def test_invalid_param_type_rejected() -> None:
    out = bq.bigquery_query(
        "SELECT * FROM `t` WHERE id = @id",
        params={"id": {"type": "geography", "value": "POINT(0 0)"}},
    )
    assert out["code"] == "INVALID_PARAM_TYPE"


def test_cost_guard_blocks_oversized_query(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import config

    config.get_settings.cache_clear()
    monkeypatch.setenv("BIGQUERY_MAX_BYTES_BILLED", "100")  # 100 bytes
    config.get_settings.cache_clear()

    client = _stub_client(estimated_bytes=10_000)
    monkeypatch.setattr(bq, "_client", lambda: client)

    out = bq.bigquery_query("SELECT 1")
    assert out["code"] == "COST_GUARD_BLOCKED"
    assert out["bytes_estimated"] == 10_000
    assert out["bytes_limit"] == 100


def test_happy_path_returns_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import config

    config.get_settings.cache_clear()

    client = _stub_client(
        estimated_bytes=512,
        rows=[
            {"customer_id": "C1", "exposure": 10.5},
            {"customer_id": "C2", "exposure": 7.25},
        ],
    )
    monkeypatch.setattr(bq, "_client", lambda: client)

    out = bq.bigquery_query(
        "SELECT customer_id, exposure FROM `proj.analytics.exposure` WHERE region = @region",
        params={"region": "BR"},
    )
    assert "rows" in out, out
    assert len(out["rows"]) == 2
    assert out["bytes_processed"] == 512
    assert out["job_id"] == "job-test-123"
    assert {f["name"] for f in out["schema"]} == {"customer_id", "exposure"}


def test_param_dict_form_is_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _stub_client()
    monkeypatch.setattr(bq, "_client", lambda: client)

    out = bq.bigquery_query(
        "SELECT * FROM `t` WHERE updated_at > @since",
        params={"since": {"type": "timestamp", "value": "2026-01-01T00:00:00Z"}},
    )
    assert "rows" in out

    # Verify the param was passed through to the dry-run job_config.
    dry_call = client.query.call_args_list[0]
    job_config = dry_call.kwargs.get("job_config")
    assert job_config is not None
    assert any(p.name == "since" for p in job_config.query_parameters)
    assert any(p.type_ == "TIMESTAMP" for p in job_config.query_parameters)

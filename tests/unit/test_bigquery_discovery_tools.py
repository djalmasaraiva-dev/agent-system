"""Tests for list_tables and describe_table — BigQuery discovery helpers."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from google.api_core import exceptions as gax

from app.tools import bigquery as bq


@pytest.fixture(autouse=True)
def _reset_client_cache() -> None:
    bq._client.cache_clear()
    yield
    bq._client.cache_clear()


def _stub_table(field_specs: list[tuple[str, str, str]]) -> MagicMock:
    class StubField:
        def __init__(self, name: str, type_: str, mode: str) -> None:
            self.name = name
            self.field_type = type_
            self.mode = mode
            self.description = None

    table = MagicMock()
    table.num_rows = 1234
    table.num_bytes = 5678
    table.time_partitioning = None
    table.clustering_fields = None
    table.schema = [StubField(n, t, m) for n, t, m in field_specs]
    return table


def test_list_tables_returns_table_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    t = MagicMock()
    t.table_id = "exposure_v3"
    t.full_table_id = "acme-financials:analytics.exposure_v3"
    t.table_type = "TABLE"
    client.list_tables.return_value = [t]
    monkeypatch.setattr(bq, "_client", lambda: client)

    out = bq.list_tables()
    assert out["dataset"] == "analytics"
    assert out["tables"][0]["table_id"] == "exposure_v3"


def test_list_tables_handles_missing_dataset(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.list_tables.side_effect = gax.NotFound("dataset gone")
    monkeypatch.setattr(bq, "_client", lambda: client)

    out = bq.list_tables(dataset="missing")
    assert out["code"] == "NOT_FOUND"


def test_describe_table_returns_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.get_table.return_value = _stub_table(
        [("customer_id", "STRING", "REQUIRED"), ("amount", "FLOAT64", "NULLABLE")]
    )
    monkeypatch.setattr(bq, "_client", lambda: client)

    out: dict[str, Any] = bq.describe_table("exposure_v3")
    assert out["num_rows"] == 1234
    assert {f["name"] for f in out["schema"]} == {"customer_id", "amount"}


def test_describe_table_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.get_table.side_effect = gax.NotFound("nope")
    monkeypatch.setattr(bq, "_client", lambda: client)

    out = bq.describe_table("missing")
    assert out["code"] == "NOT_FOUND"


def test_with_clause_query_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """`WITH cte AS (...) SELECT ...` is allow-listed."""
    from tests.unit.test_bigquery_tool import _stub_client  # reuse helper

    client = _stub_client()
    monkeypatch.setattr(bq, "_client", lambda: client)
    out = bq.bigquery_query("WITH x AS (SELECT 1 AS a) SELECT * FROM x")
    assert "rows" in out


def test_dml_statement_is_blocked() -> None:
    out = bq.bigquery_query("UPDATE analytics.t SET x = 1 WHERE id = @id", params={"id": 1})
    assert out["code"] == "FORBIDDEN_STATEMENT"

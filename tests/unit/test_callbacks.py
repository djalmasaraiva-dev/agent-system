"""Tests for governance callbacks (audit log, allow-list, rate limit)."""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest

from app.shared_libraries import callbacks

# --- Fakes ------------------------------------------------------------------


class FakeState(dict):
    """Dict that doubles as the ADK State object for tests."""


class FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name


def _ctx(agent_name: str, state: FakeState | None = None) -> SimpleNamespace:
    """Mimic CallbackContext / ToolContext duck-type."""
    return SimpleNamespace(
        agent_name=agent_name,
        invocation_id="inv-test-001",
        state=state if state is not None else FakeState(),
    )


# --- before_tool_callback ---------------------------------------------------


def test_before_tool_allows_listed_tool() -> None:
    ctx = _ctx("data_agent")
    out = callbacks.before_tool_callback(FakeTool("bigquery_query"), {"sql": "SELECT 1"}, ctx)
    assert out is None  # None == allow & continue


def test_before_tool_blocks_unlisted_tool() -> None:
    ctx = _ctx("data_agent")
    out = callbacks.before_tool_callback(FakeTool("delete_table"), {"table": "x"}, ctx)
    assert isinstance(out, dict)
    assert out["code"] == "TOOL_NOT_ALLOWED"
    assert "delete_table" in out["error"]


def test_before_tool_writes_telemetry_to_state() -> None:
    state = FakeState()
    ctx = _ctx("data_agent", state)
    callbacks.before_tool_callback(FakeTool("bigquery_query"), {"sql": "SELECT 1"}, ctx)
    assert "tool.bigquery_query.last_called_at" in state


def test_before_tool_logs_only_arg_keys_not_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """PII guard: don't log argument values, only key names."""
    captured: list[dict[str, Any]] = []

    def fake_info(event: str, **kw: Any) -> None:
        captured.append({"event": event, **kw})

    monkeypatch.setattr(callbacks.logger, "info", fake_info)
    ctx = _ctx("data_agent")
    callbacks.before_tool_callback(
        FakeTool("bigquery_query"),
        {"sql": "SELECT * FROM t WHERE customer_id = 'PII-DATA'"},
        ctx,
    )
    assert any("PII-DATA" not in str(c) for c in captured)
    assert all("PII-DATA" not in str(c) for c in captured)


# --- after_tool_callback ----------------------------------------------------


def test_after_tool_logs_bytes_billed_for_bigquery(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        callbacks.logger,
        "info",
        lambda event, **kw: captured.append({"event": event, **kw}),
    )
    ctx = _ctx("data_agent")
    callbacks.after_tool_callback(
        FakeTool("bigquery_query"),
        {"sql": "SELECT 1"},
        ctx,
        {"rows": [{"a": 1}], "bytes_billed": 12345, "job_id": "j1"},
    )
    ok_events = [c for c in captured if c["event"] == "tool.call.ok"]
    assert ok_events
    assert ok_events[0]["bytes_billed"] == 12345
    assert ok_events[0]["row_count"] == 1


def test_after_tool_records_error_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        callbacks.logger,
        "warning",
        lambda event, **kw: captured.append({"event": event, **kw}),
    )
    ctx = _ctx("data_agent")
    callbacks.after_tool_callback(
        FakeTool("bigquery_query"),
        {"sql": "DELETE …"},
        ctx,
        {"error": "blocked", "code": "FORBIDDEN_STATEMENT"},
    )
    err_events = [c for c in captured if c["event"] == "tool.call.error"]
    assert err_events
    assert err_events[0]["error_code"] == "FORBIDDEN_STATEMENT"


# --- rate_limit_callback ----------------------------------------------------


def test_rate_limit_initialises_window() -> None:
    state = FakeState()
    ctx = _ctx("coordinator", state)
    llm_request = SimpleNamespace(contents=[])
    callbacks.rate_limit_callback(ctx, llm_request)
    assert state["rate_limit.count"] == 1
    assert state["rate_limit.window_start"] > 0


def test_rate_limit_increments_count() -> None:
    state = FakeState()
    state["rate_limit.window_start"] = time.time()
    state["rate_limit.count"] = 5
    ctx = _ctx("coordinator", state)
    llm_request = SimpleNamespace(contents=[])
    callbacks.rate_limit_callback(ctx, llm_request)
    assert state["rate_limit.count"] == 6


# --- before_agent_callback --------------------------------------------------


def test_before_agent_stamps_invocation_metadata() -> None:
    state = FakeState()
    ctx = _ctx("coordinator", state)
    callbacks.before_agent_callback(ctx)
    assert state["invocation.agent"] == "coordinator"
    assert isinstance(state["invocation.started_at"], float)


# --- loop guards ------------------------------------------------------------


def test_total_tool_call_cap_short_circuits() -> None:
    """After MAX_TOOL_CALLS_PER_AGENT, before_tool returns a stop-error."""
    state = FakeState()
    ctx = _ctx("data_agent", state)

    # Use a different argument signature each time so the repeat-cap doesn't fire.
    for i in range(callbacks.MAX_TOOL_CALLS_PER_AGENT):
        out = callbacks.before_tool_callback(
            FakeTool("bigquery_query"), {"sql": f"SELECT {i}"}, ctx
        )
        assert out is None, f"call {i + 1} unexpectedly blocked"

    # Next call exceeds the cap.
    out = callbacks.before_tool_callback(
        FakeTool("bigquery_query"), {"sql": "SELECT 999"}, ctx
    )
    assert isinstance(out, dict)
    assert out["code"] == "TOOL_LOOP_GUARD_TOTAL"


def test_total_cap_is_per_agent_not_shared() -> None:
    """coordinator's budget is independent of data_agent's budget."""
    state = FakeState()

    # data_agent burns its whole budget (15 calls).
    ctx_data = _ctx("data_agent", state)
    for i in range(callbacks.MAX_TOOL_CALLS_PER_AGENT):
        out = callbacks.before_tool_callback(
            FakeTool("bigquery_query"), {"sql": f"SELECT {i}"}, ctx_data
        )
        assert out is None

    # coordinator (same session state) must still have its full budget.
    ctx_coord = _ctx("coordinator", state)
    out = callbacks.before_tool_callback(
        FakeTool("reporter_agent"), {"request": "compose"}, ctx_coord
    )
    assert out is None, "coordinator should not share data_agent's exhausted budget"


def test_repeat_tool_call_cap_short_circuits() -> None:
    """Calling the same tool with the same args >MAX_REPEATED_TOOL_CALLS triggers stop."""
    state = FakeState()
    ctx = _ctx("data_agent", state)

    args = {"dataset": "analytics"}

    for _ in range(callbacks.MAX_REPEATED_TOOL_CALLS):
        out = callbacks.before_tool_callback(FakeTool("list_tables"), args, ctx)
        assert out is None

    out = callbacks.before_tool_callback(FakeTool("list_tables"), args, ctx)
    assert isinstance(out, dict)
    assert out["code"] == "TOOL_LOOP_GUARD_REPEAT"


def test_repeat_cap_does_not_count_distinct_arg_calls() -> None:
    """Distinct args don't share the repeat counter."""
    state = FakeState()
    ctx = _ctx("data_agent", state)

    for i in range(callbacks.MAX_REPEATED_TOOL_CALLS + 1):
        out = callbacks.before_tool_callback(
            FakeTool("describe_table"),
            {"table_id": f"t{i}"},
            ctx,
        )
        assert out is None, f"distinct-args call {i} should not be blocked"

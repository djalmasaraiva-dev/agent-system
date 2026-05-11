"""Callback library — governance hooks aligned with the article's audit story.

Pattern from `google/adk-samples/python/agents/customer-service`:
  * `before_agent_callback` — stamp the invocation with caller identity / timing.
  * `before_model_callback` — rate-limit RPM per session.
  * `before_tool_callback` — audit-log every tool call with named args.
  * `after_tool_callback` — log outcome (errors, bytes_billed) and redact.

These callbacks are the runtime side of "who can ultimately cause a write to
that customer table?" — they emit a structured record per agent / tool call so
the IGA / SIEM / Cloud Logging side can answer the question without forensics.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmRequest, LlmResponse  # type: ignore[attr-defined]
from google.adk.tools import BaseTool  # type: ignore[attr-defined]
from google.adk.tools.tool_context import ToolContext

from app.utils.logging import get_logger

logger = get_logger("agent.callbacks")

# --- Rate limit defaults — override per agent if needed --------------------
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_RPM_DEFAULT = 30

# --- Loop guards per invocation -------------------------------------------
# Tool calls are bounded per-agent (so coordinator's delegations don't share a
# budget with data_agent's BigQuery exploration) and per-(tool, args) signature
# (catch retry-on-failure storms). When either cap trips, the callback returns
# a directive error that tells the LLM to STOP.
MAX_TOOL_CALLS_PER_AGENT = 15
MAX_REPEATED_TOOL_CALLS = 2


# --- Allow-list of tool names per agent (used by before_tool_callback) -----
TOOL_ALLOWLIST: dict[str, set[str]] = {
    "coordinator": {"research_agent", "data_agent", "reporter_agent"},
    "research_agent": {"google_search"},
    "data_agent": {"bigquery_query", "list_tables", "describe_table"},
    "reporter_agent": set(),
}


def _args_signature(args: dict[str, Any]) -> str:
    """Stable hash of tool args for loop detection."""
    payload = json.dumps(args, sort_keys=True, default=str)
    return hashlib.md5(payload.encode("utf-8"), usedforsecurity=False).hexdigest()[:10]


def before_agent_callback(callback_context: CallbackContext) -> None:
    """Stamp the invocation with timing + caller identity into session state."""
    state = callback_context.state
    agent_name = callback_context.agent_name
    state["invocation.started_at"] = time.time()
    state["invocation.agent"] = agent_name
    logger.info(
        "agent.invocation.start",
        agent=agent_name,
        invocation_id=callback_context.invocation_id,
        user_id=getattr(callback_context, "user_id", None),
    )


def rate_limit_callback(callback_context: CallbackContext, llm_request: LlmRequest) -> None:
    """Naive RPM rate-limit — sleeps when over quota.

    Replace with a Cloud Memorystore or token bucket in real prod; for the
    reference impl, the sample pattern is good enough and self-contained.
    """
    # ADK requires non-empty parts.text — patch any empty strings in place.
    for content in llm_request.contents:
        for part in content.parts or []:
            if getattr(part, "text", None) == "":
                part.text = " "

    now = time.time()
    state = callback_context.state
    if "rate_limit.window_start" not in state:
        state["rate_limit.window_start"] = now
        state["rate_limit.count"] = 1
        return

    state["rate_limit.count"] = state["rate_limit.count"] + 1
    elapsed = now - state["rate_limit.window_start"]

    if state["rate_limit.count"] > RATE_LIMIT_RPM_DEFAULT:
        delay = RATE_LIMIT_WINDOW_SECONDS - elapsed + 1
        if delay > 0:
            logger.warning(
                "agent.rate_limit.sleeping",
                agent=callback_context.agent_name,
                delay_s=round(delay, 2),
            )
            time.sleep(delay)
        state["rate_limit.window_start"] = now
        state["rate_limit.count"] = 1


def before_tool_callback(
    tool: BaseTool,
    args: dict[str, Any],
    tool_context: ToolContext,
) -> dict[str, Any] | None:
    """Audit every tool call. Block calls outside the agent's allow-list and
    short-circuit runaway loops.

    Returning a dict short-circuits the tool — the dict becomes the tool result
    visible to the LLM. We use this to deny disallowed tools fail-closed and to
    break out of repeat-call storms (e.g. tight retries on a NOT_FOUND).
    """
    agent_name = tool_context.agent_name
    tool_name = tool.name
    state = tool_context.state

    # 1) Allow-list check (fail-closed governance).
    allowed = TOOL_ALLOWLIST.get(agent_name)
    if allowed is not None and tool_name not in allowed:
        logger.warning(
            "tool.call.denied",
            agent=agent_name,
            tool=tool_name,
            invocation_id=tool_context.invocation_id,
            args_keys=sorted(args.keys()),
        )
        return {
            "error": f"Tool {tool_name!r} is not on the allow-list for {agent_name!r}.",
            "code": "TOOL_NOT_ALLOWED",
        }

    # 2) Per-AGENT total-calls cap. Each agent has its own budget so the
    # coordinator's delegations to sub-agents don't share a counter with the
    # sub-agent's internal tool calls.
    total_key = f"tool.call.total.{agent_name}"
    total = int(state.get(total_key, 0)) + 1
    state[total_key] = total
    if total > MAX_TOOL_CALLS_PER_AGENT:
        logger.warning(
            "tool.call.total_cap_hit",
            agent=agent_name,
            tool=tool_name,
            invocation_id=tool_context.invocation_id,
            total=total,
            cap=MAX_TOOL_CALLS_PER_AGENT,
        )
        return {
            "error": (
                f"Tool-call budget exhausted for agent {agent_name!r} "
                f"({MAX_TOOL_CALLS_PER_AGENT} calls). STOP calling tools and "
                f"respond to the user with what you have, or explain you cannot "
                f"answer."
            ),
            "code": "TOOL_LOOP_GUARD_TOTAL",
        }

    # 3) Per-(tool, args) repeat cap — catches NOT_FOUND retry storms.
    sig = _args_signature(args)
    counts_key = f"tool.call.repeat.{tool_name}.{sig}"
    n = int(state.get(counts_key, 0)) + 1
    state[counts_key] = n
    if n > MAX_REPEATED_TOOL_CALLS:
        logger.warning(
            "tool.call.repeat_blocked",
            agent=agent_name,
            tool=tool_name,
            invocation_id=tool_context.invocation_id,
            count=n,
            args_keys=sorted(args.keys()),
        )
        return {
            "error": (
                f"Tool {tool_name!r} called {n} times with identical arguments "
                f"and kept failing. STOP retrying — respond to the user that "
                f"you cannot complete the request."
            ),
            "code": "TOOL_LOOP_GUARD_REPEAT",
        }

    logger.info(
        "tool.call.start",
        agent=agent_name,
        tool=tool_name,
        invocation_id=tool_context.invocation_id,
        # log the keys, not the values — values may contain user data.
        args_keys=sorted(args.keys()),
    )
    state[f"tool.{tool_name}.last_called_at"] = time.time()
    return None


def after_tool_callback(
    tool: BaseTool,
    args: dict[str, Any],
    tool_context: ToolContext,
    tool_response: dict[str, Any],
) -> dict[str, Any] | None:
    """Log outcome + cost metrics. Surface errors so the audit log is honest."""
    agent_name = tool_context.agent_name
    tool_name = tool.name

    log_kwargs: dict[str, Any] = {
        "agent": agent_name,
        "tool": tool_name,
        "invocation_id": tool_context.invocation_id,
    }

    if isinstance(tool_response, dict):
        if (code := tool_response.get("code")) and code not in {"OK", None}:
            logger.warning("tool.call.error", error_code=code, **log_kwargs)
            return None
        # Tool-specific cost telemetry.
        if "bytes_billed" in tool_response:
            log_kwargs["bytes_billed"] = tool_response["bytes_billed"]
        if "rows" in tool_response and isinstance(tool_response["rows"], list):
            log_kwargs["row_count"] = len(tool_response["rows"])

    logger.info("tool.call.ok", **log_kwargs)
    return None


def after_model_callback(callback_context: CallbackContext, llm_response: LlmResponse) -> None:
    """Light hook to record token usage when present (per-agent cost accounting)."""
    usage = getattr(llm_response, "usage_metadata", None)
    if usage is None:
        return
    logger.info(
        "model.response",
        agent=callback_context.agent_name,
        invocation_id=callback_context.invocation_id,
        prompt_tokens=getattr(usage, "prompt_token_count", None),
        candidates_tokens=getattr(usage, "candidates_token_count", None),
        total_tokens=getattr(usage, "total_token_count", None),
    )

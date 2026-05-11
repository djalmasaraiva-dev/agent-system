"""Tests for the Agent Engine deploy wrapper.

`build_adk_app()` is what the deploy script hands to
`vertexai.agent_engines.create()`. We verify it returns either a fresh root
agent (older ADK) or a `google.adk.apps.App` (newer ADK), without actually
calling Vertex AI.
"""

from __future__ import annotations


def test_build_adk_app_returns_runnable_agent_or_app() -> None:
    from app.agent_engine_app import build_adk_app

    obj = build_adk_app()
    # Either an `App` (with .root_agent) or a bare LlmAgent.
    name = getattr(obj, "name", None) or getattr(getattr(obj, "root_agent", None), "name", None)
    # App.name normalises hyphens → underscores; root agent is "coordinator".
    assert name in {"agent_system", "agent-system", "coordinator"}


def test_app_engine_app_get_app_is_idempotent() -> None:
    """Calling get_app() repeatedly must return fresh, equivalent agents.

    Each call returns a fresh ADK object — sample-aligned pickle stability
    pattern. We verify name equality, not object identity.
    """
    from app.agent import app_engine_app

    a = app_engine_app.get_app()
    b = app_engine_app.get_app()

    a_root = getattr(a, "root_agent", a)
    b_root = getattr(b, "root_agent", b)
    assert a_root.name == b_root.name == "coordinator"

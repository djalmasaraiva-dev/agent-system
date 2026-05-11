"""Agent Engine wrapper.

Thin shim over `app.agent.AgentSystemApp` so the deploy script reads cleanly:

    from app.agent_engine_app import build_adk_app
    remote = vertexai.agent_engines.create(agent_engine=build_adk_app(), ...)
"""

from __future__ import annotations

from typing import Any

from app.agent import app_engine_app


def build_adk_app() -> Any:
    """Return the deploy-time `App` (or root agent fallback)."""
    return app_engine_app.get_app()

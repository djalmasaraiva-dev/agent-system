"""Root agent — the coordinator.

ADK sample conventions (`google/adk-samples/python/agents/customer-service`,
`economic-research-agent`) used here:

  * Module-level `root_agent` so `adk web` / `adk run` discover it.
  * `App(root_agent=..., name=...)` wrapper from `google.adk.apps` exposed as
    `app_engine_app` for Agent Engine deployment.
  * `global_instruction` flowed across all agents for cross-cutting policy.
  * `before_*` / `after_*` callbacks for runtime governance.
  * State-free wrapper class (`AgentSystemApp`) so the Reasoning Engine can
    pickle it cleanly — agents are built lazily inside `get_app()`.
"""

from __future__ import annotations

from typing import Any

from google.adk.agents import LlmAgent
from google.adk.tools.agent_tool import AgentTool

from app.agents.data import data_agent
from app.agents.prompts import COORDINATOR_INSTRUCTION, GLOBAL_INSTRUCTION
from app.agents.reporter import reporter_agent
from app.agents.research import research_agent
from app.config import get_settings
from app.shared_libraries.callbacks import (
    after_model_callback,
    after_tool_callback,
    before_agent_callback,
    before_tool_callback,
    rate_limit_callback,
)
from app.shared_libraries.safety import deterministic_config


def build_coordinator() -> LlmAgent:
    """Build the coordinator agent. Pure function — safe to call repeatedly."""
    settings = get_settings()
    return LlmAgent(
        name="coordinator",
        model=settings.coordinator_model,
        description=(
            "Orchestrates a research → data → reporter workflow. Routes the "
            "analyst's question to the right specialists and returns the brief."
        ),
        global_instruction=GLOBAL_INSTRUCTION,
        instruction=COORDINATOR_INSTRUCTION,
        tools=[
            AgentTool(agent=research_agent),
            AgentTool(agent=data_agent),
            AgentTool(agent=reporter_agent),
        ],
        generate_content_config=deterministic_config(temperature=0.2),
        before_agent_callback=before_agent_callback,
        before_model_callback=rate_limit_callback,
        before_tool_callback=before_tool_callback,
        after_tool_callback=after_tool_callback,
        after_model_callback=after_model_callback,
    )


# Module-level handle. `adk web`, Agent Engine deploy, and our FastAPI server
# all look up `root_agent` from this module.
root_agent: LlmAgent = build_coordinator()


# --- Agent Engine wrapper --------------------------------------------------


class AgentSystemApp:
    """State-free wrapper for Vertex AI Agent Engine deployment.

    Pattern from `google/adk-samples/python/agents/economic-research-agent`:
    keep the deploy-time object empty and instantiate ADK objects inside
    `get_app()` so the Reasoning Engine can pickle and re-hydrate cleanly.
    """

    agent_framework = "google-adk"

    def get_app(self) -> Any:
        """Return a `google.adk.apps.App` packaging the coordinator.

        Imported lazily so unit tests / contributor laptops without the new
        `apps` module still load the rest of the package.
        """
        try:
            from google.adk.apps import App  # ADK ≥ 1.x
        except ImportError:  # pragma: no cover — fallback for older ADK
            return build_coordinator()
        # ADK App.name requires a valid Python identifier (letters/digits/_),
        # whereas service_name is also used as the Cloud Run service name
        # (which allows hyphens). Normalise here.
        app_name = get_settings().service_name.replace("-", "_")
        return App(root_agent=build_coordinator(), name=app_name)


app_engine_app = AgentSystemApp()
"""Object handed to `vertexai.agent_engines.create(agent_engine=...)`."""

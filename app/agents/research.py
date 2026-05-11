"""Research agent — public sources via the built-in google_search tool."""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.tools import google_search  # type: ignore[attr-defined]

from app.agents.prompts import RESEARCH_INSTRUCTION
from app.config import get_settings
from app.shared_libraries.callbacks import (
    after_model_callback,
    after_tool_callback,
    before_agent_callback,
    before_tool_callback,
    rate_limit_callback,
)
from app.shared_libraries.safety import deterministic_config


def build_research_agent() -> LlmAgent:
    settings = get_settings()
    return LlmAgent(
        name="research_agent",
        model=settings.research_model,
        description=(
            "Researches public information on a topic using Google Search and "
            "returns a concise, citation-rich brief in markdown."
        ),
        instruction=RESEARCH_INSTRUCTION,
        tools=[google_search],
        # Sub-agent output written into session state so the coordinator can
        # reference {research_brief?} in templated instructions if needed.
        output_key="research_brief",
        generate_content_config=deterministic_config(temperature=0.2),
        before_agent_callback=before_agent_callback,
        before_model_callback=rate_limit_callback,
        before_tool_callback=before_tool_callback,
        after_tool_callback=after_tool_callback,
        after_model_callback=after_model_callback,
    )


research_agent: LlmAgent = build_research_agent()

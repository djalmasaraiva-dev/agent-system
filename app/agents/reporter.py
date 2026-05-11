"""Reporter agent — synthesises research + data into the final brief."""

from __future__ import annotations

from google.adk.agents import LlmAgent

from app.agents.prompts import REPORTER_INSTRUCTION
from app.config import get_settings
from app.shared_libraries.callbacks import (
    after_model_callback,
    before_agent_callback,
    rate_limit_callback,
)
from app.shared_libraries.safety import creative_config


def build_reporter_agent() -> LlmAgent:
    settings = get_settings()
    return LlmAgent(
        name="reporter_agent",
        model=settings.reporter_model,
        description=(
            "Composes a clean executive-style brief from the research and data "
            "findings provided by the coordinator."
        ),
        instruction=REPORTER_INSTRUCTION,
        # Reporter has no tools — it's pure synthesis. Skip tool callbacks.
        output_key="final_report",
        generate_content_config=creative_config(temperature=0.3),
        before_agent_callback=before_agent_callback,
        before_model_callback=rate_limit_callback,
        after_model_callback=after_model_callback,
    )


reporter_agent: LlmAgent = build_reporter_agent()

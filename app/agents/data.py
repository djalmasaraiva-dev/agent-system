"""Data agent — read-only BigQuery analytics."""

from __future__ import annotations

from google.adk.agents import LlmAgent

from app.agents.prompts import data_instruction
from app.config import get_settings
from app.shared_libraries.callbacks import (
    after_model_callback,
    after_tool_callback,
    before_agent_callback,
    before_tool_callback,
    rate_limit_callback,
)
from app.shared_libraries.safety import deterministic_config
from app.tools.bigquery import bigquery_query, describe_table, list_tables


def build_data_agent() -> LlmAgent:
    settings = get_settings()
    return LlmAgent(
        name="data_agent",
        model=settings.data_model,
        description=(
            "Answers analytical questions by querying the internal BigQuery dataset "
            f"`{settings.bigquery_dataset}` in project `{settings.google_cloud_project}`."
        ),
        instruction=data_instruction(
            project=settings.google_cloud_project,
            dataset=settings.bigquery_dataset,
            location=settings.bigquery_location,
        ),
        tools=[bigquery_query, list_tables, describe_table],
        output_key="data_summary",
        generate_content_config=deterministic_config(temperature=0.1),
        before_agent_callback=before_agent_callback,
        before_model_callback=rate_limit_callback,
        before_tool_callback=before_tool_callback,
        after_tool_callback=after_tool_callback,
        after_model_callback=after_model_callback,
    )


data_agent: LlmAgent = build_data_agent()

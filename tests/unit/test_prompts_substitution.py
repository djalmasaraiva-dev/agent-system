"""The data agent's instruction must include the live project/dataset values."""

from __future__ import annotations


def test_data_agent_instruction_includes_settings_values() -> None:
    from app.agents.data import data_agent
    from app.config import get_settings

    s = get_settings()
    instr = data_agent.instruction or ""
    assert s.bigquery_dataset in instr
    assert s.google_cloud_project in instr
    assert s.bigquery_location in instr


def test_data_agent_instruction_links_to_canonical_skill() -> None:
    from app.agents.data import data_agent

    instr = data_agent.instruction or ""
    assert "github.com/google/skills/tree/main/skills/cloud/bigquery-basics" in instr


def test_research_agent_instruction_links_to_gemini_api_skill() -> None:
    from app.agents.research import research_agent

    instr = research_agent.instruction or ""
    assert "github.com/google/skills/tree/main/skills/cloud/gemini-api" in instr


def test_coordinator_global_instruction_excludes_pii_leak_guidance() -> None:
    """Persona must explicitly forbid PII leakage."""
    from app.agent import root_agent

    g = root_agent.global_instruction or ""
    assert "PII" in g
    assert "fabricate" in g.lower()

"""Smoke tests: agents instantiate, expose the right tools, callbacks wired."""

from __future__ import annotations


def test_research_agent_basics() -> None:
    from app.agents.research import research_agent

    assert research_agent.name == "research_agent"
    assert research_agent.output_key == "research_brief"
    assert research_agent.generate_content_config is not None
    assert research_agent.generate_content_config.temperature is not None
    # google_search builtin must be present
    assert research_agent.tools


def test_data_agent_wires_bigquery_tools_and_callbacks() -> None:
    from app.agents.data import data_agent

    assert data_agent.name == "data_agent"
    assert data_agent.output_key == "data_summary"

    func_names = {getattr(t, "__name__", "") for t in data_agent.tools}
    assert "bigquery_query" in func_names
    assert "list_tables" in func_names
    assert "describe_table" in func_names

    # Governance callbacks wired
    assert data_agent.before_agent_callback is not None
    assert data_agent.before_model_callback is not None
    assert data_agent.before_tool_callback is not None
    assert data_agent.after_tool_callback is not None


def test_data_agent_references_skill_url() -> None:
    from app.agents.data import data_agent

    assert "github.com/google/skills" in data_agent.instruction
    assert "bigquery-basics" in data_agent.instruction


def test_reporter_agent_has_no_tools_only_synthesis() -> None:
    from app.agents.reporter import reporter_agent

    assert reporter_agent.name == "reporter_agent"
    assert not reporter_agent.tools
    assert reporter_agent.output_key == "final_report"


def test_coordinator_wraps_three_specialists_with_global_instruction() -> None:
    from app.agent import root_agent

    assert root_agent.name == "coordinator"
    assert len(root_agent.tools) == 3
    inner_names = {getattr(getattr(t, "agent", None), "name", None) for t in root_agent.tools}
    assert inner_names == {"research_agent", "data_agent", "reporter_agent"}
    assert root_agent.global_instruction
    # The persona must mention the regulated FS context.
    assert "regulated" in root_agent.global_instruction.lower()


def test_agent_engine_wrapper_is_state_free() -> None:
    """The deploy-time wrapper must not hold any non-pickleable state."""
    from app.agent import AgentSystemApp, app_engine_app

    assert isinstance(app_engine_app, AgentSystemApp)
    assert app_engine_app.agent_framework == "google-adk"
    # No instance attributes — Reasoning Engine pickles cleanly.
    assert vars(app_engine_app) == {}


def test_app_module_exports_root_agent() -> None:
    """`adk web` and Agent Engine look up `root_agent` from app.agent."""
    import app
    import app.agent

    assert hasattr(app.agent, "root_agent")
    assert app.root_agent is app.agent.root_agent

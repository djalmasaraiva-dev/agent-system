"""Agent system: multi-agent ADK with cross-platform identity bridge.

Reference implementation accompanying the article
"When Agents Call Agents: The Exponential Access Problem in Multi-Agent ADK Systems".

Public surface:
  * `root_agent`      — the coordinator (LlmAgent), discovered by `adk web`.
  * `app_engine_app`  — state-free wrapper for Vertex AI Agent Engine deploy.
"""

from app.agent import app_engine_app, root_agent

__version__ = "0.1.0"
__all__ = ["app_engine_app", "root_agent"]

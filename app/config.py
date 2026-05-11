"""Centralised settings loaded from environment / .env.

All configuration flows through `get_settings()` so tests can override values
via dependency injection without monkey-patching modules.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Classification = Literal["low-risk", "medium-risk", "high-risk-data-access", "regulated"]


class Settings(BaseSettings):
    """Process-wide configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Vertex AI / Gemini -------------------------------------------------
    google_cloud_project: str = Field(default="acme-financials")
    google_cloud_location: str = Field(default="us-central1")
    google_genai_use_vertexai: bool = Field(default=True)

    coordinator_model: str = Field(default="gemini-3.1-pro-preview")
    research_model: str = Field(default="gemini-3.1-pro-preview")
    data_model: str = Field(default="gemini-3-flash-preview")
    reporter_model: str = Field(default="gemini-3-flash-preview")

    # --- BigQuery -----------------------------------------------------------
    bigquery_dataset: str = Field(default="analytics")
    bigquery_location: str = Field(default="US")
    bigquery_max_bytes_billed: int = Field(default=1 * 1024 * 1024 * 1024)  # 1 GiB
    bigquery_max_rows: int = Field(default=1000)

    # --- Identity bridge metadata -------------------------------------------
    agent_name: str = Field(default="coordinator")
    agent_version: str = Field(default="0.1.0")
    agent_owner_email: str = Field(default="ai-platform-ops@example.com")
    agent_fallback_owner_email: str = Field(default="ai-platform-ops@example.com")
    agent_business_unit: str = Field(default="Platform")
    agent_classification: Classification = Field(default="low-risk")
    agent_business_context: str = Field(default="")
    agent_decommission_after: datetime | None = Field(default=None)

    # --- IAP for Agents -----------------------------------------------------
    iap_expected_audience: str = Field(default="")
    iap_required: bool = Field(default=False)

    # --- Server / observability --------------------------------------------
    host: str = Field(default="0.0.0.0")  # noqa: S104 — Cloud Run requires 0.0.0.0
    port: int = Field(default=8080)
    log_level: str = Field(default="INFO")
    enable_cloud_trace: bool = Field(default=True)
    service_name: str = Field(default="agent-system")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached settings instance."""
    return Settings()

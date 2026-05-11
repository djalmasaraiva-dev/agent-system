"""Shared pytest fixtures.

We keep `app/` on sys.path explicitly so tests work without an editable install
on dev machines that haven't run `uv sync`.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import os

# Force a deterministic, dev-mode env for every test before settings load.
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "acme-financials")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")
os.environ.setdefault("IAP_REQUIRED", "false")
os.environ.setdefault("IAP_EXPECTED_AUDIENCE", "")
os.environ.setdefault("ENABLE_CLOUD_TRACE", "false")
os.environ.setdefault("AGENT_NAME", "coordinator")
os.environ.setdefault("AGENT_OWNER_EMAIL", "owner@example.com")
os.environ.setdefault("AGENT_FALLBACK_OWNER_EMAIL", "fallback@example.com")

import pytest

from app.config import get_settings
from app.identity.registry import reset_registry


@pytest.fixture(autouse=True)
def _reset_registry_around_each_test() -> None:
    """The registry caches; reset before and after each test."""
    reset_registry()
    yield
    reset_registry()


@pytest.fixture
def settings():
    get_settings.cache_clear()
    return get_settings()

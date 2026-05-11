"""Verify safety_settings + sampling defaults."""

from __future__ import annotations

from app.shared_libraries.safety import creative_config, deterministic_config


def test_deterministic_config_low_temperature() -> None:
    cfg = deterministic_config()
    assert cfg.temperature is not None
    assert cfg.temperature <= 0.2
    assert cfg.candidate_count == 1
    assert cfg.safety_settings


def test_creative_config_modest_temperature() -> None:
    cfg = creative_config()
    assert cfg.temperature is not None
    assert 0.2 <= cfg.temperature <= 0.6


def test_safety_categories_block_low_and_above() -> None:
    """All four harm categories are blocked at the lowest threshold."""
    from google.genai import types as genai_types

    cfg = deterministic_config()
    by_cat = {s.category: s.threshold for s in cfg.safety_settings}
    expected = {
        genai_types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        genai_types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        genai_types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        genai_types.HarmCategory.HARM_CATEGORY_HARASSMENT,
    }
    assert expected.issubset(set(by_cat.keys()))
    assert all(t == genai_types.HarmBlockThreshold.BLOCK_LOW_AND_ABOVE for t in by_cat.values())

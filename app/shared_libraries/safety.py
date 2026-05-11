"""GenerateContentConfig defaults — safety + sampling per agent role.

Sample alignment: customer-service / academic-research agents both wire
explicit `safety_settings` and modest `temperature`. We default to that.
"""

from __future__ import annotations

from google.genai import types as genai_types

# Block at the lowest threshold for harmful categories — these are public,
# enterprise-facing agents.
_DEFAULT_SAFETY_SETTINGS = [
    genai_types.SafetySetting(
        category=genai_types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        threshold=genai_types.HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
    ),
    genai_types.SafetySetting(
        category=genai_types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        threshold=genai_types.HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
    ),
    genai_types.SafetySetting(
        category=genai_types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        threshold=genai_types.HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
    ),
    genai_types.SafetySetting(
        category=genai_types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        threshold=genai_types.HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
    ),
]


def deterministic_config(temperature: float = 0.1) -> genai_types.GenerateContentConfig:
    """Low-temperature config for analytical/data work — stable answers."""
    return genai_types.GenerateContentConfig(
        temperature=temperature,
        top_p=0.95,
        candidate_count=1,
        max_output_tokens=8192,
        safety_settings=_DEFAULT_SAFETY_SETTINGS,
    )


def creative_config(temperature: float = 0.4) -> genai_types.GenerateContentConfig:
    """Slightly higher temperature for prose composition (reporter)."""
    return genai_types.GenerateContentConfig(
        temperature=temperature,
        top_p=0.95,
        candidate_count=1,
        max_output_tokens=8192,
        safety_settings=_DEFAULT_SAFETY_SETTINGS,
    )

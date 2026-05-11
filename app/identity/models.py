"""Agent identity envelope — schema from the article, verbatim.

The bridge endpoint at `/.well-known/agent-identity` serves this exact shape so
any IGA-side connector can ingest it without per-platform mapping.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr

Classification = Literal["low-risk", "medium-risk", "high-risk-data-access", "regulated"]


class AgentIdentity(BaseModel):
    """Portable agent identity envelope.

    Wraps the platform's native identity (e.g. Google Cloud SPIFFE ID for
    Gemini Enterprise Agent Platform) with the lifecycle/ownership metadata
    that an upstream IGA needs to certify ownership and run access reviews.
    """

    agent_id: str
    name: str
    version: str
    platform: str
    spiffe_id: str | None = None
    owner_email: EmailStr
    fallback_owner_email: EmailStr
    business_unit: str
    created_at: datetime
    last_reviewed_at: datetime | None = None
    model: str
    tools: list[str]
    inbound_callers: list[str]
    outbound_callees: list[str]
    classification: Classification
    data_scopes: list[str]
    business_context: str
    decommission_after: datetime | None = None

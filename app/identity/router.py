"""FastAPI router for the cross-platform identity bridge.

Exposes:
  GET /.well-known/agent-identity        — the agent this service hosts
  GET /.well-known/agents                — full registry (per-deployment topology)
  GET /.well-known/agent-identity/{name} — specific agent by name

All routes are protected by `verify_iap_jwt`. The article spec shows a single
endpoint per agent — that maps to the first route here, with the additional
list/by-name routes added for IGA-side discovery on multi-agent images.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.identity.iap_auth import verify_iap_jwt
from app.identity.models import AgentIdentity
from app.identity.registry import get_current_identity, get_registry, list_identities

router = APIRouter(
    prefix="/.well-known",
    tags=["identity"],
    dependencies=[Depends(verify_iap_jwt)],
)


@router.get("/agent-identity", response_model=AgentIdentity)
async def get_identity(
    _claims: Annotated[dict[str, Any], Depends(verify_iap_jwt)],
) -> AgentIdentity:
    """Return the identity of the agent this service is configured to host."""
    return get_current_identity()


@router.get("/agents", response_model=list[AgentIdentity])
async def get_agents(
    _claims: Annotated[dict[str, Any], Depends(verify_iap_jwt)],
) -> list[AgentIdentity]:
    """Return the full topology — every agent the IGA should be aware of."""
    return list_identities()


@router.get("/agent-identity/{agent_name}", response_model=AgentIdentity)
async def get_identity_by_name(
    agent_name: str,
    _claims: Annotated[dict[str, Any], Depends(verify_iap_jwt)],
) -> AgentIdentity:
    """Return the identity for a specific agent by name."""
    reg = get_registry()
    if agent_name not in reg:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown agent: {agent_name}",
        )
    return reg[agent_name]

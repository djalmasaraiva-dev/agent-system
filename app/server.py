"""FastAPI server — Agent Starter Pack convention.

Exposes:
  GET  /healthz                        — liveness
  GET  /readyz                         — readiness (incl. ADC sanity check)
  GET  /.well-known/agent-identity     — identity bridge (see app/identity/router.py)
  POST /invoke                         — runs the coordinator agent end-to-end
  POST /stream                         — streams events from the coordinator

ADK Runner uses `InMemorySessionService` for dev. Swap to `VertexAiSessionService`
or your own persistence layer for production multi-turn workloads.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import StreamingResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types
from pydantic import BaseModel, Field

from app.agent import root_agent
from app.config import get_settings
from app.identity.iap_auth import verify_iap_jwt
from app.identity.router import router as identity_router
from app.utils.logging import configure_logging, get_logger
from app.utils.tracing import setup_tracing

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger(__name__)

# Vertex AI ADK requires these env vars before any genai import is exercised.
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", settings.google_cloud_project)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", settings.google_cloud_location)
os.environ.setdefault(
    "GOOGLE_GENAI_USE_VERTEXAI",
    "true" if settings.google_genai_use_vertexai else "false",
)


# --- Request/response models ------------------------------------------------


class InvokeRequest(BaseModel):
    message: str = Field(..., description="Analyst question for the coordinator.")
    user_id: str = Field(default="anonymous")
    session_id: str | None = Field(
        default=None,
        description="Reuse this to continue a multi-turn conversation.",
    )


class InvokeResponse(BaseModel):
    session_id: str
    user_id: str
    final_text: str
    events: list[dict[str, Any]]


# --- ADK Runner -------------------------------------------------------------

# ADK 2.0+ validates Runner.app_name (and App.name) as a Python identifier —
# letters/digits/underscore only. service_name is also used as the Cloud Run
# service name (which allows hyphens), so normalise here.
_APP_NAME = settings.service_name.replace("-", "_")

_session_service = InMemorySessionService()  # type: ignore[no-untyped-call]
_runner = Runner(
    app_name=_APP_NAME,
    agent=root_agent,
    session_service=_session_service,
)


async def _ensure_session(user_id: str, session_id: str | None) -> str:
    """Create the session if absent. Returns the session ID."""
    sid = session_id or f"sess-{uuid.uuid4()}"
    existing = await _session_service.get_session(
        app_name=_APP_NAME, user_id=user_id, session_id=sid
    )
    if existing is None:
        await _session_service.create_session(
            app_name=_APP_NAME, user_id=user_id, session_id=sid
        )
    return sid


def _to_user_content(message: str) -> genai_types.Content:
    return genai_types.Content(role="user", parts=[genai_types.Part(text=message)])


async def _run_agent(
    *, user_id: str, session_id: str, message: str
) -> tuple[str, list[dict[str, Any]]]:
    """Run the coordinator end-to-end and return (final_text, events)."""
    final_text = ""
    events: list[dict[str, Any]] = []
    async for event in _runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=_to_user_content(message),
    ):
        events.append(_summarise_event(event))
        if event.is_final_response() and event.content and event.content.parts:
            final_text = "".join(p.text or "" for p in event.content.parts)
    return final_text, events


def _summarise_event(event: Any) -> dict[str, Any]:
    """Project an ADK event into something JSON-friendly for the response."""
    summary: dict[str, Any] = {"author": getattr(event, "author", None)}
    if getattr(event, "actions", None) and getattr(event.actions, "transfer_to_agent", None):
        summary["transfer_to"] = event.actions.transfer_to_agent
    content = getattr(event, "content", None)
    if content and getattr(content, "parts", None):
        for p in content.parts:
            if getattr(p, "function_call", None):
                summary.setdefault("tool_calls", []).append(
                    {"name": p.function_call.name, "args": dict(p.function_call.args or {})}
                )
            if getattr(p, "function_response", None):
                summary.setdefault("tool_responses", []).append({"name": p.function_response.name})
            if getattr(p, "text", None):
                summary.setdefault("text", "")
                summary["text"] += p.text
    return summary


# --- FastAPI app ------------------------------------------------------------


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.service_name,
        version="0.1.0",
        description=(
            "Multi-agent ADK system with cross-platform identity bridge. "
            "See /.well-known/agent-identity for the agent envelope."
        ),
    )

    app.include_router(identity_router)
    setup_tracing(
        app,
        service_name=settings.service_name,
        project_id=settings.google_cloud_project,
        enabled=settings.enable_cloud_trace,
    )

    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["health"])
    async def readyz() -> dict[str, Any]:
        # Soft-checks Application Default Credentials so misconfigured
        # deployments fail readiness instead of erroring on first invoke.
        creds_ok = True
        creds_err: str | None = None
        try:
            import google.auth

            google.auth.default()
        except Exception as exc:
            creds_ok = False
            creds_err = str(exc)
        return {
            "status": "ok" if creds_ok else "degraded",
            "credentials": creds_ok,
            "credentials_error": creds_err,
            "agent": settings.agent_name,
            "model": settings.coordinator_model,
        }

    @app.post("/invoke", response_model=InvokeResponse, tags=["agent"])
    async def invoke(
        req: InvokeRequest,
        claims: Annotated[dict[str, Any], Depends(verify_iap_jwt)],
    ) -> InvokeResponse:
        log = logger.bind(
            caller=claims.get("email"),
            user_id=req.user_id,
            agent=settings.agent_name,
        )
        sid = await _ensure_session(req.user_id, req.session_id)
        log.info("invoke.start", session_id=sid)
        try:
            final_text, events = await _run_agent(
                user_id=req.user_id, session_id=sid, message=req.message
            )
        except Exception as exc:
            log.error("invoke.failed", error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"agent run failed: {exc}",
            ) from exc

        log.info("invoke.ok", session_id=sid, events=len(events))
        return InvokeResponse(
            session_id=sid,
            user_id=req.user_id,
            final_text=final_text,
            events=events,
        )

    @app.post("/stream", tags=["agent"])
    async def stream(
        req: InvokeRequest,
        claims: Annotated[dict[str, Any], Depends(verify_iap_jwt)],
    ) -> StreamingResponse:
        sid = await _ensure_session(req.user_id, req.session_id)

        async def event_iter() -> AsyncIterator[bytes]:
            yield _sse({"type": "session", "session_id": sid})
            try:
                async for event in _runner.run_async(
                    user_id=req.user_id,
                    session_id=sid,
                    new_message=_to_user_content(req.message),
                ):
                    yield _sse({"type": "event", **_summarise_event(event)})
                    if event.is_final_response():
                        yield _sse({"type": "done"})
                        return
            except asyncio.CancelledError:
                with contextlib.suppress(Exception):
                    yield _sse({"type": "cancelled"})
                raise

        return StreamingResponse(event_iter(), media_type="text/event-stream")

    return app


def _sse(payload: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(payload, default=str)}\n\n".encode()


app = create_app()


def run() -> None:
    """Console-script entrypoint (`agent-server`)."""
    import uvicorn

    uvicorn.run(
        "app.server:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    run()

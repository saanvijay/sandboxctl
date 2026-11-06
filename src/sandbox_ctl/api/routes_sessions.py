"""Session routes: POST /sessions/run, GET /sessions/{id}.

We intentionally omit ``from __future__ import annotations`` here: FastAPI
resolves route signatures at runtime, and a forward-ref'd ``Caller`` under
PEP 563 breaks Pydantic's dependency-wire resolution.
"""

import logging
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from sandbox_ctl.api.auth import Caller
from sandbox_ctl.runtime.agent_client import AgentError
from sandbox_ctl.runtime.driver import DriverError
from sandbox_ctl.session.manager import RunSubmission, SessionManager
from sandbox_ctl.session.quotas import QuotaError
from sandbox_ctl.session.registry import SessionNotFound, SessionRegistry

logger = logging.getLogger(__name__)


class RunRequest(BaseModel):
    code: str = Field(min_length=1, max_length=1_048_576)
    language: str = Field(min_length=1, max_length=32)
    flavor_id: str | None = Field(default=None, max_length=64)
    timeout_s: int = Field(default=30, ge=1, le=600)


class RunResponse(BaseModel):
    session_id: str
    flavor_id: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int


class SessionStateView(BaseModel):
    session_id: str
    tenant_id: str
    flavor_id: str
    phase: str
    exit_code: int | None
    error: str | None


CallerDep = Callable[..., Awaitable[Caller]]


def build_router(
    *,
    manager: SessionManager,
    registry: SessionRegistry,
    caller_dep: CallerDep,
    default_flavor_id: str,
) -> APIRouter:
    router = APIRouter(prefix="/sessions", tags=["sessions"])

    @router.post("/run", response_model=RunResponse, status_code=status.HTTP_200_OK)
    async def run_session(
        body: RunRequest,
        caller: Caller = Depends(caller_dep),
    ) -> RunResponse:
        submission = RunSubmission(
            tenant_id=caller.tenant_id,
            flavor_id=body.flavor_id or default_flavor_id,
            code=body.code,
            language=body.language,
            timeout_s=body.timeout_s,
        )
        try:
            outcome = await manager.run(submission)
        except QuotaError as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)
            ) from exc
        except (DriverError, AgentError) as exc:
            logger.exception("session failed", extra={"tenant_id": caller.tenant_id})
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail="runtime error"
            ) from exc
        return RunResponse(
            session_id=outcome.session_id,
            flavor_id=outcome.flavor_id,
            exit_code=outcome.exit_code,
            stdout=outcome.stdout,
            stderr=outcome.stderr,
            duration_ms=outcome.duration_ms,
        )

    @router.get("/{session_id}", response_model=SessionStateView)
    async def get_session(
        session_id: str,
        caller: Caller = Depends(caller_dep),
    ) -> SessionStateView:
        try:
            state = await registry.get(session_id)
        except SessionNotFound:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from None
        if state.tenant_id != caller.tenant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return SessionStateView(
            session_id=state.session_id,
            tenant_id=state.tenant_id,
            flavor_id=state.flavor_id,
            phase=state.phase.value,
            exit_code=state.exit_code,
            error=state.error,
        )

    return router

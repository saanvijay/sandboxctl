"""SessionManager: orchestrates one run end-to-end.

Lifecycle (see DESIGN.md §5.1):

    acquire -> isolate -> mint creds -> run -> teardown

Dependencies are injected so unit tests can wire fakes. The manager is
intentionally free of transport details; it depends only on the typed
driver / agent / credential interfaces.
"""

from __future__ import annotations

import logging
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sandbox_ctl.config import Settings
from sandbox_ctl.isolation.creds import CredentialMinter, SessionCredential
from sandbox_ctl.pool.warm_pool import WarmPool
from sandbox_ctl.runtime.agent_client import AgentClient, AgentError, RunRequest
from sandbox_ctl.runtime.driver import Driver, DriverError, SandboxHandle
from sandbox_ctl.session.quotas import QuotaEnforcer, QuotaError
from sandbox_ctl.session.registry import SessionRegistry
from sandbox_ctl.session.state import SessionPhase, SessionState
from sandbox_ctl.telemetry.events import EventEmitter

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RunSubmission:
    tenant_id: str
    flavor_id: str
    code: str
    language: str
    timeout_s: int


@dataclass(frozen=True, slots=True)
class RunOutcome:
    session_id: str
    flavor_id: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int


ColdSpecFactory = Callable[[str, SessionCredential], Awaitable[dict[str, object]]]
"""Build a Pod spec for a *leased* session, given its flavor and credential."""


class SessionError(RuntimeError):
    pass


class SessionManager:
    def __init__(
        self,
        *,
        settings: Settings,
        driver: Driver,
        pool: WarmPool,
        agent: AgentClient,
        creds: CredentialMinter,
        quotas: QuotaEnforcer,
        registry: SessionRegistry,
        events: EventEmitter,
        cold_spec_factory: ColdSpecFactory,
    ) -> None:
        self._settings = settings
        self._driver = driver
        self._pool = pool
        self._agent = agent
        self._creds = creds
        self._quotas = quotas
        self._registry = registry
        self._events = events
        self._cold_spec = cold_spec_factory

    async def run(self, submission: RunSubmission) -> RunOutcome:
        session_id = _new_session_id()
        state = SessionState(
            session_id=session_id,
            tenant_id=submission.tenant_id,
            flavor_id=submission.flavor_id,
        )
        await self._registry.put(state)
        self._events.emit(
            session_id=session_id,
            tenant_id=submission.tenant_id,
            kind="submitted",
            flavor_id=submission.flavor_id,
            language=submission.language,
        )

        try:
            await self._quotas.acquire(submission.tenant_id)
        except QuotaError as exc:
            await self._registry.update(session_id, SessionPhase.FAILED, error=str(exc))
            raise

        handle: SandboxHandle | None = None
        cred: SessionCredential | None = None
        start = time.monotonic()

        try:
            handle = await self._acquire(submission.flavor_id, session_id, submission.tenant_id)
            await self._registry.update(
                session_id,
                SessionPhase.ACQUIRED,
                sandbox_id=handle.sandbox_id,
                pod_name=handle.pod_name,
            )

            cred = self._creds.mint(session_id, submission.tenant_id)
            await self._registry.update(session_id, SessionPhase.ISOLATED, cred_id=cred.cred_id)
            self._events.emit(
                session_id=session_id,
                tenant_id=submission.tenant_id,
                kind="isolated",
                cred_id=cred.cred_id,
            )

            await self._registry.update(session_id, SessionPhase.RUNNING)
            result = await self._agent.run(
                handle.agent_endpoint,
                RunRequest(
                    code=submission.code,
                    language=submission.language,
                    timeout_s=submission.timeout_s,
                ),
            )
            await self._registry.update(
                session_id, SessionPhase.COMPLETED, exit_code=result.exit_code
            )
            self._events.emit(
                session_id=session_id,
                tenant_id=submission.tenant_id,
                kind="completed",
                exit_code=result.exit_code,
                duration_ms=result.duration_ms,
            )
            return RunOutcome(
                session_id=session_id,
                flavor_id=submission.flavor_id,
                exit_code=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
                duration_ms=result.duration_ms,
            )

        except (DriverError, AgentError, SessionError) as exc:
            await self._fail(session_id, exc)
            raise
        finally:
            await self._teardown(session_id, submission.tenant_id, handle, cred, started=start)

    async def _acquire(self, flavor_id: str, session_id: str, tenant_id: str) -> SandboxHandle:
        warm = await self._pool.lease(flavor_id)
        if warm is not None:
            await self._driver.relabel(warm, {"session_id": session_id, "pool": "ondemand"})
            self._events.emit(
                session_id=session_id,
                tenant_id=tenant_id,
                kind="warm_hit",
                flavor_id=flavor_id,
            )
            return warm
        self._events.emit(
            session_id=session_id,
            tenant_id=tenant_id,
            kind="warm_miss",
            flavor_id=flavor_id,
        )
        cred = self._creds.mint(session_id, tenant_id)
        spec = await self._cold_spec(flavor_id, cred)
        return await self._driver.create(spec, flavor_id=flavor_id)

    async def _fail(self, session_id: str, exc: Exception) -> None:
        try:
            state = await self._registry.get(session_id)
        except KeyError:
            return
        if state.phase in {SessionPhase.COMPLETED, SessionPhase.FAILED, SessionPhase.DESTROYED}:
            return
        try:
            await self._registry.update(session_id, SessionPhase.FAILED, error=str(exc))
        except Exception:
            logger.exception("failed to mark session failed", extra={"session_id": session_id})

    async def _teardown(
        self,
        session_id: str,
        tenant_id: str,
        handle: SandboxHandle | None,
        cred: SessionCredential | None,
        *,
        started: float,
    ) -> None:
        if cred is not None:
            self._creds.revoke(cred.cred_id)
        if handle is not None:
            try:
                await self._driver.destroy(handle)
            except DriverError:
                logger.exception("destroy failed", extra={"session_id": session_id})
        await self._quotas.release(tenant_id)
        try:
            state = await self._registry.get(session_id)
            if state.phase != SessionPhase.DESTROYED:
                await self._registry.update(session_id, SessionPhase.DESTROYED)
        except Exception:
            logger.exception("final transition failed", extra={"session_id": session_id})
        self._events.emit(
            session_id=session_id,
            tenant_id=tenant_id,
            kind="destroyed",
            wall_ms=int((time.monotonic() - started) * 1000),
        )


def _new_session_id() -> str:
    return f"s_{secrets.token_hex(12)}"

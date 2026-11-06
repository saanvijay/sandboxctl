from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sandbox_ctl.isolation.creds import CredentialMinter, SessionCredential
from sandbox_ctl.pool.warm_pool import WarmPool
from sandbox_ctl.runtime.agent_client import AgentError, RunResult
from sandbox_ctl.runtime.driver import DriverError, SandboxHandle
from sandbox_ctl.session.manager import RunSubmission, SessionManager
from sandbox_ctl.session.quotas import QuotaConfig, QuotaEnforcer
from sandbox_ctl.session.registry import SessionRegistry
from sandbox_ctl.session.state import SessionPhase
from sandbox_ctl.telemetry.events import EventEmitter
from tests.unit.fakes import FakeAgent, FakeDriver


async def _make_cold_spec(flavor: str, cred: SessionCredential) -> dict[str, Any]:
    return {
        "metadata": {
            "name": f"sandbox-{cred.session_id}",
            "labels": {"sandbox_id": cred.session_id, "flavor_id": flavor},
        }
    }


def _mgr(
    *,
    settings: object,
    driver: FakeDriver,
    agent: FakeAgent,
    signing_key: Path,
    pool: WarmPool | None = None,
    events: EventEmitter | None = None,
) -> SessionManager:
    return SessionManager(
        settings=settings,  # type: ignore[arg-type]
        driver=driver,
        pool=pool or WarmPool(max_idle_s=60),
        agent=agent,
        creds=CredentialMinter(str(signing_key), ttl_s=60),
        quotas=QuotaEnforcer(QuotaConfig(max_concurrent=4, rps=100)),
        registry=SessionRegistry(),
        events=events or EventEmitter(),
        cold_spec_factory=_make_cold_spec,
    )


async def test_happy_path_cold(settings: object, signing_key: Path) -> None:
    driver = FakeDriver()
    agent = FakeAgent(RunResult(exit_code=0, stdout="hi\n", stderr="", duration_ms=12))
    mgr = _mgr(settings=settings, driver=driver, agent=agent, signing_key=signing_key)
    outcome = await mgr.run(
        RunSubmission(
            tenant_id="t",
            flavor_id="python-3.11-ctr",
            code="print(1)",
            language="python",
            timeout_s=5,
        )
    )
    assert outcome.exit_code == 0
    assert outcome.stdout == "hi\n"
    assert len(driver.created) == 1
    assert len(driver.destroyed) == 1


async def test_happy_path_warm(settings: object, signing_key: Path) -> None:
    driver = FakeDriver()
    pool = WarmPool(max_idle_s=60)
    warm_handle = SandboxHandle(
        sandbox_id="warm_1",
        pod_name="sandbox-warm_1",
        namespace="sandbox",
        flavor_id="python-3.11-ctr",
        agent_endpoint="grpc://fake:50051",
    )
    await pool.release(warm_handle)
    agent = FakeAgent(RunResult(exit_code=0, stdout="", stderr="", duration_ms=5))
    mgr = _mgr(settings=settings, driver=driver, agent=agent, signing_key=signing_key, pool=pool)
    outcome = await mgr.run(
        RunSubmission(
            tenant_id="t", flavor_id="python-3.11-ctr", code="x", language="python", timeout_s=5
        )
    )
    assert outcome.exit_code == 0
    # Warm path means no cold create, but there IS a relabel.
    assert len(driver.created) == 0
    assert len(driver.relabels) == 1
    assert driver.relabels[0][1]["pool"] == "ondemand"


async def test_agent_error_marks_failed(settings: object, signing_key: Path) -> None:
    driver = FakeDriver()
    agent = FakeAgent(AgentError("agent exploded"))
    registry = SessionRegistry()
    mgr = SessionManager(
        settings=settings,  # type: ignore[arg-type]
        driver=driver,
        pool=WarmPool(max_idle_s=60),
        agent=agent,
        creds=CredentialMinter(str(signing_key), ttl_s=60),
        quotas=QuotaEnforcer(QuotaConfig(max_concurrent=4, rps=100)),
        registry=registry,
        events=EventEmitter(),
        cold_spec_factory=_make_cold_spec,
    )
    with pytest.raises(AgentError):
        await mgr.run(
            RunSubmission(
                tenant_id="t",
                flavor_id="python-3.11-ctr",
                code="x",
                language="python",
                timeout_s=5,
            )
        )
    # The session is torn down regardless; we assert the destroy happened.
    assert len(driver.destroyed) == 1
    rows = list(await registry.all())
    assert rows[0].phase is SessionPhase.DESTROYED


async def test_driver_create_error(settings: object, signing_key: Path) -> None:
    driver = FakeDriver(create_error=DriverError("quota"))
    agent = FakeAgent(RunResult(exit_code=0, stdout="", stderr="", duration_ms=0))
    mgr = _mgr(settings=settings, driver=driver, agent=agent, signing_key=signing_key)
    with pytest.raises(DriverError):
        await mgr.run(
            RunSubmission(
                tenant_id="t",
                flavor_id="python-3.11-ctr",
                code="x",
                language="python",
                timeout_s=5,
            )
        )
    assert driver.destroyed == []

"""K8s driver — covered via a hand-rolled fake of the CoreV1Api surface."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from typing import Any

import pytest
from kubernetes.client.exceptions import ApiException

from sandbox_ctl.config import Settings
from sandbox_ctl.runtime.driver import DriverError
from sandbox_ctl.runtime.k8s_driver import K8sDriver


class FakeCoreV1:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.deleted: list[str] = []
        self.patches: list[dict[str, Any]] = []
        self.pod_status_sequence: list[Any] = []

    def create_namespaced_pod(self, namespace: str, body: dict[str, Any]) -> None:
        self.created.append(body)

    def delete_namespaced_pod(
        self, name: str, namespace: str, grace_period_seconds: int = 0
    ) -> None:
        self.deleted.append(name)

    def patch_namespaced_pod(self, name: str, namespace: str, patch: dict[str, Any]) -> None:
        self.patches.append(patch)

    def read_namespaced_pod(self, name: str, namespace: str) -> Any:
        return self.pod_status_sequence.pop(0)


def _running_ready(ip: str = "10.0.0.5") -> Any:
    return SimpleNamespace(
        status=SimpleNamespace(
            phase="Running",
            pod_ip=ip,
            conditions=[SimpleNamespace(type="Ready", status="True")],
        )
    )


def _pending() -> Any:
    return SimpleNamespace(status=SimpleNamespace(phase="Pending", pod_ip=None, conditions=[]))


async def test_create_waits_for_ready(settings: Settings) -> None:
    fake = FakeCoreV1()
    fake.pod_status_sequence = [_pending(), _running_ready(), _running_ready()]
    driver = K8sDriver(settings, core_v1=fake)
    spec = {
        "metadata": {
            "name": "sandbox-x",
            "labels": {"sandbox_id": "x"},
        }
    }
    handle = await driver.create(spec, flavor_id="f")
    assert handle.sandbox_id == "x"
    assert "grpc://10.0.0.5" in handle.agent_endpoint


async def test_create_raises_on_api_error(settings: Settings) -> None:
    fake = FakeCoreV1()

    def boom(*_: Any, **__: Any) -> None:
        raise ApiException(reason="Forbidden")

    fake.create_namespaced_pod = boom  # type: ignore[assignment]
    driver = K8sDriver(settings, core_v1=fake)
    with pytest.raises(DriverError, match="Forbidden"):
        await driver.create(
            {"metadata": {"name": "sandbox-x", "labels": {"sandbox_id": "x"}}},
            flavor_id="f",
        )


async def test_destroy_tolerates_missing_pod(settings: Settings) -> None:
    fake = FakeCoreV1()

    def not_found(*_: Any, **__: Any) -> None:
        exc = ApiException(reason="NotFound")
        exc.status = 404
        raise exc

    fake.delete_namespaced_pod = not_found  # type: ignore[assignment]
    driver = K8sDriver(settings, core_v1=fake)
    from sandbox_ctl.runtime.driver import SandboxHandle

    await driver.destroy(
        SandboxHandle(
            sandbox_id="x",
            pod_name="sandbox-x",
            namespace="sandbox",
            flavor_id="f",
            agent_endpoint="",
        )
    )


async def test_wait_times_out(settings: Settings) -> None:
    fake = FakeCoreV1()
    # Return pending forever (test uses a very short wall timeout).
    settings_short = dataclasses.replace(settings, session_max_wall_s=1)
    fake.pod_status_sequence = [_pending()] * 20
    driver = K8sDriver(settings_short, core_v1=fake)
    with pytest.raises(DriverError, match="not Ready"):
        await driver.create(
            {"metadata": {"name": "sandbox-x", "labels": {"sandbox_id": "x"}}},
            flavor_id="f",
        )

"""The driver module exposes a Protocol. Verify a fake satisfies it."""

from __future__ import annotations

from typing import Any

from sandbox_ctl.runtime.driver import Driver, SandboxHandle


class FakeDriver:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.destroyed: list[SandboxHandle] = []

    async def create(self, pod_spec: dict[str, Any], *, flavor_id: str) -> SandboxHandle:
        self.created.append(pod_spec)
        return SandboxHandle(
            sandbox_id=pod_spec["metadata"]["labels"]["sandbox_id"],
            pod_name=pod_spec["metadata"]["name"],
            namespace="sandbox",
            flavor_id=flavor_id,
            agent_endpoint="grpc://fake:50051",
        )

    async def destroy(self, handle: SandboxHandle, *, grace_s: int = 0) -> None:
        self.destroyed.append(handle)

    async def relabel(self, handle: SandboxHandle, labels: dict[str, str]) -> SandboxHandle:
        return handle


def test_fake_satisfies_protocol() -> None:
    fake = FakeDriver()
    assert isinstance(fake, Driver)


async def test_fake_round_trip() -> None:
    fake = FakeDriver()
    spec = {
        "metadata": {
            "name": "sandbox-X",
            "labels": {"sandbox_id": "X"},
        }
    }
    handle = await fake.create(spec, flavor_id="f")
    assert handle.sandbox_id == "X"
    await fake.destroy(handle)
    assert fake.destroyed == [handle]

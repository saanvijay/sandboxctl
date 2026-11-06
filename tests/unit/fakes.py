"""Small fakes used across session-manager tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sandbox_ctl.runtime.agent_client import RunRequest, RunResult
from sandbox_ctl.runtime.driver import SandboxHandle


class FakeDriver:
    def __init__(self, *, create_error: Exception | None = None) -> None:
        self.created: list[dict[str, Any]] = []
        self.destroyed: list[SandboxHandle] = []
        self.relabels: list[tuple[SandboxHandle, dict[str, str]]] = []
        self._create_error = create_error
        self._counter = 0

    async def create(self, pod_spec: dict[str, Any], *, flavor_id: str) -> SandboxHandle:
        if self._create_error is not None:
            raise self._create_error
        self._counter += 1
        self.created.append(pod_spec)
        return SandboxHandle(
            sandbox_id=f"sbx_{self._counter}",
            pod_name=f"sandbox-sbx_{self._counter}",
            namespace="sandbox",
            flavor_id=flavor_id,
            agent_endpoint="grpc://fake:50051",
        )

    async def destroy(self, handle: SandboxHandle, *, grace_s: int = 0) -> None:
        self.destroyed.append(handle)

    async def relabel(self, handle: SandboxHandle, labels: dict[str, str]) -> SandboxHandle:
        self.relabels.append((handle, labels))
        return handle


class FakeAgent:
    def __init__(self, result: RunResult | Exception) -> None:
        self._result = result
        self.calls: list[RunRequest] = []

    async def run(self, endpoint: str, request: RunRequest) -> RunResult:
        self.calls.append(request)
        if isinstance(self._result, Exception):
            raise self._result
        return self._result

    async def stream(self, endpoint: str, request: RunRequest) -> AsyncIterator[bytes]:
        async def gen() -> AsyncIterator[bytes]:
            yield b""

        return gen()

    async def close(self) -> None:
        return None

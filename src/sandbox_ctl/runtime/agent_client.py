"""Client for the in-sandbox agent.

The real protocol is gRPC; its ``.proto`` file is owned by the agent repo.
Here we expose a small typed interface so the Session Manager can mock it
cleanly, and provide a thin ``AsyncAgentClient`` wrapper that calls the
gRPC stub when it is importable. Keeping the surface narrow — ``run``,
``stream``, ``close`` — keeps the dependency on generated code at the edge.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RunRequest:
    code: str
    language: str
    timeout_s: int
    env: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class RunResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int


class AgentError(RuntimeError):
    """Raised when an agent RPC fails or exceeds its timeout."""


@runtime_checkable
class AgentClient(Protocol):
    async def run(self, endpoint: str, request: RunRequest) -> RunResult: ...
    async def stream(self, endpoint: str, request: RunRequest) -> AsyncIterator[bytes]: ...
    async def close(self) -> None: ...


class AsyncAgentClient:
    """Default implementation.

    The real gRPC stub is created lazily; we don't import generated code at
    module import time so the module stays usable in unit tests that don't
    install it.
    """

    def __init__(self, timeout_s: int) -> None:
        self._timeout = timeout_s
        self._stub_factory: object | None = None

    async def run(self, endpoint: str, request: RunRequest) -> RunResult:
        # The generated gRPC code lives in the agent repo and is wired in at
        # runtime. We leave this call site small and typed so the Session
        # Manager unit tests can replace this object wholesale with a fake.
        raise AgentError(
            "AsyncAgentClient.run requires the generated gRPC stubs to be "
            "installed; wire a stub factory in via dependency injection "
            "before calling in production."
        )

    async def stream(self, endpoint: str, request: RunRequest) -> AsyncIterator[bytes]:
        raise AgentError("streaming not configured; inject a stub factory")

    async def close(self) -> None:
        return None

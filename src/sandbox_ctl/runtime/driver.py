"""Abstract runtime driver interface.

A Driver is "the thing that turns a Pod spec into a running sandbox and
hands back a handle to it". Two implementations exist: the real
``K8sDriver`` and a ``FakeDriver`` used in unit tests. The Session Manager
depends only on this interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class SandboxHandle:
    """Identifies a running (or warm) sandbox at the runtime layer."""

    sandbox_id: str
    pod_name: str
    namespace: str
    flavor_id: str
    agent_endpoint: str  # grpc://host:port the control plane uses to reach the in-pod agent.


class DriverError(RuntimeError):
    """Raised when the runtime refuses or fails an operation."""


@runtime_checkable
class Driver(Protocol):
    """Create / observe / destroy sandbox Pods."""

    async def create(self, pod_spec: dict[str, Any], *, flavor_id: str) -> SandboxHandle:
        """Submit a Pod spec and return a handle once the Pod reports Ready.

        Implementations must raise :class:`DriverError` on timeout, scheduling
        failure, or image-pull failure.
        """
        ...

    async def destroy(self, handle: SandboxHandle, *, grace_s: int = 0) -> None:
        """Delete the Pod. Idempotent: a missing Pod is not an error."""
        ...

    async def relabel(self, handle: SandboxHandle, labels: dict[str, str]) -> SandboxHandle:
        """Attach additional labels to the Pod (e.g. real session_id on lease)."""
        ...

"""On-demand CPU/alloc profile from inside a sandbox.

Triggers the in-sandbox agent to run its native profiler for N seconds and
returns the resulting profile bytes. Format is agent-defined (pprof today).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sandbox_ctl.runtime.driver import SandboxHandle


class ProfileKind(str):
    CPU = "cpu"
    ALLOC = "alloc"


@dataclass(frozen=True, slots=True)
class ProfileResult:
    sandbox_id: str
    kind: str
    duration_s: int
    payload: bytes
    media_type: str  # e.g. "application/x-pprof"


# (handle, kind, seconds) -> (payload, media_type)
ProfileFn = Callable[[SandboxHandle, str, int], Awaitable[tuple[bytes, str]]]


class Profiler:
    def __init__(self, profile_fn: ProfileFn) -> None:
        self._profile = profile_fn

    async def capture(
        self, handle: SandboxHandle, *, kind: str = "cpu", seconds: int = 5
    ) -> ProfileResult:
        if seconds <= 0 or seconds > 60:
            raise ValueError("seconds must be in [1, 60]")
        if kind not in {"cpu", "alloc"}:
            raise ValueError(f"unknown profile kind: {kind!r}")
        payload, media_type = await self._profile(handle, kind, seconds)
        return ProfileResult(
            sandbox_id=handle.sandbox_id,
            kind=kind,
            duration_s=seconds,
            payload=payload,
            media_type=media_type,
        )

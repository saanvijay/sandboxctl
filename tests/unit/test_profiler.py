from __future__ import annotations

import pytest

from sandbox_ctl.debug.profiler import Profiler
from sandbox_ctl.runtime.driver import SandboxHandle


async def test_capture_round_trip() -> None:
    async def fake(_handle: SandboxHandle, kind: str, seconds: int) -> tuple[bytes, str]:
        return b"PPROF" + str(seconds).encode(), "application/x-pprof"

    p = Profiler(fake)
    result = await p.capture(
        SandboxHandle(
            sandbox_id="s", pod_name="p", namespace="n", flavor_id="f", agent_endpoint=""
        ),
        kind="cpu",
        seconds=5,
    )
    assert result.payload.startswith(b"PPROF")
    assert result.duration_s == 5
    assert result.media_type == "application/x-pprof"


async def test_rejects_bad_duration() -> None:
    async def fake(*_: object, **__: object) -> tuple[bytes, str]:
        return b"", ""

    p = Profiler(fake)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        await p.capture(
            SandboxHandle(
                sandbox_id="s", pod_name="p", namespace="n", flavor_id="f", agent_endpoint=""
            ),
            seconds=0,
        )


async def test_rejects_bad_kind() -> None:
    async def fake(*_: object, **__: object) -> tuple[bytes, str]:
        return b"", ""

    p = Profiler(fake)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        await p.capture(
            SandboxHandle(
                sandbox_id="s", pod_name="p", namespace="n", flavor_id="f", agent_endpoint=""
            ),
            kind="trace",
        )

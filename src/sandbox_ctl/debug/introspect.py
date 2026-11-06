"""Pull /proc and cgroup snapshots from a live sandbox via the agent.

The agent exposes an RPC that reads a narrow set of files inside the sandbox
and returns their contents. This module normalizes those blobs into typed
structures the on-call playbook can consume.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sandbox_ctl.runtime.driver import SandboxHandle


@dataclass(frozen=True, slots=True)
class CgroupStats:
    cpu_usage_us: int
    memory_current_bytes: int
    memory_peak_bytes: int
    pids_current: int


@dataclass(frozen=True, slots=True)
class ProcSnapshot:
    uptime_s: float
    loadavg_1m: float
    procs_running: int


@dataclass(frozen=True, slots=True)
class LiveSnapshot:
    sandbox_id: str
    cgroup: CgroupStats
    proc: ProcSnapshot


# (handle, path) -> file contents.
ReadFileFn = Callable[[SandboxHandle, str], Awaitable[str]]


class Introspector:
    """Reads a small, documented set of files via an injected reader."""

    def __init__(self, read_file: ReadFileFn) -> None:
        self._read = read_file

    async def snapshot(self, handle: SandboxHandle) -> LiveSnapshot:
        cpu_raw = await self._read(handle, "/sys/fs/cgroup/cpu.stat")
        mem_cur = await self._read(handle, "/sys/fs/cgroup/memory.current")
        mem_peak = await self._read(handle, "/sys/fs/cgroup/memory.peak")
        pids_cur = await self._read(handle, "/sys/fs/cgroup/pids.current")
        uptime = await self._read(handle, "/proc/uptime")
        loadavg = await self._read(handle, "/proc/loadavg")

        return LiveSnapshot(
            sandbox_id=handle.sandbox_id,
            cgroup=CgroupStats(
                cpu_usage_us=_find_int(cpu_raw, "usage_usec"),
                memory_current_bytes=int(mem_cur.strip()),
                memory_peak_bytes=int(mem_peak.strip()),
                pids_current=int(pids_cur.strip()),
            ),
            proc=ProcSnapshot(
                uptime_s=float(uptime.split()[0]),
                loadavg_1m=float(loadavg.split()[0]),
                procs_running=int(loadavg.split()[3].split("/")[0]),
            ),
        )


def _find_int(blob: str, key: str) -> int:
    for line in blob.splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and parts[0] == key:
            return int(parts[1])
    raise ValueError(f"key {key!r} not found in cgroup blob")

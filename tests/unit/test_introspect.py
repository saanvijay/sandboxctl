from __future__ import annotations

from sandbox_ctl.debug.introspect import Introspector
from sandbox_ctl.runtime.driver import SandboxHandle

_FILES = {
    "/sys/fs/cgroup/cpu.stat": "usage_usec 12345\nuser_usec 10000\nsystem_usec 2345\n",
    "/sys/fs/cgroup/memory.current": "123456\n",
    "/sys/fs/cgroup/memory.peak": "789012\n",
    "/sys/fs/cgroup/pids.current": "17\n",
    "/proc/uptime": "100.1 50.2\n",
    "/proc/loadavg": "0.42 0.30 0.20 3/178 42\n",
}


async def test_snapshot_parses_all_fields() -> None:
    async def read(_handle: SandboxHandle, path: str) -> str:
        return _FILES[path]

    probe = Introspector(read)
    snap = await probe.snapshot(
        SandboxHandle(sandbox_id="s", pod_name="p", namespace="n", flavor_id="f", agent_endpoint="")
    )
    assert snap.cgroup.cpu_usage_us == 12345
    assert snap.cgroup.memory_current_bytes == 123456
    assert snap.cgroup.memory_peak_bytes == 789012
    assert snap.cgroup.pids_current == 17
    assert snap.proc.uptime_s == 100.1
    assert snap.proc.loadavg_1m == 0.42
    assert snap.proc.procs_running == 3

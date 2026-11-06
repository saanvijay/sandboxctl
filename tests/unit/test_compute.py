from __future__ import annotations

import pytest

from sandbox_ctl.isolation.compute import ComputeLimits, to_pod_resources, to_security_rlimits


def test_to_pod_resources_shape() -> None:
    limits = ComputeLimits(cpu_millis=500, memory_mb=256, pids_max=128, nofile_max=256)
    out = to_pod_resources(limits)
    assert out == {
        "requests": {"cpu": "500m", "memory": "256Mi"},
        "limits": {"cpu": "500m", "memory": "256Mi"},
    }


def test_rlimits() -> None:
    limits = ComputeLimits(cpu_millis=100, memory_mb=64, pids_max=16, nofile_max=512)
    assert to_security_rlimits(limits) == [{"name": "RLIMIT_NOFILE", "soft": 512, "hard": 512}]


def test_invariants() -> None:
    with pytest.raises(ValueError):
        ComputeLimits(cpu_millis=0, memory_mb=1, pids_max=1)
    with pytest.raises(ValueError):
        ComputeLimits(cpu_millis=1, memory_mb=0, pids_max=1)
    with pytest.raises(ValueError):
        ComputeLimits(cpu_millis=1, memory_mb=1, pids_max=0)

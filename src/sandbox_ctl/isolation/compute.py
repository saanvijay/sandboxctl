"""Compute isolation: produce the cgroup v2 / Pod-resources spec for a session.

Running cgroup commands is the node agent's job (and already Kubernetes'
through resource requests/limits). The control plane's job is to turn the
session's typed limits into the exact K8s ``resources`` block and the
auxiliary caps (pids, nofile) that the Pod spec includes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ComputeLimits:
    """Session-visible compute envelope."""

    cpu_millis: int
    memory_mb: int
    pids_max: int
    nofile_max: int = 1024
    wall_s: int = 300

    def __post_init__(self) -> None:
        if self.cpu_millis <= 0:
            raise ValueError("cpu_millis must be > 0")
        if self.memory_mb <= 0:
            raise ValueError("memory_mb must be > 0")
        if self.pids_max <= 0:
            raise ValueError("pids_max must be > 0")
        if self.wall_s <= 0:
            raise ValueError("wall_s must be > 0")


def to_pod_resources(limits: ComputeLimits) -> dict[str, dict[str, str]]:
    """Render compute limits as the ``spec.containers[].resources`` dict.

    requests == limits so Pods land in the Guaranteed QoS class — the hot
    path for sandbox predictability. Kubernetes handles the actual cgroup
    programming downstream.
    """
    cpu = f"{limits.cpu_millis}m"
    memory = f"{limits.memory_mb}Mi"
    return {
        "requests": {"cpu": cpu, "memory": memory},
        "limits": {"cpu": cpu, "memory": memory},
    }


def to_security_rlimits(limits: ComputeLimits) -> list[dict[str, int | str]]:
    """Render auxiliary rlimits the in-sandbox agent applies.

    Kubernetes does not expose a native rlimit surface, so these flow through
    an env var the agent reads at startup. Kept as a list of dicts so the
    serialization is explicit at the call site.
    """
    return [
        {"name": "RLIMIT_NOFILE", "soft": limits.nofile_max, "hard": limits.nofile_max},
    ]

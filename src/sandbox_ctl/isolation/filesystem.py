"""Filesystem isolation: read-only root, bounded scratch, no host bind mounts.

Produces the ``volumes`` + ``volumeMounts`` fragment for a sandbox Pod.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class FilesystemLayout:
    scratch_mb: int
    code_secret_name: str | None  # Secret containing the submitted code, None for warm Pods.

    def __post_init__(self) -> None:
        if self.scratch_mb <= 0:
            raise ValueError("scratch_mb must be > 0")


def to_pod_volumes_and_mounts(
    layout: FilesystemLayout,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return ``(volumes, volumeMounts)`` for the Pod and its agent container."""
    volumes: list[dict[str, Any]] = [
        {
            "name": "scratch",
            "emptyDir": {"medium": "Memory", "sizeLimit": f"{layout.scratch_mb}Mi"},
        }
    ]
    mounts: list[dict[str, Any]] = [
        {"name": "scratch", "mountPath": "/scratch"},
    ]
    if layout.code_secret_name is not None:
        volumes.append(
            {
                "name": "code",
                "projected": {
                    "sources": [{"secret": {"name": layout.code_secret_name}}],
                },
            }
        )
        mounts.append({"name": "code", "mountPath": "/work", "readOnly": True})
    return volumes, mounts

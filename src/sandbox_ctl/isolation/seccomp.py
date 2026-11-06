"""Seccomp profile selection for sandbox Pods.

The profile itself lives on each node under
``/var/lib/kubelet/seccomp/<POD_SECCOMP_PROFILE>``; the control plane only
emits the ``seccompProfile`` block that points at it. We also expose a
helper to list the small set of profiles callers may select; new entries go
in ``deploy/seccomp/`` and in the enum here together.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class SeccompProfile(str, Enum):
    DEFAULT = "default"
    STRICT = "strict"


_PROFILE_FILES = {
    SeccompProfile.DEFAULT: "sandbox/default.json",
    SeccompProfile.STRICT: "sandbox/strict.json",
}


def to_pod_seccomp(profile: SeccompProfile | None, configured_default: str) -> dict[str, Any]:
    """Return the ``spec.securityContext.seccompProfile`` block.

    If ``profile`` is ``None`` we fall back to the operator-configured default
    (``POD_SECCOMP_PROFILE``); passing an explicit value overrides it.
    """
    localhost_profile = _PROFILE_FILES[profile] if profile is not None else configured_default
    return {
        "type": "Localhost",
        "localhostProfile": localhost_profile,
    }

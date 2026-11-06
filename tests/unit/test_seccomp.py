from __future__ import annotations

from sandbox_ctl.isolation.seccomp import SeccompProfile, to_pod_seccomp


def test_explicit_profile_wins() -> None:
    out = to_pod_seccomp(SeccompProfile.STRICT, "sandbox/default.json")
    assert out == {"type": "Localhost", "localhostProfile": "sandbox/strict.json"}


def test_fallback_to_default() -> None:
    out = to_pod_seccomp(None, "sandbox/custom.json")
    assert out == {"type": "Localhost", "localhostProfile": "sandbox/custom.json"}

"""Isolation-posture checks that live at the Pod-spec layer.

These validate the invariants DESIGN.md §8 and §14.3 pin down:
seccomp localhost profile, read-only root, drop all caps, no SA token,
default-deny network (via NetworkPolicy — not Pod-spec-local, so we assert
the shape and route the NetworkPolicy check through a helm chart lint in
CI). The Pod spec is what the control plane produces, so if a regression
here lands, the next sandbox created loses isolation.
"""

from __future__ import annotations

import pytest

from sandbox_ctl.config import Settings
from sandbox_ctl.isolation.compute import ComputeLimits
from sandbox_ctl.isolation.filesystem import FilesystemLayout
from sandbox_ctl.isolation.seccomp import SeccompProfile
from sandbox_ctl.runtime.pod_spec import PodBuildInputs, build_pod_spec

pytestmark = pytest.mark.e2e


def _inputs() -> PodBuildInputs:
    return PodBuildInputs(
        sandbox_id="sbx",
        tenant_id="t",
        session_id="s",
        flavor_id="python-3.11-ctr",
        image="img@sha256:abc",
        compute=ComputeLimits(cpu_millis=500, memory_mb=256, pids_max=128, wall_s=60),
        filesystem=FilesystemLayout(scratch_mb=128, code_secret_name="run-s-code"),
        seccomp=SeccompProfile.DEFAULT,
        runtime_class="runc-hardened",
        priority_class="sandbox-ondemand",
        cred_secret_name="run-s-cred",
    )


def test_pod_has_seccomp_localhost(settings: Settings) -> None:
    pod = build_pod_spec(_inputs(), settings)
    assert pod["spec"]["securityContext"]["seccompProfile"]["type"] == "Localhost"


def test_root_filesystem_is_readonly(settings: Settings) -> None:
    pod = build_pod_spec(_inputs(), settings)
    container = pod["spec"]["containers"][0]
    assert container["securityContext"]["readOnlyRootFilesystem"] is True


def test_all_caps_dropped(settings: Settings) -> None:
    pod = build_pod_spec(_inputs(), settings)
    container = pod["spec"]["containers"][0]
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]


def test_service_account_token_not_mounted(settings: Settings) -> None:
    pod = build_pod_spec(_inputs(), settings)
    assert pod["spec"]["automountServiceAccountToken"] is False


def test_wall_time_bounded(settings: Settings) -> None:
    pod = build_pod_spec(_inputs(), settings)
    assert pod["spec"]["activeDeadlineSeconds"] == 60


def test_runs_as_non_root(settings: Settings) -> None:
    pod = build_pod_spec(_inputs(), settings)
    assert pod["spec"]["securityContext"]["runAsNonRoot"] is True


def test_restart_policy_never(settings: Settings) -> None:
    pod = build_pod_spec(_inputs(), settings)
    assert pod["spec"]["restartPolicy"] == "Never"

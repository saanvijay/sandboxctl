from __future__ import annotations

import pytest

from sandbox_ctl.config import Settings
from sandbox_ctl.isolation.compute import ComputeLimits
from sandbox_ctl.isolation.filesystem import FilesystemLayout
from sandbox_ctl.isolation.seccomp import SeccompProfile
from sandbox_ctl.runtime.pod_spec import PodBuildInputs, build_pod_spec


def _inputs(session_id: str = "s_abc") -> PodBuildInputs:
    return PodBuildInputs(
        sandbox_id="sbx_1",
        tenant_id="t",
        session_id=session_id,
        flavor_id="python-3.11-ctr",
        image="registry.local/sandbox:python-3.11@sha256:deadbeef",
        compute=ComputeLimits(cpu_millis=500, memory_mb=256, pids_max=128, wall_s=120),
        filesystem=FilesystemLayout(scratch_mb=128, code_secret_name="run-s_abc-code"),
        seccomp=SeccompProfile.DEFAULT,
        runtime_class="runc-hardened",
        priority_class="sandbox-ondemand",
        cred_secret_name="run-s_abc-cred",
    )


def test_pod_spec_core_shape(settings: Settings) -> None:
    pod = build_pod_spec(_inputs(), settings)
    assert pod["kind"] == "Pod"
    meta = pod["metadata"]
    assert meta["name"] == "sandbox-sbx_1"
    assert meta["labels"]["app"] == "sandbox"
    assert meta["labels"]["pool"] == "ondemand"

    spec = pod["spec"]
    assert spec["runtimeClassName"] == "runc-hardened"
    assert spec["automountServiceAccountToken"] is False
    assert spec["activeDeadlineSeconds"] == 120
    assert spec["securityContext"]["runAsNonRoot"] is True
    assert spec["securityContext"]["seccompProfile"]["type"] == "Localhost"

    container = spec["containers"][0]
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert container["resources"]["limits"]["cpu"] == "500m"


def test_warm_pod_has_no_session_id(settings: Settings) -> None:
    inputs = _inputs(session_id="")
    pod = build_pod_spec(inputs, settings)
    assert pod["metadata"]["labels"]["session_id"] == ""
    assert pod["metadata"]["labels"]["pool"] == "warm"


def test_cred_secret_wired_into_env(settings: Settings) -> None:
    pod = build_pod_spec(_inputs(), settings)
    env = pod["spec"]["containers"][0]["env"]
    cred_env = next(e for e in env if e["name"] == "SESSION_CREDENTIAL")
    assert cred_env["valueFrom"]["secretKeyRef"]["name"] == "run-s_abc-cred"


def test_image_pull_secret_passed_through(settings: Settings) -> None:
    pod = build_pod_spec(_inputs(), settings)
    assert pod["spec"]["imagePullSecrets"] == [{"name": settings.sandbox_image_pull_secret}]


def test_bad_node_selector_raises(settings: Settings) -> None:
    import dataclasses

    bad = dataclasses.replace(settings, sandbox_node_selector="role")
    with pytest.raises(ValueError):
        build_pod_spec(_inputs(), bad)

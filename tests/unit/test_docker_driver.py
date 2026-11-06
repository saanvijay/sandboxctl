"""Unit tests for the Docker driver.

A ``FakeRunner`` records every invocation and returns a scripted
``CommandResult``; the driver never reaches the real Docker daemon.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import pytest

from sandbox_ctl.config import Settings
from sandbox_ctl.runtime.docker_driver import (
    CommandResult,
    DockerDriver,
    _cpu_to_docker,
    _memory_to_docker,
)
from sandbox_ctl.runtime.driver import DriverError, SandboxHandle


class FakeRunner:
    def __init__(self, results: list[CommandResult]) -> None:
        self._results: Iterator[CommandResult] = iter(results)
        self.calls: list[list[str]] = []

    async def __call__(self, argv: list[str]) -> CommandResult:
        self.calls.append(argv)
        try:
            return next(self._results)
        except StopIteration as exc:
            raise AssertionError("FakeRunner called more times than scripted") from exc


def _ok() -> CommandResult:
    return CommandResult(returncode=0, stdout="cid\n", stderr="")


def _pod_spec() -> dict[str, Any]:
    return {
        "metadata": {
            "name": "sandbox-abc",
            "labels": {"sandbox_id": "abc", "tenant_id": "t1", "flavor_id": "py"},
        },
        "spec": {
            "containers": [
                {
                    "name": "agent",
                    "image": "python:3.11-slim",
                    "securityContext": {"readOnlyRootFilesystem": True},
                    "resources": {"limits": {"cpu": "500m", "memory": "512Mi"}},
                    "env": [
                        {"name": "SESSION_ID", "value": "s-1"},
                        {
                            "name": "SESSION_CREDENTIAL",
                            "valueFrom": {"secretKeyRef": {"name": "x", "key": "token"}},
                        },
                    ],
                    "volumeMounts": [{"name": "scratch", "mountPath": "/scratch"}],
                }
            ],
            "volumes": [
                {"name": "scratch", "emptyDir": {"medium": "Memory", "sizeLimit": "128Mi"}}
            ],
        },
    }


async def test_create_builds_expected_argv(settings: Settings) -> None:
    runner = FakeRunner([_ok()])
    driver = DockerDriver(settings, runner=runner)

    handle = await driver.create(_pod_spec(), flavor_id="py")

    assert handle.sandbox_id == "abc"
    assert handle.pod_name == "sandbox-abc"
    assert handle.namespace == "docker"
    assert handle.agent_endpoint == "docker-exec://sandbox-abc"

    argv = runner.calls[0]
    assert argv[:5] == ["docker", "run", "-d", "--name", "sandbox-abc"]
    # Security hardening is always applied.
    assert "--cap-drop" in argv and "ALL" in argv
    assert "no-new-privileges" in argv
    assert "--read-only" in argv
    # Resource translation.
    cpus_idx = argv.index("--cpus")
    assert argv[cpus_idx + 1] == "0.5"
    mem_idx = argv.index("--memory")
    assert argv[mem_idx + 1] == "512m"
    # Plain env is forwarded; secret-backed env is dropped.
    assert "SESSION_ID=s-1" in argv
    assert not any("SESSION_CREDENTIAL" in a for a in argv)
    # Memory-backed scratch is translated to a tmpfs mount.
    tmpfs_idx = argv.index("--tmpfs")
    assert argv[tmpfs_idx + 1].startswith("/scratch:rw,nosuid,noexec,nodev,size=128m")


async def test_create_adds_network_when_configured(settings: Settings) -> None:
    runner = FakeRunner([_ok()])
    s = replace(settings, docker_network="sandbox-net")
    driver = DockerDriver(s, runner=runner)

    await driver.create(_pod_spec(), flavor_id="py")

    argv = runner.calls[0]
    net_idx = argv.index("--network")
    assert argv[net_idx + 1] == "sandbox-net"


async def test_create_raises_driver_error_on_failure(settings: Settings) -> None:
    runner = FakeRunner([CommandResult(returncode=125, stdout="", stderr="image not found")])
    driver = DockerDriver(settings, runner=runner)

    with pytest.raises(DriverError, match="image not found"):
        await driver.create(_pod_spec(), flavor_id="py")


async def test_destroy_runs_docker_rm(settings: Settings) -> None:
    runner = FakeRunner([_ok()])
    driver = DockerDriver(settings, runner=runner)
    handle = SandboxHandle(
        sandbox_id="abc",
        pod_name="sandbox-abc",
        namespace="docker",
        flavor_id="py",
        agent_endpoint="docker-exec://sandbox-abc",
    )

    await driver.destroy(handle)

    assert runner.calls[0] == ["docker", "rm", "-f", "sandbox-abc"]


async def test_destroy_tolerates_missing_container(settings: Settings) -> None:
    runner = FakeRunner(
        [
            CommandResult(
                returncode=1,
                stdout="",
                stderr="Error: No such container: sandbox-abc",
            )
        ]
    )
    driver = DockerDriver(settings, runner=runner)
    handle = SandboxHandle(
        sandbox_id="abc",
        pod_name="sandbox-abc",
        namespace="docker",
        flavor_id="py",
        agent_endpoint="docker-exec://sandbox-abc",
    )

    await driver.destroy(handle)  # Does not raise.


async def test_destroy_raises_on_other_errors(settings: Settings) -> None:
    runner = FakeRunner([CommandResult(returncode=1, stdout="", stderr="permission denied")])
    driver = DockerDriver(settings, runner=runner)
    handle = SandboxHandle(
        sandbox_id="abc",
        pod_name="sandbox-abc",
        namespace="docker",
        flavor_id="py",
        agent_endpoint="docker-exec://sandbox-abc",
    )

    with pytest.raises(DriverError, match="permission denied"):
        await driver.destroy(handle)


async def test_relabel_tracks_labels_in_memory(settings: Settings) -> None:
    runner = FakeRunner([_ok()])
    driver = DockerDriver(settings, runner=runner)
    handle = await driver.create(_pod_spec(), flavor_id="py")

    returned = await driver.relabel(handle, {"session_id": "s-99", "pool": "ondemand"})

    assert returned is handle
    labels = driver.labels_of(handle.pod_name)
    assert labels["session_id"] == "s-99"
    assert labels["pool"] == "ondemand"
    # Previously-attached labels remain.
    assert labels["sandbox_id"] == "abc"


def test_cpu_translation() -> None:
    assert _cpu_to_docker("500m") == "0.5"
    assert _cpu_to_docker("2") == "2"
    assert _cpu_to_docker("1500m") == "1.5"


def test_memory_translation() -> None:
    assert _memory_to_docker("512Mi") == "512m"
    assert _memory_to_docker("1Gi") == "1g"
    assert _memory_to_docker("64Ki") == "64k"
    assert _memory_to_docker("256") == "256"

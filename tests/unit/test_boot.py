"""Unit tests for :mod:`sandbox_ctl.runtime.boot`.

The selector must return the right driver/agent pair for a given
``RUNTIME_BACKEND``, and must reject unknown values.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from sandbox_ctl.config import Settings
from sandbox_ctl.runtime.agent_client import AsyncAgentClient
from sandbox_ctl.runtime.boot import BackendError, build_agent, build_driver
from sandbox_ctl.runtime.docker_agent import DockerExecAgent
from sandbox_ctl.runtime.docker_driver import DockerDriver


def test_docker_backend_builds_docker_driver_and_agent(settings: Settings) -> None:
    s = replace(settings, runtime_backend="docker")

    driver = build_driver(s)
    agent = build_agent(s)

    assert isinstance(driver, DockerDriver)
    assert isinstance(agent, DockerExecAgent)


def test_kubernetes_backend_builds_async_agent(settings: Settings) -> None:
    # We only check the agent side here; building a real K8sDriver tries to
    # load a kubeconfig and is covered by the K8s driver tests directly.
    s = replace(settings, runtime_backend="kubernetes")

    agent = build_agent(s)

    assert isinstance(agent, AsyncAgentClient)


def test_unknown_backend_raises(settings: Settings) -> None:
    s = replace(settings, runtime_backend="firecracker-remote")

    with pytest.raises(BackendError, match="firecracker-remote"):
        build_driver(s)
    with pytest.raises(BackendError, match="firecracker-remote"):
        build_agent(s)

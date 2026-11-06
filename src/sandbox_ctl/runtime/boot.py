"""Select the runtime driver and agent client for the configured backend.

Two backends sit behind the same :class:`Driver` / :class:`AgentClient`
interfaces:

- ``kubernetes`` (production): :class:`K8sDriver` + :class:`AsyncAgentClient`.
- ``docker`` (local development): :class:`DockerDriver` + :class:`DockerExecAgent`.

Everything upstream of this module is backend-agnostic. New backends plug
in here, not in the Session Manager.
"""

from __future__ import annotations

import logging

from sandbox_ctl.config import Settings
from sandbox_ctl.runtime.agent_client import AgentClient, AsyncAgentClient
from sandbox_ctl.runtime.docker_agent import DockerExecAgent
from sandbox_ctl.runtime.docker_driver import DockerDriver
from sandbox_ctl.runtime.driver import Driver
from sandbox_ctl.runtime.k8s_driver import K8sDriver

logger = logging.getLogger(__name__)


class BackendError(RuntimeError):
    """Raised when ``RUNTIME_BACKEND`` names a backend we do not implement."""


def build_driver(settings: Settings) -> Driver:
    backend = settings.runtime_backend
    if backend == "kubernetes":
        return K8sDriver(settings)
    if backend == "docker":
        return DockerDriver(settings)
    raise BackendError(f"unknown RUNTIME_BACKEND: {backend!r}")


def build_agent(settings: Settings) -> AgentClient:
    backend = settings.runtime_backend
    if backend == "kubernetes":
        return AsyncAgentClient(timeout_s=settings.agent_timeout_s)
    if backend == "docker":
        return DockerExecAgent()
    raise BackendError(f"unknown RUNTIME_BACKEND: {backend!r}")

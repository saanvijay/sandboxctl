"""Docker implementation of :class:`Driver` for local development.

Translates a Kubernetes-shaped Pod spec into ``docker run`` arguments and
tracks the resulting container. Prod uses :class:`K8sDriver`; this driver
lets developers run the full control plane on a laptop with only Docker.

Isolation is weaker than production (no microVM, shared host kernel). The
backend is gated by ``RUNTIME_BACKEND=docker`` — dev clusters never run
real tenant workloads. See DESIGN.md §15.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sandbox_ctl.config import Settings
from sandbox_ctl.runtime.driver import Driver, DriverError, SandboxHandle

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[list[str]], Awaitable[CommandResult]]


async def _default_runner(argv: list[str]) -> CommandResult:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return CommandResult(
        returncode=proc.returncode or 0,
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
    )


_KEEPALIVE_CMD = ["sh", "-c", "trap 'exit 0' TERM; while :; do sleep 3600 & wait $!; done"]


class DockerDriver(Driver):
    """Create / destroy sandbox containers via the local Docker daemon."""

    def __init__(self, settings: Settings, *, runner: CommandRunner | None = None) -> None:
        self._settings = settings
        self._runner: CommandRunner = runner or _default_runner
        # Docker does not support label updates on a running container. The
        # control plane cares about labels for routing and metrics, so we
        # track them in memory and expose them via :meth:`labels_of`.
        self._labels: dict[str, dict[str, str]] = {}

    async def create(self, pod_spec: dict[str, Any], *, flavor_id: str) -> SandboxHandle:
        name = pod_spec["metadata"]["name"]
        labels = dict(pod_spec["metadata"].get("labels", {}))
        sandbox_id = labels["sandbox_id"]
        container_spec = pod_spec["spec"]["containers"][0]
        image = container_spec["image"]

        argv: list[str] = ["docker", "run", "-d", "--name", name]
        for k, v in labels.items():
            argv += ["--label", f"{k}={v}"]
        argv += self._security_args(container_spec)
        argv += self._resource_args(container_spec)
        argv += self._env_args(container_spec)
        argv += self._volume_args(pod_spec["spec"], container_spec)
        if self._settings.docker_network:
            argv += ["--network", self._settings.docker_network]
        argv += [image, *_KEEPALIVE_CMD]

        result = await self._runner(argv)
        if result.returncode != 0:
            raise DriverError(
                f"docker run failed: {result.stderr.strip() or result.stdout.strip()}"
            )
        self._labels[name] = labels

        return SandboxHandle(
            sandbox_id=sandbox_id,
            pod_name=name,
            namespace="docker",
            flavor_id=flavor_id,
            agent_endpoint=f"docker-exec://{name}",
        )

    async def destroy(self, handle: SandboxHandle, *, grace_s: int = 0) -> None:
        argv = ["docker", "rm", "-f", handle.pod_name]
        result = await self._runner(argv)
        if result.returncode != 0:
            text = (result.stderr or result.stdout).strip()
            if "No such container" in text:
                logger.info("destroy: container already gone", extra={"name": handle.pod_name})
                self._labels.pop(handle.pod_name, None)
                return
            raise DriverError(f"docker rm failed: {text}")
        self._labels.pop(handle.pod_name, None)

    async def relabel(self, handle: SandboxHandle, labels: dict[str, str]) -> SandboxHandle:
        current = self._labels.setdefault(handle.pod_name, {})
        current.update(labels)
        return handle

    def labels_of(self, pod_name: str) -> dict[str, str]:
        return dict(self._labels.get(pod_name, {}))

    @staticmethod
    def _security_args(c: dict[str, Any]) -> list[str]:
        args = [
            "--security-opt",
            "no-new-privileges",
            "--cap-drop",
            "ALL",
        ]
        sec = c.get("securityContext") or {}
        if sec.get("readOnlyRootFilesystem"):
            args.append("--read-only")
        return args

    @staticmethod
    def _resource_args(c: dict[str, Any]) -> list[str]:
        args: list[str] = []
        limits = (c.get("resources") or {}).get("limits") or {}
        if "cpu" in limits:
            args += ["--cpus", _cpu_to_docker(str(limits["cpu"]))]
        if "memory" in limits:
            args += ["--memory", _memory_to_docker(str(limits["memory"]))]
        return args

    @staticmethod
    def _env_args(c: dict[str, Any]) -> list[str]:
        args: list[str] = []
        for entry in c.get("env") or []:
            # Secret-backed env entries (``valueFrom``) are resolved by K8s in
            # prod; locally we skip them. Plain-valued entries pass through.
            if "value" in entry and entry.get("name"):
                args += ["-e", f"{entry['name']}={entry['value']}"]
        return args

    @staticmethod
    def _volume_args(spec: dict[str, Any], c: dict[str, Any]) -> list[str]:
        args: list[str] = []
        volumes = {v["name"]: v for v in spec.get("volumes") or []}
        for mount in c.get("volumeMounts") or []:
            vol = volumes.get(mount["name"])
            if vol is None:
                continue
            empty = vol.get("emptyDir") or {}
            if empty.get("medium") == "Memory":
                size = empty.get("sizeLimit", "64Mi")
                args += [
                    "--tmpfs",
                    f"{mount['mountPath']}:rw,nosuid,noexec,nodev,size={_memory_to_docker(size)}",
                ]
        return args


def _cpu_to_docker(spec: str) -> str:
    """Convert K8s CPU quantity (e.g. ``'500m'``) to Docker's ``--cpus`` value."""
    if spec.endswith("m"):
        return f"{int(spec[:-1]) / 1000.0:g}"
    return spec


def _memory_to_docker(spec: str) -> str:
    """Convert K8s memory quantity (e.g. ``'512Mi'``) to Docker's format."""
    if spec.endswith("Mi"):
        return f"{spec[:-2]}m"
    if spec.endswith("Gi"):
        return f"{spec[:-2]}g"
    if spec.endswith("Ki"):
        return f"{spec[:-2]}k"
    return spec

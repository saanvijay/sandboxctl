"""Agent client that execs into sandbox Pods via the Kubernetes API.

Production uses an in-sandbox gRPC agent (:class:`AsyncAgentClient`). For
local minikube / dev-cluster work we instead exec straight into the Pod
using the Kubernetes exec stream API, mirroring :class:`DockerExecAgent`.
No gRPC stubs required; isolation is whatever the Pod spec and
NetworkPolicy give us.

Endpoint shape produced by :class:`K8sDriver` for this path:

    kube-exec://<namespace>/<pod-name>
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from kubernetes.stream import stream

from sandbox_ctl.config import Settings
from sandbox_ctl.runtime.agent_client import AgentError, RunRequest, RunResult

logger = logging.getLogger(__name__)

_KUBE_EXEC_SCHEME = "kube-exec://"

# Language → (code file extension, interpreter binary available in the image).
_LANGUAGE_RUNNERS: dict[str, tuple[str, str]] = {
    "python": ("py", "python3"),
    "python3": ("py", "python3"),
    "bash": ("sh", "bash"),
    "sh": ("sh", "sh"),
    "node": ("js", "node"),
    "javascript": ("js", "node"),
}

_EXIT_MARKER = "__SANDBOX_EXIT__"


class KubeExecAgent:
    """Execute code inside a sandbox Pod via the K8s exec stream."""

    def __init__(self, settings: Settings, *, core_v1: Any | None = None) -> None:
        self._settings = settings
        if core_v1 is None:
            self._load_kubeconfig()
            self._core = k8s_client.CoreV1Api()
        else:
            self._core = core_v1

    def _load_kubeconfig(self) -> None:
        if self._settings.kube_in_cluster:
            k8s_config.load_incluster_config()
        else:
            path = self._settings.kube_kubeconfig_path or None
            k8s_config.load_kube_config(config_file=path)

    async def run(self, endpoint: str, request: RunRequest) -> RunResult:
        namespace, pod = _parse_endpoint(endpoint)
        if request.language not in _LANGUAGE_RUNNERS:
            raise AgentError(f"unsupported language for kube-exec runtime: {request.language!r}")
        ext, interpreter = _LANGUAGE_RUNNERS[request.language]
        remote_path = f"/scratch/code.{ext}"

        try:
            await asyncio.to_thread(self._stage_code, namespace, pod, remote_path, request.code)
        except AgentError:
            raise
        except Exception as exc:
            raise AgentError(f"failed to stage code: {exc}") from exc

        start = time.monotonic()
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(self._exec_code, namespace, pod, interpreter, remote_path),
                timeout=request.timeout_s,
            )
        except TimeoutError as exc:
            raise AgentError(f"execution exceeded timeout {request.timeout_s}s") from exc
        duration_ms = int((time.monotonic() - start) * 1000)
        return RunResult(
            exit_code=result["exit_code"],
            stdout=result["stdout"],
            stderr=result["stderr"],
            duration_ms=duration_ms,
        )

    async def stream(self, endpoint: str, request: RunRequest) -> AsyncIterator[bytes]:
        raise AgentError("streaming not supported by KubeExecAgent")

    async def close(self) -> None:
        return None

    def _stage_code(self, namespace: str, pod: str, remote_path: str, code: str) -> None:
        resp = stream(
            self._core.connect_get_namespaced_pod_exec,
            pod,
            namespace,
            command=["sh", "-c", f"cat > {remote_path}"],
            stderr=True,
            stdin=True,
            stdout=True,
            tty=False,
            _preload_content=False,
        )
        try:
            resp.write_stdin(code)
            # Signal EOF so the `cat` on the Pod side exits.
            resp.update(timeout=1)
            resp.close()
        finally:
            if resp.is_open():
                resp.close()

    def _exec_code(
        self, namespace: str, pod: str, interpreter: str, remote_path: str
    ) -> dict[str, Any]:
        # Wrap in a shell so we can surface the interpreter's exit code — the
        # websocket stream doesn't carry it as reliably as a stdout sentinel.
        wrapped = f"{interpreter} {remote_path}; " f"printf '\\n{_EXIT_MARKER}%d\\n' $?"
        resp = stream(
            self._core.connect_get_namespaced_pod_exec,
            pod,
            namespace,
            command=["sh", "-c", wrapped],
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
            _preload_content=False,
        )
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        try:
            while resp.is_open():
                resp.update(timeout=1)
                if resp.peek_stdout():
                    stdout_parts.append(resp.read_stdout())
                if resp.peek_stderr():
                    stderr_parts.append(resp.read_stderr())
            # Drain anything buffered after the stream closed.
            if resp.peek_stdout():
                stdout_parts.append(resp.read_stdout())
            if resp.peek_stderr():
                stderr_parts.append(resp.read_stderr())
        finally:
            resp.close()

        stdout = "".join(stdout_parts)
        stderr = "".join(stderr_parts)
        exit_code, stdout = _split_exit_marker(stdout)
        return {"exit_code": exit_code, "stdout": stdout, "stderr": stderr}


def _parse_endpoint(endpoint: str) -> tuple[str, str]:
    if not endpoint.startswith(_KUBE_EXEC_SCHEME):
        raise AgentError(f"not a kube-exec endpoint: {endpoint!r}")
    rest = endpoint[len(_KUBE_EXEC_SCHEME) :]
    ns, _, pod = rest.partition("/")
    if not ns or not pod:
        raise AgentError(f"malformed kube-exec endpoint: {endpoint!r}")
    return ns, pod


def _split_exit_marker(stdout: str) -> tuple[int, str]:
    """Extract the interpreter's exit code from the trailing marker line."""
    idx = stdout.rfind(_EXIT_MARKER)
    if idx == -1:
        return 0, stdout
    tail = stdout[idx + len(_EXIT_MARKER) :].strip()
    try:
        exit_code = int(tail.splitlines()[0]) if tail else 0
    except (ValueError, IndexError):
        exit_code = 0
    cleaned = stdout[:idx].rstrip("\n")
    if cleaned and not cleaned.endswith("\n"):
        cleaned += "\n"
    return exit_code, cleaned

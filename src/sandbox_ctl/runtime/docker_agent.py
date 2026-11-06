"""Agent client for the Docker local runtime.

In production the agent is a Rust/Go gRPC server baked into the sandbox
image and reached by :class:`AsyncAgentClient`. In local Docker mode the
"agent" is simply ``docker exec``: the submitted code is staged into the
container's in-memory scratch directory and executed with the
language-appropriate interpreter.

Isolation is whatever Docker and the locked-down container spec give us —
not microVM-grade. See DESIGN.md §15.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable

from sandbox_ctl.runtime.agent_client import AgentError, RunRequest, RunResult
from sandbox_ctl.runtime.docker_driver import CommandResult

logger = logging.getLogger(__name__)


CommandRunnerWithInput = Callable[[list[str], bytes | None], Awaitable[CommandResult]]


async def _default_runner(argv: list[str], stdin: bytes | None) -> CommandResult:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE if stdin is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(input=stdin)
    return CommandResult(
        returncode=proc.returncode or 0,
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
    )


# Language → (code file extension, interpreter binary available in the image).
_LANGUAGE_RUNNERS: dict[str, tuple[str, str]] = {
    "python": ("py", "python3"),
    "python3": ("py", "python3"),
    "bash": ("sh", "bash"),
    "sh": ("sh", "sh"),
    "node": ("js", "node"),
    "javascript": ("js", "node"),
}

_DOCKER_EXEC_SCHEME = "docker-exec://"


class DockerExecAgent:
    """Execute code inside a local sandbox container via ``docker exec``."""

    def __init__(self, *, runner: CommandRunnerWithInput | None = None) -> None:
        self._runner: CommandRunnerWithInput = runner or _default_runner

    async def run(self, endpoint: str, request: RunRequest) -> RunResult:
        container = _parse_endpoint(endpoint)
        if request.language not in _LANGUAGE_RUNNERS:
            raise AgentError(f"unsupported language for docker runtime: {request.language!r}")
        ext, interpreter = _LANGUAGE_RUNNERS[request.language]
        remote_path = f"/scratch/code.{ext}"

        write_argv = ["docker", "exec", "-i", container, "sh", "-c", f"cat > {remote_path}"]
        write = await self._runner(write_argv, request.code.encode("utf-8"))
        if write.returncode != 0:
            raise AgentError(f"failed to stage code: {write.stderr.strip()}")

        exec_argv = ["docker", "exec", container, interpreter, remote_path]
        start = time.monotonic()
        try:
            result = await asyncio.wait_for(
                self._runner(exec_argv, None), timeout=request.timeout_s
            )
        except TimeoutError as exc:
            raise AgentError(f"execution exceeded timeout {request.timeout_s}s") from exc
        duration_ms = int((time.monotonic() - start) * 1000)

        return RunResult(
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_ms=duration_ms,
        )

    async def stream(self, endpoint: str, request: RunRequest) -> AsyncIterator[bytes]:
        raise AgentError("streaming not supported by DockerExecAgent")

    async def close(self) -> None:
        return None


def _parse_endpoint(endpoint: str) -> str:
    if not endpoint.startswith(_DOCKER_EXEC_SCHEME):
        raise AgentError(f"not a docker-exec endpoint: {endpoint!r}")
    return endpoint[len(_DOCKER_EXEC_SCHEME) :]

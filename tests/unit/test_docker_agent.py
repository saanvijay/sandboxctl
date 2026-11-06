"""Unit tests for :class:`DockerExecAgent`.

The runner is a fake that records every ``docker exec`` invocation and
hands back a scripted ``CommandResult``; nothing hits the real daemon.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest

from sandbox_ctl.runtime.agent_client import AgentError, RunRequest
from sandbox_ctl.runtime.docker_agent import DockerExecAgent
from sandbox_ctl.runtime.docker_driver import CommandResult


class FakeRunner:
    def __init__(self, results: list[CommandResult]) -> None:
        self._results: Iterator[CommandResult] = iter(results)
        self.calls: list[tuple[list[str], bytes | None]] = []

    async def __call__(self, argv: list[str], stdin: bytes | None) -> CommandResult:
        self.calls.append((argv, stdin))
        try:
            return next(self._results)
        except StopIteration as exc:
            raise AssertionError("FakeRunner called more times than scripted") from exc


async def test_run_stages_code_then_executes() -> None:
    runner = FakeRunner(
        [
            CommandResult(returncode=0, stdout="", stderr=""),
            CommandResult(returncode=0, stdout="hello\n", stderr=""),
        ]
    )
    agent = DockerExecAgent(runner=runner)

    result = await agent.run(
        "docker-exec://sandbox-abc",
        RunRequest(code="print('hello')", language="python", timeout_s=5),
    )

    assert result.exit_code == 0
    assert result.stdout == "hello\n"
    assert result.duration_ms >= 0

    write_argv, stdin = runner.calls[0]
    assert write_argv[:4] == ["docker", "exec", "-i", "sandbox-abc"]
    assert write_argv[-1].startswith("cat > /scratch/code.py")
    assert stdin == b"print('hello')"

    exec_argv, _ = runner.calls[1]
    assert exec_argv == ["docker", "exec", "sandbox-abc", "python3", "/scratch/code.py"]


async def test_run_rejects_unknown_endpoint_scheme() -> None:
    agent = DockerExecAgent(runner=FakeRunner([]))

    with pytest.raises(AgentError, match="not a docker-exec endpoint"):
        await agent.run(
            "grpc://10.0.0.1:50051",
            RunRequest(code="print(1)", language="python", timeout_s=5),
        )


async def test_run_rejects_unknown_language() -> None:
    agent = DockerExecAgent(runner=FakeRunner([]))

    with pytest.raises(AgentError, match="unsupported language"):
        await agent.run(
            "docker-exec://sandbox-abc",
            RunRequest(code="print(1)", language="brainfuck", timeout_s=5),
        )


async def test_run_surfaces_stage_failure() -> None:
    runner = FakeRunner([CommandResult(returncode=1, stdout="", stderr="no such container")])
    agent = DockerExecAgent(runner=runner)

    with pytest.raises(AgentError, match="failed to stage code"):
        await agent.run(
            "docker-exec://sandbox-abc",
            RunRequest(code="print(1)", language="python", timeout_s=5),
        )


async def test_run_times_out() -> None:
    async def slow_runner(argv: list[str], stdin: bytes | None) -> CommandResult:
        if argv[:3] == ["docker", "exec"] and "-i" in argv:
            return CommandResult(returncode=0, stdout="", stderr="")
        await asyncio.sleep(10)
        return CommandResult(returncode=0, stdout="", stderr="")

    agent = DockerExecAgent(runner=slow_runner)

    with pytest.raises(AgentError, match="exceeded timeout"):
        await agent.run(
            "docker-exec://sandbox-abc",
            RunRequest(code="print(1)", language="python", timeout_s=1),
        )

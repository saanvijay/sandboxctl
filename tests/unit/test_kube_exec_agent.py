"""Tests for KubeExecAgent — covers the parts that don't need a real cluster.

The streaming API that `kubernetes.stream.stream` opens is hard to fake
without a websocket server, so the full exec round-trip is exercised by
the e2e suite against a real minikube. Here we cover endpoint parsing,
language validation, and the exit-marker extraction.
"""

from __future__ import annotations

import pytest

from sandbox_ctl.runtime.agent_client import AgentError, RunRequest
from sandbox_ctl.runtime.kube_exec_agent import (
    KubeExecAgent,
    _parse_endpoint,
    _split_exit_marker,
)


def test_parse_endpoint_happy_path() -> None:
    assert _parse_endpoint("kube-exec://sandbox/sandbox-abc123") == ("sandbox", "sandbox-abc123")


@pytest.mark.parametrize(
    "bad",
    [
        "grpc://host:50051",
        "kube-exec://",
        "kube-exec:///pod-only",
        "kube-exec://ns-only/",
    ],
)
def test_parse_endpoint_rejects_malformed(bad: str) -> None:
    with pytest.raises(AgentError):
        _parse_endpoint(bad)


def test_split_exit_marker_extracts_zero_and_strips_marker() -> None:
    raw = "hello\n__SANDBOX_EXIT__0\n"
    code, stdout = _split_exit_marker(raw)
    assert code == 0
    assert stdout == "hello\n"


def test_split_exit_marker_extracts_nonzero() -> None:
    raw = "oops\n__SANDBOX_EXIT__2\n"
    code, stdout = _split_exit_marker(raw)
    assert code == 2
    assert stdout == "oops\n"


def test_split_exit_marker_tolerates_no_marker() -> None:
    raw = "just output"
    code, stdout = _split_exit_marker(raw)
    assert code == 0
    assert stdout == "just output"


def test_split_exit_marker_tolerates_garbage_payload() -> None:
    raw = "x\n__SANDBOX_EXIT__abc\n"
    code, stdout = _split_exit_marker(raw)
    assert code == 0
    assert stdout == "x\n"


@pytest.mark.asyncio()
async def test_run_rejects_unknown_language() -> None:
    # core_v1 is never touched because language validation runs first.
    agent = KubeExecAgent.__new__(KubeExecAgent)
    agent._core = None  # type: ignore[attr-defined]
    with pytest.raises(AgentError, match="unsupported language"):
        await agent.run(
            "kube-exec://ns/pod",
            RunRequest(code="x", language="ruby", timeout_s=5),
        )

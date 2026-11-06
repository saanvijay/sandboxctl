from __future__ import annotations

import pytest

from sandbox_ctl.runtime.agent_client import AgentError, AsyncAgentClient, RunRequest


async def test_default_run_requires_wiring() -> None:
    client = AsyncAgentClient(timeout_s=5)
    with pytest.raises(AgentError, match="stubs"):
        await client.run(
            "grpc://unused:50051",
            RunRequest(code="x", language="python", timeout_s=5),
        )

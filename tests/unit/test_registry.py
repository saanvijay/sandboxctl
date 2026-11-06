from __future__ import annotations

import pytest

from sandbox_ctl.session.registry import SessionNotFound, SessionRegistry
from sandbox_ctl.session.state import SessionPhase, SessionState


async def test_put_get_update() -> None:
    r = SessionRegistry()
    s = SessionState(session_id="s", tenant_id="t", flavor_id="f")
    await r.put(s)
    assert (await r.get("s")).phase is SessionPhase.PENDING
    updated = await r.update("s", SessionPhase.ACQUIRED, sandbox_id="x")
    assert updated.phase is SessionPhase.ACQUIRED
    assert updated.sandbox_id == "x"


async def test_missing_raises() -> None:
    r = SessionRegistry()
    with pytest.raises(SessionNotFound):
        await r.get("missing")


async def test_all_snapshot() -> None:
    r = SessionRegistry()
    await r.put(SessionState(session_id="a", tenant_id="t", flavor_id="f"))
    await r.put(SessionState(session_id="b", tenant_id="t", flavor_id="f"))
    rows = await r.all()
    assert {s.session_id for s in rows} == {"a", "b"}

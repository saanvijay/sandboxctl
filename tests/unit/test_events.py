from __future__ import annotations

from sandbox_ctl.telemetry.events import EventEmitter


def test_emit_and_fetch_by_session() -> None:
    bus = EventEmitter()
    bus.emit(session_id="s1", tenant_id="t", kind="submitted")
    bus.emit(session_id="s2", tenant_id="t", kind="submitted")
    bus.emit(session_id="s1", tenant_id="t", kind="completed", exit_code=0)
    rows = bus.events_for("s1")
    assert [r.kind for r in rows] == ["submitted", "completed"]
    assert rows[1].detail == {"exit_code": 0}


def test_emit_bounded() -> None:
    bus = EventEmitter()
    for i in range(20):
        bus.emit(session_id=f"s{i}", tenant_id="t", kind="submitted")
    assert len(list(bus.all())) == 20

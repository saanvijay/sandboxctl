from __future__ import annotations

import time

from sandbox_ctl.debug.timeline import build_timeline, render_text
from sandbox_ctl.telemetry.events import EventEmitter


def test_timeline_in_order_and_offsets() -> None:
    bus = EventEmitter()
    bus.emit(session_id="s", tenant_id="t", kind="submitted")
    time.sleep(0.001)
    bus.emit(session_id="s", tenant_id="t", kind="completed", exit_code=0)
    timeline = build_timeline(bus, "s")
    assert [r.kind for r in timeline.rows] == ["submitted", "completed"]
    assert timeline.rows[0].offset_ms == 0
    assert timeline.rows[1].offset_ms >= 0


def test_timeline_missing_session() -> None:
    bus = EventEmitter()
    timeline = build_timeline(bus, "ghost")
    assert timeline.rows == ()
    assert "no events" in render_text(timeline)

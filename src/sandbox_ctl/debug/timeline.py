"""Build a human-readable timeline for a session from its lifecycle events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sandbox_ctl.telemetry.events import EventEmitter, LifecycleEvent


@dataclass(frozen=True, slots=True)
class TimelineRow:
    ts: datetime
    offset_ms: int
    kind: str
    detail: dict[str, object]


@dataclass(frozen=True, slots=True)
class Timeline:
    session_id: str
    rows: tuple[TimelineRow, ...]


def build_timeline(events: EventEmitter, session_id: str) -> Timeline:
    found = events.events_for(session_id)
    if not found:
        return Timeline(session_id=session_id, rows=())
    start = min(e.ts for e in found)
    rows = tuple(
        TimelineRow(
            ts=e.ts,
            offset_ms=int((e.ts - start).total_seconds() * 1000),
            kind=e.kind,
            detail=dict(e.detail),
        )
        for e in sorted(found, key=lambda e: e.ts)
    )
    return Timeline(session_id=session_id, rows=rows)


def render_text(timeline: Timeline) -> str:
    if not timeline.rows:
        return f"session {timeline.session_id}: no events"
    lines = [f"session {timeline.session_id}:"]
    for row in timeline.rows:
        detail = " ".join(f"{k}={v}" for k, v in row.detail.items()) if row.detail else ""
        lines.append(f"  +{row.offset_ms:>6d}ms  {row.kind:<16}  {detail}")
    return "\n".join(lines)


__all__ = ["Timeline", "TimelineRow", "build_timeline", "render_text", "LifecycleEvent"]

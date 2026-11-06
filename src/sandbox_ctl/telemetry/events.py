"""Lifecycle event emitter.

Lifecycle events are *facts* about a session (acquired, isolated, running,
destroyed) consumed by both logs and (in prod) an audit sink. The emitter is
a simple append-only in-memory buffer plus a log line so callers can rely on
one call site rather than scattering log statements.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

_MAX_RETAINED_EVENTS: int = 10_000


@dataclass(frozen=True, slots=True)
class LifecycleEvent:
    ts: datetime
    session_id: str
    tenant_id: str
    kind: str
    detail: dict[str, Any] = field(default_factory=dict)


class EventEmitter:
    """Thread-safe lifecycle event sink.

    In production this would fan out to an audit log or Kafka topic. In-memory
    retention is bounded by ``_MAX_RETAINED_EVENTS`` so the sink is safe to
    leave on in long-running processes.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buf: deque[LifecycleEvent] = deque(maxlen=_MAX_RETAINED_EVENTS)

    def emit(
        self,
        *,
        session_id: str,
        tenant_id: str,
        kind: str,
        **detail: Any,
    ) -> LifecycleEvent:
        event = LifecycleEvent(
            ts=datetime.now(tz=UTC),
            session_id=session_id,
            tenant_id=tenant_id,
            kind=kind,
            detail=detail,
        )
        with self._lock:
            self._buf.append(event)
        logger.info(
            "lifecycle",
            extra={
                "session_id": session_id,
                "tenant_id": tenant_id,
                "kind": kind,
                **detail,
            },
        )
        return event

    def events_for(self, session_id: str) -> list[LifecycleEvent]:
        with self._lock:
            return [e for e in self._buf if e.session_id == session_id]

    def all(self) -> Iterable[LifecycleEvent]:
        with self._lock:
            return list(self._buf)

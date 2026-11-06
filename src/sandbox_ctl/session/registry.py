"""In-memory session registry.

Single source of truth for live session state within a control-plane replica.
Thread-safe via asyncio.Lock. Persisted state (durable restart) lives in a
separate store and is out of scope here.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any

from sandbox_ctl.session.state import SessionPhase, SessionState


class SessionNotFound(KeyError):
    """Raised when ``get`` or ``update`` is called with an unknown id."""


class SessionRegistry:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._store: dict[str, SessionState] = {}

    async def put(self, state: SessionState) -> None:
        async with self._lock:
            self._store[state.session_id] = state

    async def get(self, session_id: str) -> SessionState:
        async with self._lock:
            state = self._store.get(session_id)
            if state is None:
                raise SessionNotFound(session_id)
            return state

    async def update(self, session_id: str, to: SessionPhase, **changes: Any) -> SessionState:
        async with self._lock:
            current = self._store.get(session_id)
            if current is None:
                raise SessionNotFound(session_id)
            new = current.transition(to, **changes)
            self._store[session_id] = new
            return new

    async def all(self) -> Iterable[SessionState]:
        async with self._lock:
            return list(self._store.values())

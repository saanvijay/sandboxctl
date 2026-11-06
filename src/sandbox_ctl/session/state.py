"""Session state dataclass and legal transitions."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import Enum


class SessionPhase(str, Enum):
    PENDING = "pending"
    ACQUIRED = "acquired"
    ISOLATED = "isolated"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    DESTROYED = "destroyed"


_LEGAL_TRANSITIONS: dict[SessionPhase, frozenset[SessionPhase]] = {
    SessionPhase.PENDING: frozenset({SessionPhase.ACQUIRED, SessionPhase.FAILED}),
    SessionPhase.ACQUIRED: frozenset(
        {SessionPhase.ISOLATED, SessionPhase.FAILED, SessionPhase.DESTROYED}
    ),
    SessionPhase.ISOLATED: frozenset(
        {SessionPhase.RUNNING, SessionPhase.FAILED, SessionPhase.DESTROYED}
    ),
    SessionPhase.RUNNING: frozenset(
        {SessionPhase.COMPLETED, SessionPhase.FAILED, SessionPhase.DESTROYED}
    ),
    SessionPhase.COMPLETED: frozenset({SessionPhase.DESTROYED}),
    SessionPhase.FAILED: frozenset({SessionPhase.DESTROYED}),
    SessionPhase.DESTROYED: frozenset(),
}


class IllegalTransition(RuntimeError):
    """Raised when a caller attempts a phase transition that is not legal."""


@dataclass(frozen=True, slots=True)
class SessionState:
    session_id: str
    tenant_id: str
    flavor_id: str
    phase: SessionPhase = SessionPhase.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    sandbox_id: str | None = None
    pod_name: str | None = None
    cred_id: str | None = None
    exit_code: int | None = None
    error: str | None = None

    def transition(self, to: SessionPhase, **changes: object) -> SessionState:
        if to not in _LEGAL_TRANSITIONS[self.phase]:
            raise IllegalTransition(f"{self.phase.value} -> {to.value} is not permitted")
        return replace(self, phase=to, **changes)  # type: ignore[arg-type]


def is_terminal(phase: SessionPhase) -> bool:
    return phase in {SessionPhase.COMPLETED, SessionPhase.FAILED, SessionPhase.DESTROYED}

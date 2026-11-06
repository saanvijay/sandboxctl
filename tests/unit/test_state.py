from __future__ import annotations

import pytest

from sandbox_ctl.session.state import IllegalTransition, SessionPhase, SessionState, is_terminal


def _s() -> SessionState:
    return SessionState(session_id="s", tenant_id="t", flavor_id="f")


def test_legal_transition() -> None:
    s = _s()
    s2 = s.transition(SessionPhase.ACQUIRED, sandbox_id="x")
    assert s2.phase is SessionPhase.ACQUIRED
    assert s2.sandbox_id == "x"


def test_illegal_transition_rejected() -> None:
    s = _s()
    with pytest.raises(IllegalTransition):
        s.transition(SessionPhase.COMPLETED)


def test_full_happy_path() -> None:
    s = _s()
    for phase in (
        SessionPhase.ACQUIRED,
        SessionPhase.ISOLATED,
        SessionPhase.RUNNING,
        SessionPhase.COMPLETED,
        SessionPhase.DESTROYED,
    ):
        s = s.transition(phase)
    assert is_terminal(s.phase)

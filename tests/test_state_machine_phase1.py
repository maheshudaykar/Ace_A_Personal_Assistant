"""Phase 1 tests for ace.ace_kernel.state_machine."""

from __future__ import annotations

import pytest

from ace.ace_kernel.state_machine import State, StateMachine


def test_valid_transition() -> None:
    machine = StateMachine()
    machine.transition(State.IDLE)

    assert machine.state == State.IDLE


def test_invalid_transition_raises() -> None:
    machine = StateMachine()

    with pytest.raises(ValueError):
        machine.transition(State.EXECUTING)


def test_guard_blocks_transition() -> None:
    machine = StateMachine()
    machine.register_guard(State.BOOT, State.IDLE, guard=lambda: False)

    with pytest.raises(ValueError):
        machine.transition(State.IDLE)

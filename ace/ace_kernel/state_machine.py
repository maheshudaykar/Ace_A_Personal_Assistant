"""Deterministic state machine with guard validation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, Optional


class State(Enum):
    BOOT = "BOOT"
    IDLE = "IDLE"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    REFLECTING = "REFLECTING"
    RECOVERING = "RECOVERING"


Guard = Callable[[], bool]


@dataclass(frozen=True)
class Transition:
    """Transition definition."""

    source: State
    target: State
    guard: Optional[Guard] = None


class StateMachine:
    """Deterministic state machine with guarded transitions."""

    _allowed: Dict[State, set[State]] = {
        State.BOOT: {State.IDLE},
        State.IDLE: {State.PLANNING},
        State.PLANNING: {State.EXECUTING, State.RECOVERING},
        State.EXECUTING: {State.REFLECTING, State.RECOVERING},
        State.REFLECTING: {State.IDLE, State.RECOVERING},
        State.RECOVERING: {State.IDLE},
    }

    def __init__(self, initial: State = State.BOOT) -> None:
        self._state = initial
        self._guards: Dict[tuple[State, State], Guard] = {}

    @property
    def state(self) -> State:
        return self._state

    def register_guard(self, source: State, target: State, guard: Guard) -> None:
        """Register a guard for a transition."""
        self._guards[(source, target)] = guard

    def transition(self, target: State) -> None:
        """Transition to a target state if allowed and guard passes."""
        if target not in self._allowed.get(self._state, set()):
            raise ValueError(f"Invalid transition: {self._state.value} -> {target.value}")
        guard = self._guards.get((self._state, target))
        if guard is not None and not guard():
            raise ValueError(f"Guard blocked transition: {self._state.value} -> {target.value}")
        self._state = target

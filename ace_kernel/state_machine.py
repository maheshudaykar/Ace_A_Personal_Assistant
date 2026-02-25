"""Simple state machine for ACE Phase 0 - BOOT -> IDLE -> EXECUTING -> IDLE"""

from enum import Enum
from typing import Callable, Optional
from datetime import datetime
import logging

logger = logging.getLogger("ACE.StateMachine")


class ACEState(Enum):
    """Phase 0 simple state machine - 4 states only"""
    BOOT = "BOOT"
    IDLE = "IDLE"
    EXECUTING = "EXECUTING"
    SHUTDOWN = "SHUTDOWN"


class StateMachine:
    """
    Simple state machine for ACE Phase 0.
    
    Transitions:
    - BOOT -> IDLE (on startup)
    - IDLE -> EXECUTING (when task received)
    - EXECUTING -> IDLE (on task completion)
    - Any state -> SHUTDOWN (on termination)
    """
    
    def __init__(self):
        self.current_state = ACEState.BOOT
        self.previous_state: Optional[ACEState] = None
        self.state_history: list[tuple[ACEState, datetime]] = []
        self.transition_callbacks: dict[tuple[ACEState, ACEState], list[Callable[[], None]]] = {}
        self._log_state_change(ACEState.BOOT, "Initialization")
    
    def register_callback(self, from_state: ACEState, to_state: ACEState, callback: Callable[[], None]) -> None:
        """Register callback for specific state transition."""
        key = (from_state, to_state)
        if key not in self.transition_callbacks:
            self.transition_callbacks[key] = []
        self.transition_callbacks[key].append(callback)
    
    def transition(self, new_state: ACEState, reason: str = ""):
        """
        Transition to new state.
        
        Args:
            new_state: Target state
            reason: Human-readable reason for transition
        
        Raises:
            ValueError: If transition is invalid
        """
        # Validate transition
        if not self._is_valid_transition(self.current_state, new_state):
            raise ValueError(
                f"Invalid transition: {self.current_state.value} -> {new_state.value}"
            )
        
        # Execute callbacks
        key = (self.current_state, new_state)
        if key in self.transition_callbacks:
            for callback in self.transition_callbacks[key]:
                try:
                    callback()
                except Exception as e:
                    logger.error(f"Error in transition callback: {e}")
        
        # Update state
        self.previous_state = self.current_state
        self.current_state = new_state
        self._log_state_change(new_state, reason)
    
    def _is_valid_transition(self, from_state: ACEState, to_state: ACEState) -> bool:
        """Check if transition is valid."""
        valid_transitions: dict[ACEState, list[ACEState]] = {
            ACEState.BOOT: [ACEState.IDLE],
            ACEState.IDLE: [ACEState.EXECUTING, ACEState.SHUTDOWN],
            ACEState.EXECUTING: [ACEState.IDLE, ACEState.SHUTDOWN],
            ACEState.SHUTDOWN: [],
        }
        return to_state in valid_transitions.get(from_state, [])
    
    def _log_state_change(self, new_state: ACEState, reason: str) -> None:
        """Log state change."""
        self.state_history.append((new_state, datetime.now()))
        logger.info(f"State transition -> {new_state.value} ({reason})")
    
    @property
    def state(self) -> ACEState:
        """Get current state."""
        return self.current_state
    
    @property
    def state_name(self) -> str:
        """Get current state name."""
        return self.current_state.value
    
    def reset(self):
        """Reset state machine to BOOT."""
        self.current_state = ACEState.BOOT
        self.previous_state = None
        self.state_history = [(ACEState.BOOT, datetime.now())]
        logger.info("State machine reset to BOOT")

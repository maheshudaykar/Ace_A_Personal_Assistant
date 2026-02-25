"""Unit tests for ace_kernel.state_machine module."""

import pytest  # type: ignore[import-not-found]
from ace_kernel.state_machine import StateMachine, ACEState


class TestACEState:
    """Test ACEState enum."""
    
    def test_ace_state_values(self):
        """Test ACEState enum has correct values."""
        assert ACEState.BOOT.value == "BOOT"
        assert ACEState.IDLE.value == "IDLE"
        assert ACEState.EXECUTING.value == "EXECUTING"
        assert ACEState.SHUTDOWN.value == "SHUTDOWN"


class TestStateMachine:
    """Test StateMachine class."""
    
    def test_initial_state(self):
        """Test initial state is BOOT."""
        sm = StateMachine()
        assert sm.current_state == ACEState.BOOT
    
    def test_valid_transition_boot_to_idle(self):
        """Test valid transition BOOT->IDLE."""
        sm = StateMachine()
        sm.transition(ACEState.IDLE)
        assert sm.current_state == ACEState.IDLE
    
    def test_valid_transition_idle_to_executing(self):
        """Test valid transition IDLE->EXECUTING."""
        sm = StateMachine()
        sm.transition(ACEState.IDLE)
        sm.transition(ACEState.EXECUTING)
        assert sm.current_state == ACEState.EXECUTING
    
    def test_valid_transition_executing_to_idle(self):
        """Test valid transition EXECUTING->IDLE."""
        sm = StateMachine()
        sm.transition(ACEState.IDLE)
        sm.transition(ACEState.EXECUTING)
        sm.transition(ACEState.IDLE)
        assert sm.current_state == ACEState.IDLE
    
    def test_valid_transition_to_shutdown(self):
        """Test valid transitions to SHUTDOWN."""
        # From IDLE
        sm = StateMachine()
        sm.transition(ACEState.IDLE)
        sm.transition(ACEState.SHUTDOWN)
        assert sm.current_state == ACEState.SHUTDOWN
        
        # From EXECUTING
        sm2 = StateMachine()
        sm2.transition(ACEState.IDLE)
        sm2.transition(ACEState.EXECUTING)
        sm2.transition(ACEState.SHUTDOWN)
        assert sm2.current_state == ACEState.SHUTDOWN
    
    def test_invalid_transition_boot_to_executing(self):
        """Test invalid transition BOOT->EXECUTING."""
        sm = StateMachine()
        with pytest.raises(ValueError, match="Invalid transition"):  # type: ignore[attr-defined]
            sm.transition(ACEState.EXECUTING)
    
    def test_invalid_transition_boot_to_shutdown(self):
        """Test invalid transition BOOT->SHUTDOWN."""
        sm = StateMachine()
        with pytest.raises(ValueError, match="Invalid transition"):  # type: ignore[attr-defined]
            sm.transition(ACEState.SHUTDOWN)
    
    def test_invalid_transition_from_shutdown(self):
        """Test invalid transition from SHUTDOWN."""
        sm = StateMachine()
        sm.transition(ACEState.IDLE)
        sm.transition(ACEState.SHUTDOWN)
        with pytest.raises(ValueError, match="Invalid transition"):  # type: ignore[attr-defined]
            sm.transition(ACEState.IDLE)
    
    def test_state_history(self):
        """Test state history tracking."""
        sm = StateMachine()
        assert len(sm.state_history) == 1  # BOOT is initial state
        assert sm.state_history[0][0] == ACEState.BOOT
        
        sm.transition(ACEState.IDLE)
        assert len(sm.state_history) == 2
        assert sm.state_history[1][0] == ACEState.IDLE
    
    def test_callback_registration(self):
        """Test callback registration."""
        sm = StateMachine()
        callback_called: list[bool] = []
        
        def test_callback() -> None:
            callback_called.append(True)
        
        sm.register_callback(ACEState.BOOT, ACEState.IDLE, test_callback)
        sm.transition(ACEState.IDLE)
        
        assert len(callback_called) == 1
    
    def test_callback_not_called_for_unregistered_transition(self):
        """Test callback not called for unregistered transitions."""
        sm = StateMachine()
        callback_called: list[bool] = []
        
        def test_callback() -> None:
            callback_called.append(True)
        
        sm.register_callback(ACEState.BOOT, ACEState.IDLE, test_callback)
        sm.transition(ACEState.IDLE)
        sm.transition(ACEState.EXECUTING)
        
        assert len(callback_called) == 1  # Only BOOT->IDLE
    
    def test_multiple_callbacks(self):
        """Test multiple callbacks on same transition."""
        sm = StateMachine()
        calls: list[str] = []
        
        def callback1() -> None:
            calls.append("cb1")
        
        def callback2() -> None:
            calls.append("cb2")
        
        sm.register_callback(ACEState.BOOT, ACEState.IDLE, callback1)
        sm.register_callback(ACEState.BOOT, ACEState.IDLE, callback2)
        sm.transition(ACEState.IDLE)
        
        assert "cb1" in calls
        assert "cb2" in calls
    
    def test_state_history_contains_timestamps(self):
        """Test state history contains timestamps."""
        sm = StateMachine()
        sm.transition(ACEState.IDLE)
        
        for entry in sm.state_history:
            assert entry[0] is not None  # state
            assert entry[1] is not None  # timestamp

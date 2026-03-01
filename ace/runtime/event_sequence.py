"""Global event sequence for deterministic total ordering of concurrent events."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


class GlobalEventSequence:
    """Thread-safe monotonic counter ensuring total ordering of determinism-critical events."""
    
    _instance: 'GlobalEventSequence | None' = None
    _init_lock = threading.Lock()
    
    def __new__(cls):
        """Enforce singleton pattern."""
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._counter = 0
                    instance._counter_lock = threading.Lock()
                    cls._instance = instance
        return cls._instance
    
    @classmethod
    def get_instance(cls):
        """Get singleton instance."""
        if cls._instance is None:
            return cls()
        return cls._instance
    
    def next(self) -> int:
        """Atomically increment and return next sequence ID."""
        with self._counter_lock:
            self._counter += 1
            return self._counter
    
    def current(self) -> int:
        """Get current counter value without incrementing (for testing)."""
        with self._counter_lock:
            return self._counter
    
    def reset(self) -> None:
        """Reset counter to 0 (testing only)."""
        with self._counter_lock:
            self._counter = 0
    
    def __repr__(self) -> str:
        return f"GlobalEventSequence(counter={self.current()})"

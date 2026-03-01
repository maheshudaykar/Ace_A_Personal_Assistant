"""Agent context — per-agent state for Phase 3A multi-agent runtime.

AgentContext is a mutable state container owned by AgentScheduler.
It tracks quota, circuit-breaker state, and scheduling counters for one agent.

Circuit-breaker states (Gate 2.4 governs transitions):
    CLOSED     — normal operation; tasks dispatched freely.
    OPEN       — circuit tripped; new tasks go to dead-letter queue.
    HALF_OPEN  — retry window elapsed; one trial task is allowed.

The scheduler (Gate 2.3) reads circuit_state before dispatch.
The circuit breaker (Gate 2.4) writes circuit_state transitions.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


# Circuit-breaker state constants
CIRCUIT_CLOSED = "CLOSED"
CIRCUIT_OPEN = "OPEN"
CIRCUIT_HALF_OPEN = "HALF_OPEN"

# Permanent-failure threshold: agent is dead-lettered after this many failures in a row
PERMANENT_FAILURE_THRESHOLD = 10


@dataclass
class AgentContext:
    """Per-agent state: quotas, scheduling counters, circuit-breaker state.

    Fields are mutable; AgentScheduler updates them under _queue_lock.
    """

    # Identity and priority
    agent_id: str
    priority: int                       # 0-10 scale; higher = dispatched sooner

    # Resource quotas enforced by the caller before memory mutations
    memory_quota_entries: int           # max episodic entries this agent may record per task
    cpu_quota_ms: int                   # soft CPU budget per dispatch (ms)
    execution_timeout_ms: int           # hard wall-clock timeout per dispatch (ms)

    # Scheduling state (managed by AgentScheduler)
    consecutive_execution_count: int = 0   # consecutive dispatches *without another agent running*
    failure_count: int = 0                 # consecutive failures since last success
    total_tasks_dispatched: int = 0
    total_tasks_succeeded: int = 0
    total_tasks_failed: int = 0

    # Circuit-breaker state (transitions governed by Gate 2.4 CircuitBreaker)
    circuit_state: str = CIRCUIT_CLOSED
    last_failure_time: float = field(default_factory=time.monotonic)
    retry_window_seconds: float = 300.0    # 5 minutes default

    def is_dispatchable(self) -> bool:
        """Return True if this agent may receive a new task right now."""
        if self.circuit_state == CIRCUIT_CLOSED:
            return True
        if self.circuit_state == CIRCUIT_HALF_OPEN:
            return True  # one trial task allowed (Gate 2.4 enforces this)
        # OPEN: check if retry window has elapsed
        if self.circuit_state == CIRCUIT_OPEN:
            elapsed = time.monotonic() - self.last_failure_time
            return elapsed >= self.retry_window_seconds
        return False

    def effective_priority(self, max_consecutive: int) -> int:
        """Compute scheduling priority with starvation-prevention cap.

        If this agent has run max_consecutive times in a row, its effective
        priority drops to -1 (below any legitimate priority level) so that
        lower-priority agents get a turn.  Once another agent runs, the
        scheduler resets consecutive_execution_count to 0.
        """
        if self.consecutive_execution_count >= max_consecutive:
            return -1
        return self.priority

    def record_success(self) -> None:
        """Update counters after a successful dispatch."""
        self.consecutive_execution_count += 1
        self.failure_count = 0
        self.total_tasks_dispatched += 1
        self.total_tasks_succeeded += 1

    def record_failure(self) -> None:
        """Update counters after a failed dispatch."""
        self.failure_count += 1
        self.consecutive_execution_count = 0  # failure breaks the consecutive run
        self.total_tasks_dispatched += 1
        self.total_tasks_failed += 1
        self.last_failure_time = time.monotonic()

    def reset_consecutive(self) -> None:
        """Reset consecutive counter (called when a *different* agent runs)."""
        self.consecutive_execution_count = 0

    def is_permanently_failed(self) -> bool:
        """True if agent has failed too many times to be retried."""
        return self.failure_count >= PERMANENT_FAILURE_THRESHOLD

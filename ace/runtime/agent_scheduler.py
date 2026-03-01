"""Agent scheduler — deterministic priority-queue dispatcher for Phase 3A.

Scheduling discipline (KAOS-inspired, no randomness):
    1. Priority DESC         — higher-numbered priority agents go first.
    2. Consecutive ASC       — among equal priority, prefer agents that have
                               run fewer consecutive times (starvation prevention).
    3. Agent ID ASC          — deterministic tie-break.

Starvation prevention:
    After MAX_CONSECUTIVE_EXECUTIONS_PER_AGENT dispatches without another agent
    running, an agent's effective_priority drops to -1.  The next lowest-priority
    agent with consecutive_count=0 goes first.  After that agent runs, the
    starved agent's consecutive counter is reset.

Circuit breaker (Gate 2.4 provides full transitions; here we read state):
    - OPEN agents are rejected to dead-letter queue.
    - HALF_OPEN agents are allowed one trial dispatch.

Lock discipline:
    - _queue_lock is completely independent of all memory-layer locks.
    - _queue_lock is released BEFORE calling the task callable.
    - No I/O, no memory operations, no logging inside _queue_lock.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ace.runtime.agent_context import (
    CIRCUIT_HALF_OPEN,
    CIRCUIT_OPEN,
    AgentContext,
)
from ace.runtime import runtime_config


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class AgentTask:
    """A unit of work submitted to the scheduler."""
    agent_id: str
    task_id: str
    fn: Callable[[], Any]
    submitted_at: float = field(default_factory=time.monotonic)


@dataclass
class DispatchResult:
    """Result of a single dispatch cycle."""
    task_id: str
    agent_id: str
    success: bool
    return_value: Any
    error: Optional[str]
    duration_ms: float


@dataclass
class SchedulerStatus:
    """Current scheduler state snapshot."""
    queue_depth: int
    dead_letter_depth: int
    registered_agents: int
    total_dispatched: int
    total_succeeded: int
    total_failed: int
    total_dead_lettered: int


# ---------------------------------------------------------------------------
# AgentScheduler
# ---------------------------------------------------------------------------

class AgentScheduler:
    """Deterministic priority-queue dispatcher with starvation prevention.

    Usage:
        scheduler = AgentScheduler()
        scheduler.register_agent(ctx)
        scheduler.submit_task(agent_id, task_id, fn)
        result = scheduler.dispatch_next()
    """

    def __init__(self) -> None:
        self._agents: Dict[str, AgentContext] = {}
        self._queue: List[AgentTask] = []          # ordered by _sort_key
        self._dead_letter: List[AgentTask] = []    # permanent failures (memory-only)
        self._queue_lock = threading.Lock()        # independent domain; never nested

        # Global counters
        self._total_dispatched: int = 0
        self._total_succeeded: int = 0
        self._total_failed: int = 0
        self._total_dead_lettered: int = 0

        # Track last dispatched agent for consecutive-reset logic
        self._last_dispatched_agent_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_agent(self, ctx: AgentContext) -> None:
        """Register an agent context.  Idempotent: overwrites if already registered."""
        with self._queue_lock:
            self._agents[ctx.agent_id] = ctx

    def unregister_agent(self, agent_id: str) -> None:
        """Remove an agent.  Any pending tasks for this agent are dead-lettered."""
        with self._queue_lock:
            self._agents.pop(agent_id, None)
            pending = [t for t in self._queue if t.agent_id == agent_id]
            self._queue = [t for t in self._queue if t.agent_id != agent_id]
            self._dead_letter.extend(pending)
            self._total_dead_lettered += len(pending)

    def get_agent(self, agent_id: str) -> Optional[AgentContext]:
        """Return a copy of the agent context (read-only snapshot)."""
        with self._queue_lock:
            ctx = self._agents.get(agent_id)
            if ctx is None:
                return None
            # Return a shallow copy to avoid external mutation
            import copy
            return copy.copy(ctx)

    # ------------------------------------------------------------------
    # Task submission
    # ------------------------------------------------------------------

    def submit_task(self, agent_id: str, task_id: str, fn: Callable[[], Any]) -> bool:
        """Submit a task for the given agent.

        Returns True if accepted into the queue, False if rejected (agent not
        registered, circuit OPEN and retry window not elapsed, or permanent failure).

        The queue is maintained in sorted order; insertion cost is O(n) where n
        is bounded by the number of registered agents * tasks per agent.
        """
        with self._queue_lock:
            ctx = self._agents.get(agent_id)
            if ctx is None:
                return False

            # Permanent failure: dead-letter immediately
            if ctx.is_permanently_failed():
                task = AgentTask(agent_id=agent_id, task_id=task_id, fn=fn)
                self._dead_letter.append(task)
                self._total_dead_lettered += 1
                return False

            # Circuit breaker gate (Gate 2.4 handles full transitions)
            if not ctx.is_dispatchable():
                task = AgentTask(agent_id=agent_id, task_id=task_id, fn=fn)
                self._dead_letter.append(task)
                self._total_dead_lettered += 1
                return False

            # Accept into queue
            task = AgentTask(agent_id=agent_id, task_id=task_id, fn=fn)
            self._queue.append(task)
            self._queue.sort(key=self._sort_key)
            return True

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def dispatch_next(self) -> Optional[DispatchResult]:
        """Dispatch the highest-priority ready task.

        Returns DispatchResult on success or failure, None if queue is empty.

        The callable is invoked OUTSIDE _queue_lock to avoid holding the lock
        during user code execution.
        """
        with self._queue_lock:
            if not self._queue:
                return None

            # Re-sort to account for consecutive-count changes since last sort
            self._queue.sort(key=self._sort_key)
            task = self._queue.pop(0)
            ctx = self._agents.get(task.agent_id)

        if ctx is None:
            # Agent was unregistered between submission and dispatch
            return DispatchResult(
                task_id=task.task_id,
                agent_id=task.agent_id,
                success=False,
                return_value=None,
                error="agent_unregistered",
                duration_ms=0.0,
            )

        # Execute OUTSIDE lock
        start_ns = time.perf_counter_ns()
        return_value = None
        error_msg: Optional[str] = None
        success = False

        try:
            return_value = task.fn()
            success = True
        except Exception as exc:
            error_msg = str(exc)

        duration_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0

        # Update agent state under lock
        with self._queue_lock:
            if success:
                ctx.record_success()
                self._total_succeeded += 1
            else:
                ctx.record_failure()
                self._total_failed += 1

            self._total_dispatched += 1

            # Starvation prevention: reset consecutive counter for all OTHER agents
            if self._last_dispatched_agent_id != task.agent_id:
                for aid, other_ctx in self._agents.items():
                    if aid != task.agent_id:
                        other_ctx.reset_consecutive()

            self._last_dispatched_agent_id = task.agent_id

        return DispatchResult(
            task_id=task.task_id,
            agent_id=task.agent_id,
            success=success,
            return_value=return_value,
            error=error_msg,
            duration_ms=duration_ms,
        )

    def dispatch_all(self) -> List[DispatchResult]:
        """Dispatch all pending tasks in priority order.  Returns list of results."""
        results: List[DispatchResult] = []
        while True:
            result = self.dispatch_next()
            if result is None:
                break
            results.append(result)
        return results

    # ------------------------------------------------------------------
    # Queue inspection
    # ------------------------------------------------------------------

    def queue_depth(self) -> int:
        with self._queue_lock:
            return len(self._queue)

    def dead_letter_depth(self) -> int:
        with self._queue_lock:
            return len(self._dead_letter)

    def get_dead_letter_queue(self) -> List[AgentTask]:
        """Return a copy of the dead-letter queue (memory-only; never persisted)."""
        with self._queue_lock:
            return list(self._dead_letter)

    def clear_dead_letter_queue(self) -> int:
        """Clear dead-letter queue.  Returns count removed."""
        with self._queue_lock:
            count = len(self._dead_letter)
            self._dead_letter.clear()
            return count

    def get_status(self) -> SchedulerStatus:
        with self._queue_lock:
            return SchedulerStatus(
                queue_depth=len(self._queue),
                dead_letter_depth=len(self._dead_letter),
                registered_agents=len(self._agents),
                total_dispatched=self._total_dispatched,
                total_succeeded=self._total_succeeded,
                total_failed=self._total_failed,
                total_dead_lettered=self._total_dead_lettered,
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _sort_key(self, task: AgentTask):
        """Deterministic sort key implementing KAOS scheduling discipline.

        Sort order: effective_priority DESC, consecutive_count ASC, agent_id ASC.
        Implemented as: (-effective_priority, consecutive_count, agent_id).
        """
        ctx = self._agents.get(task.agent_id)
        if ctx is None:
            # Unknown agent: lowest priority
            return (1, 0, task.agent_id)

        max_consec = runtime_config.MAX_CONSECUTIVE_EXECUTIONS_PER_AGENT
        ep = ctx.effective_priority(max_consec)
        # Negate priority for ascending sort (highest priority = smallest sort key)
        return (-ep, ctx.consecutive_execution_count, task.agent_id)

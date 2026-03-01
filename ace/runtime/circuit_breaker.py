"""Circuit-breaker FSM for individual agent contexts.

State transitions:
    CLOSED  --(failure_count >= threshold)--> OPEN
    OPEN    --(retry window elapsed)---------> HALF_OPEN
    HALF_OPEN --(on_success)----------------> CLOSED
    HALF_OPEN --(on_failure)----------------> OPEN

All transitions are logged to GoldenTrace when TRACE_ENABLED is True.
No background timers: the window is checked lazily at dispatch time.
"""
from __future__ import annotations

import time
from typing import Optional

from ace.runtime import runtime_config
from ace.runtime.golden_trace import EventType, GoldenTrace

# Forward-import only for type checking to avoid circular imports
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ace.runtime.agent_context import AgentContext


CIRCUIT_CLOSED = "CLOSED"
CIRCUIT_OPEN = "OPEN"
CIRCUIT_HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    """Stateless helper that mutates an AgentContext based on success/failure.

    A single shared CircuitBreaker instance may be used by the scheduler for
    all agents — it carries no per-agent state itself.

    Args:
        failure_threshold: Number of consecutive failures in the CLOSED state
            that trip the breaker (default 3).
    """

    def __init__(self, failure_threshold: int = 3) -> None:
        self._failure_threshold = failure_threshold

    # ── Public API ────────────────────────────────────────────────────────────

    def on_success(self, ctx: "AgentContext") -> Optional[str]:
        """Record a successful task execution for *ctx*.

        If the circuit was HALF_OPEN it transitions to CLOSED.

        Returns:
            The new circuit_state string if a transition occurred, else None.
        """
        if ctx.circuit_state == CIRCUIT_HALF_OPEN:
            ctx.circuit_state = CIRCUIT_CLOSED
            ctx.failure_count = 0
            ctx.last_failure_time = time.monotonic()
            self._log(EventType.CIRCUIT_BREAKER_CLOSED, ctx)
            return CIRCUIT_CLOSED

        # CLOSED: reset failure count on success (partial recovery)
        if ctx.circuit_state == CIRCUIT_CLOSED and ctx.failure_count > 0:
            ctx.failure_count = 0

        return None

    def on_failure(self, ctx: "AgentContext") -> Optional[str]:
        """Record a failed task execution for *ctx*.

        Transitions:
            CLOSED    → OPEN  when failure_count reaches threshold
            HALF_OPEN → OPEN  always (probe failed)

        Returns:
            The new circuit_state string if a transition occurred, else None.
        """
        ctx.failure_count += 1
        ctx.last_failure_time = time.monotonic()

        if ctx.circuit_state in (CIRCUIT_CLOSED, CIRCUIT_HALF_OPEN):
            if (ctx.circuit_state == CIRCUIT_HALF_OPEN
                    or ctx.failure_count >= self._failure_threshold):
                ctx.circuit_state = CIRCUIT_OPEN
                self._log(EventType.CIRCUIT_BREAKER_OPENED, ctx)
                return CIRCUIT_OPEN

        return None

    def check_half_open_transition(self, ctx: "AgentContext") -> bool:
        """If OPEN and the retry window has elapsed, advance to HALF_OPEN.

        Called lazily inside AgentContext.is_dispatchable() — no timers needed.

        Returns:
            True if the circuit just transitioned to HALF_OPEN.
        """
        if ctx.circuit_state != CIRCUIT_OPEN:
            return False

        elapsed = time.monotonic() - ctx.last_failure_time
        if elapsed >= ctx.retry_window_seconds:
            ctx.circuit_state = CIRCUIT_HALF_OPEN
            # Logging removed — caller (scheduler) logs outside _queue_lock
            return True

        return False

    # ── Internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _log(event_type: str, ctx: "AgentContext") -> None:
        if not runtime_config.TRACE_ENABLED:
            return
        GoldenTrace.get_instance().log_event(
            event_type=event_type,
            metadata={
                "agent_id": ctx.agent_id,
                "circuit_state": ctx.circuit_state,
                "failure_count": ctx.failure_count,
            },
        )

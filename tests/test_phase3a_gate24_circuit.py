"""Gate 2.4 — Circuit Breaker Tests.

Tests:
    1. CLOSED → OPEN after consecutive failure threshold
    2. OPEN circuit rejects tasks to dead-letter
    3. OPEN → HALF_OPEN after retry window elapses
    4. HALF_OPEN → CLOSED on successful trial dispatch
    5. HALF_OPEN → OPEN on failed trial dispatch
    6. Circuit transition events recorded in GoldenTrace when TRACE_ENABLED

All tests must pass with the full prior suite (28 tests) still passing.
"""
from __future__ import annotations

import time
import pytest

from ace.runtime import runtime_config
from ace.runtime.agent_context import (
    AgentContext,
    CIRCUIT_CLOSED,
    CIRCUIT_OPEN,
    CIRCUIT_HALF_OPEN,
)
from ace.runtime.agent_scheduler import AgentScheduler
from ace.runtime.circuit_breaker import CircuitBreaker
from ace.runtime.golden_trace import EventType, GoldenTrace
from ace.runtime.event_sequence import GlobalEventSequence


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(agent_id: str = "agent-cb", priority: int = 5,
              retry_window: float = 60.0) -> AgentContext:
    return AgentContext(
        agent_id=agent_id,
        priority=priority,
        memory_quota_entries=100,
        cpu_quota_ms=500,
        execution_timeout_ms=1000,
        retry_window_seconds=retry_window,
    )


def _failing_fn():
    raise RuntimeError("forced failure")


def _ok_fn():
    return "ok"


# ---------------------------------------------------------------------------
# Test 1: CLOSED → OPEN after failure threshold
# ---------------------------------------------------------------------------

def test_closed_to_open_after_n_failures():
    """3 consecutive failures must trip the breaker from CLOSED to OPEN."""
    cb = CircuitBreaker(failure_threshold=3)
    ctx = _make_ctx()
    assert ctx.circuit_state == CIRCUIT_CLOSED

    # Two failures: still CLOSED
    for _ in range(2):
        transition = cb.on_failure(ctx)
        assert transition is None, "Should not trip breaker before threshold"
        assert ctx.circuit_state == CIRCUIT_CLOSED

    # Third failure: should trip
    transition = cb.on_failure(ctx)
    assert transition == CIRCUIT_OPEN
    assert ctx.circuit_state == CIRCUIT_OPEN
    assert ctx.failure_count == 3


# ---------------------------------------------------------------------------
# Test 2: OPEN circuit rejects new tasks to dead-letter
# ---------------------------------------------------------------------------

def test_open_rejects_tasks_to_dead_letter():
    """Tasks submitted while circuit is OPEN go to dead-letter, not queue."""
    scheduler = AgentScheduler(failure_threshold=2)
    ctx = _make_ctx(retry_window=9999.0)   # long window so it stays OPEN
    scheduler.register_agent(ctx)

    # Trip the breaker by dispatching failures
    for i in range(2):
        scheduler.submit_task(ctx.agent_id, f"t{i}", _failing_fn)
    scheduler.dispatch_all()

    # After 2 failures circuit should be OPEN
    live_ctx = scheduler._agents[ctx.agent_id]
    assert live_ctx.circuit_state == CIRCUIT_OPEN

    # Submitting another task should land in dead-letter
    dl_before = scheduler.dead_letter_depth()
    accepted = scheduler.submit_task(ctx.agent_id, "rejected-task", _ok_fn)
    assert not accepted
    assert scheduler.dead_letter_depth() == dl_before + 1
    assert scheduler.queue_depth() == 0


# ---------------------------------------------------------------------------
# Test 3: OPEN → HALF_OPEN after retry window
# ---------------------------------------------------------------------------

def test_open_to_half_open_after_retry_window():
    """Once the retry window elapses, submit_task transitions OPEN → HALF_OPEN."""
    cb = CircuitBreaker(failure_threshold=1)
    ctx = _make_ctx(retry_window=0.0)   # window = 0s → always elapsed

    # Trip it
    cb.on_failure(ctx)
    assert ctx.circuit_state == CIRCUIT_OPEN

    # Calling check_half_open_transition should advance state
    transitioned = cb.check_half_open_transition(ctx)
    assert transitioned is True
    assert ctx.circuit_state == CIRCUIT_HALF_OPEN


# ---------------------------------------------------------------------------
# Test 4: HALF_OPEN → CLOSED on success
# ---------------------------------------------------------------------------

def test_half_open_to_closed_on_success():
    """A successful trial dispatch while HALF_OPEN closes the circuit."""
    scheduler = AgentScheduler(failure_threshold=1)
    ctx = _make_ctx(retry_window=0.0)   # window = 0 → always elapsed
    scheduler.register_agent(ctx)

    # Trip circuit
    scheduler.submit_task(ctx.agent_id, "fail-1", _failing_fn)
    scheduler.dispatch_all()

    live_ctx = scheduler._agents[ctx.agent_id]
    assert live_ctx.circuit_state == CIRCUIT_OPEN

    # Submit again — zero retry window means check_half_open_transition advances it
    accepted = scheduler.submit_task(ctx.agent_id, "probe", _ok_fn)
    assert accepted
    assert live_ctx.circuit_state == CIRCUIT_HALF_OPEN

    # Dispatch probe — success should close
    result = scheduler.dispatch_next()
    assert result is not None
    assert result.success
    assert live_ctx.circuit_state == CIRCUIT_CLOSED


# ---------------------------------------------------------------------------
# Test 5: HALF_OPEN → OPEN on failure
# ---------------------------------------------------------------------------

def test_half_open_to_open_on_failure():
    """A failed trial dispatch while HALF_OPEN re-opens the circuit."""
    scheduler = AgentScheduler(failure_threshold=1)
    ctx = _make_ctx(retry_window=0.0)
    scheduler.register_agent(ctx)

    # Trip
    scheduler.submit_task(ctx.agent_id, "fail-1", _failing_fn)
    scheduler.dispatch_all()

    live_ctx = scheduler._agents[ctx.agent_id]
    # Allow HALF_OPEN transition
    accepted = scheduler.submit_task(ctx.agent_id, "probe", _failing_fn)
    assert accepted
    assert live_ctx.circuit_state == CIRCUIT_HALF_OPEN

    # Dispatch probe — failure should re-open
    result = scheduler.dispatch_next()
    assert result is not None
    assert not result.success
    assert live_ctx.circuit_state == CIRCUIT_OPEN


# ---------------------------------------------------------------------------
# Test 6: Circuit events recorded in GoldenTrace when TRACE_ENABLED
# ---------------------------------------------------------------------------

def test_circuit_events_in_golden_trace(monkeypatch):
    """CIRCUIT_BREAKER_OPENED and CIRCUIT_BREAKER_CLOSED appear in the trace."""
    monkeypatch.setattr(runtime_config, "TRACE_ENABLED", True)

    # Reset singleton state
    trace = GoldenTrace.get_instance()
    trace.reset()
    GlobalEventSequence.get_instance().reset()

    cb = CircuitBreaker(failure_threshold=2)
    ctx = _make_ctx(retry_window=0.0)

    # Two failures → OPENED event
    cb.on_failure(ctx)
    cb.on_failure(ctx)
    assert ctx.circuit_state == CIRCUIT_OPEN

    events = trace.get_all_events()
    opened_events = [e for e in events if e.event_type == EventType.CIRCUIT_BREAKER_OPENED]
    assert len(opened_events) == 1, f"Expected 1 CIRCUIT_BREAKER_OPENED, got {len(opened_events)}"

    # Advance to HALF_OPEN
    cb.check_half_open_transition(ctx)
    assert ctx.circuit_state == CIRCUIT_HALF_OPEN

    half_events = [e for e in trace.get_all_events()
                   if e.event_type == EventType.CIRCUIT_BREAKER_HALF_OPEN]
    assert len(half_events) == 1

    # Close on success
    cb.on_success(ctx)
    assert ctx.circuit_state == CIRCUIT_CLOSED

    closed_events = [e for e in trace.get_all_events()
                     if e.event_type == EventType.CIRCUIT_BREAKER_CLOSED]
    assert len(closed_events) == 1

    monkeypatch.setattr(runtime_config, "TRACE_ENABLED", False)

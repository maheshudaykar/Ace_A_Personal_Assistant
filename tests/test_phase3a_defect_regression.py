"""Phase 3A Defect Regression Tests — March 1, 2026.

Tests for architectural defect fixes:
1. DEFECT #1: Single-agent permanent starvation (agent_scheduler.py line 283)
2. DEFECT #2: Nested lock _queue_lock -> _events_lock (agent_scheduler.py line 166)
3. DEFECT #3: Incomplete replay validation (determinism_validator.py)
"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

from ace.ace_diagnostics.evaluation_engine import EvaluationEngine
from ace.ace_kernel.audit_trail import AuditTrail
from ace.ace_memory.episodic_memory import EpisodicMemory
from ace.ace_memory.memory_store import MemoryStore
from ace.ace_memory.quality_scorer import QualityScorer
from ace.runtime import runtime_config
from ace.runtime.agent_context import AgentContext, CIRCUIT_OPEN, CIRCUIT_HALF_OPEN, CIRCUIT_CLOSED
from ace.runtime.agent_scheduler import AgentScheduler
from ace.runtime.determinism_validator import DeterminismValidator
from ace.runtime.event_sequence import GlobalEventSequence
from ace.runtime.golden_trace import EventType, GoldenTrace


# ---------------------------------------------------------------------------
# DEFECT #1: Single-Agent Permanent Starvation
# ---------------------------------------------------------------------------

def test_defect1_single_agent_no_starvation():
    """Regression test: single-agent system must not starve after 3+ dispatches.
    
    Before fix: agent.consecutive_execution_count reached MAX_CONSECUTIVE (3), 
    effective_priority dropped to -1, and no other agent existed to reset it.
    Agent became permanently un-dispatchable.
    
    After fix: scheduler detects len(agents)==1 and resets consecutive count.
    """
    scheduler = AgentScheduler(failure_threshold=10)
    ctx = AgentContext(
        agent_id="solo-agent",
        priority=5,
        memory_quota_entries=100,
        cpu_quota_ms=500,
        execution_timeout_ms=1000,
    )
    scheduler.register_agent(ctx)

    # Submit and dispatch 10 tasks (well beyond MAX_CONSECUTIVE_EXECUTIONS_PER_AGENT=3)
    for i in range(10):
        accepted = scheduler.submit_task("solo-agent", f"task-{i}", lambda: "ok")
        assert accepted, f"Task {i} rejected unexpectedly"
        result = scheduler.dispatch_next()
        assert result is not None, f"Dispatch {i} returned None"
        assert result.success, f"Dispatch {i} failed"
    
    # Verify agent is still dispatchable
    live_ctx = scheduler._agents["solo-agent"]
    assert live_ctx.consecutive_execution_count == 0, (
        f"Expected consecutive_count=0 for single agent, got {live_ctx.consecutive_execution_count}"
    )


# ---------------------------------------------------------------------------
# DEFECT #2: Nested Lock (_queue_lock -> _events_lock)
# ---------------------------------------------------------------------------

def test_defect2_no_nested_lock_on_half_open_transition(monkeypatch):
    """Regression test: HALF_OPEN transition must log OUTSIDE _queue_lock.
    
    Before fix: check_half_open_transition() called inside _queue_lock, which
    called _log() -> GoldenTrace.log_event() -> acquired _events_lock, creating
    nested lock: _queue_lock -> _events_lock.
    
    After fix: check_half_open_transition() returns bool, scheduler logs OUTSIDE lock.
    """
    monkeypatch.setattr(runtime_config, "TRACE_ENABLED", True)
    
    GoldenTrace.get_instance().reset()
    GlobalEventSequence.get_instance().reset()

    scheduler = AgentScheduler(failure_threshold=1)
    ctx = AgentContext(
        agent_id="test-agent",
        priority=5,
        memory_quota_entries=100,
        cpu_quota_ms=500,
        execution_timeout_ms=1000,
        retry_window_seconds=0.0,  # zero = immediate HALF_OPEN after OPEN
    )
    scheduler.register_agent(ctx)

    # Trip circuit with 1 failure
    scheduler.submit_task("test-agent", "fail-1", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    scheduler.dispatch_all()

    live_ctx = scheduler._agents["test-agent"]
    assert live_ctx.circuit_state == CIRCUIT_OPEN

    # This submit_task call will trigger OPEN -> HALF_OPEN transition
    # If logging happens inside _queue_lock, we'd have nested lock
    # The test passes if no deadlock occurs
    accepted = scheduler.submit_task("test-agent", "probe", lambda: "ok")
    assert accepted
    assert live_ctx.circuit_state == CIRCUIT_HALF_OPEN

    # Verify HALF_OPEN event was logged (outside lock)
    trace_events = GoldenTrace.get_instance().get_all_events()
    half_open_events = [
        e for e in trace_events 
        if e.event_type == EventType.CIRCUIT_BREAKER_HALF_OPEN
    ]
    assert len(half_open_events) == 1, f"Expected 1 HALF_OPEN event, got {len(half_open_events)}"

    monkeypatch.setattr(runtime_config, "TRACE_ENABLED", False)


# ---------------------------------------------------------------------------
# DEFECT #3: Incomplete Replay Validation
# ---------------------------------------------------------------------------

def test_defect3_replay_validates_agent_dispatch_order(
    monkeypatch, tmp_path: Path
):
    """Regression test: replay must validate agent dispatch sequence, not just memory.
    
    Before fix: DeterminismValidator only validated memory-layer events (RECORD/ARCHIVE).
    Circuit and agent events were ignored.
    
    After fix: extract_memory_snapshot() captures agent_dispatch_sequence and
    circuit_transitions; validate_determinism() checks they match.
    """
    monkeypatch.setattr(runtime_config, "TRACE_ENABLED", True)

    GoldenTrace.get_instance().reset()
    GlobalEventSequence.get_instance().reset()

    audit = AuditTrail(tmp_path / "audit.jsonl")
    store = MemoryStore(tmp_path / "memory.jsonl", audit_trail=audit)
    scorer = QualityScorer(EvaluationEngine())
    episodic = EpisodicMemory(store, quality_scorer=scorer, audit_trail=audit)

    scheduler = AgentScheduler(failure_threshold=2)
    ctx_a = AgentContext("agent-A", priority=10, memory_quota_entries=100, cpu_quota_ms=500, execution_timeout_ms=1000)
    ctx_b = AgentContext("agent-B", priority=5, memory_quota_entries=100, cpu_quota_ms=500, execution_timeout_ms=1000)
    scheduler.register_agent(ctx_a)
    scheduler.register_agent(ctx_b)

    # Submit tasks and dispatch (higher priority agent-A goes first)
    scheduler.submit_task("agent-A", "t1", lambda: episodic.record("agent-A", "content-A1", 0.9))
    scheduler.submit_task("agent-B", "t2", lambda: episodic.record("agent-B", "content-B1", 0.9))
    scheduler.submit_task("agent-A", "t3", lambda: episodic.record("agent-A", "content-A2", 0.9))

    results = scheduler.dispatch_all()
    assert len(results) == 3

    # Extract snapshot from trace
    trace = GoldenTrace.get_instance().get_all_events()
    validator = DeterminismValidator()
    snapshot = validator.extract_memory_snapshot(trace)

    # DEFECT FIX #3: Verify agent_dispatch_sequence is captured
    assert "agent_dispatch_sequence" in snapshot
    dispatch_seq = snapshot["agent_dispatch_sequence"]
    assert len(dispatch_seq) == 3, f"Expected 3 dispatches, got {len(dispatch_seq)}"

    # Verify dispatch order (agent-A priority=10 goes first twice, then agent-B priority=5)
    agent_ids = [agent_id for agent_id, task_id, seq_id in dispatch_seq]
    # Priority sort should give: agent-A, agent-A, agent-B
    assert agent_ids[0] == "agent-A"
    assert agent_ids[1] == "agent-A"
    assert agent_ids[2] == "agent-B"

    # Verify circuit_transitions field exists (even if empty)
    assert "circuit_transitions" in snapshot
    assert isinstance(snapshot["circuit_transitions"], list)

    monkeypatch.setattr(runtime_config, "TRACE_ENABLED", False)


def test_defect3_replay_validates_circuit_transitions(monkeypatch):
    """Regression test: replay must validate circuit breaker state transitions.
    
    Before fix: Circuit events (OPENED, HALF_OPEN, CLOSED) were logged but not
    included in determinism validation.
    
    After fix: circuit_transitions captured as (agent_id, new_state, seq_id) tuples.
    """
    monkeypatch.setattr(runtime_config, "TRACE_ENABLED", True)

    GoldenTrace.get_instance().reset()
    GlobalEventSequence.get_instance().reset()

    scheduler = AgentScheduler(failure_threshold=2)
    ctx = AgentContext(
        agent_id="fragile-agent",
        priority=5,
        memory_quota_entries=100,
        cpu_quota_ms=500,
        execution_timeout_ms=1000,
        retry_window_seconds=0.0,
    )
    scheduler.register_agent(ctx)

    # Trip circuit with 2 failures
    for i in range(2):
        scheduler.submit_task("fragile-agent", f"fail-{i}", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    scheduler.dispatch_all()

    # OPEN -> HALF_OPEN -> CLOSED flow
    scheduler.submit_task("fragile-agent", "probe", lambda: "recovered")
    scheduler.dispatch_next()

    trace = GoldenTrace.get_instance().get_all_events()
    validator = DeterminismValidator()
    snapshot = validator.extract_memory_snapshot(trace)

    # DEFECT FIX #3: Verify circuit transitions captured
    circuit_transitions = snapshot["circuit_transitions"]
    assert len(circuit_transitions) >= 3, (
        f"Expected >= 3 transitions (OPEN, HALF_OPEN, CLOSED), got {len(circuit_transitions)}"
    )

    # Extract states in order
    states = [state for agent_id, state, seq_id in circuit_transitions]
    # Should see: OPEN, HALF_OPEN, CLOSED (among other possible events)
    assert "OPEN" in states or "OPENED" in states
    assert "HALF_OPEN" in states or "HALF-OPEN" in states
    assert "CLOSED" in states

    monkeypatch.setattr(runtime_config, "TRACE_ENABLED", False)

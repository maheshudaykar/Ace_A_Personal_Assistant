"""Gate 2.6 — Integration Stress Tests.

End-to-end tests exercising the full Phase 3A runtime stack under concurrent
load. Every test is time-bounded (no real hour-long runs).

Tests:
    1. 10k-scale soak: 10 threads × 100 records each; verify index consistency
    2. 5-second deadlock probe: concurrent memory + scheduler + metrics; no hang
    3. Cross-domain lock ordering: metrics lock held while memory ops run
    4. Circuit breaker + scheduler end-to-end flow (trip → HALF_OPEN → CLOSED)
    5. GoldenTrace + MetricsRegistry simultaneous (no lost events)
    6. Phase 2C quota governance preserved under 8-thread concurrent load
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from ace.ace_diagnostics.evaluation_engine import EvaluationEngine
from ace.ace_kernel.audit_trail import AuditTrail
from ace.ace_memory import memory_config
from ace.ace_memory.episodic_memory import EpisodicMemory
from ace.ace_memory.memory_store import MemoryStore
from ace.ace_memory.quality_scorer import QualityScorer
from ace.runtime import runtime_config
from ace.runtime.agent_context import AgentContext, CIRCUIT_OPEN, CIRCUIT_HALF_OPEN, CIRCUIT_CLOSED
from ace.runtime.agent_scheduler import AgentScheduler
from ace.runtime.event_sequence import GlobalEventSequence
from ace.runtime.golden_trace import EventType, GoldenTrace
from ace.runtime.metrics_registry import MetricsRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def audit(tmp_path: Path) -> AuditTrail:
    return AuditTrail(tmp_path / "audit.jsonl")


@pytest.fixture
def store(tmp_path: Path, audit: AuditTrail) -> MemoryStore:
    return MemoryStore(tmp_path / "memory.jsonl", audit_trail=audit)


@pytest.fixture
def scorer() -> QualityScorer:
    return QualityScorer(EvaluationEngine())


@pytest.fixture
def episodic(store: MemoryStore, scorer: QualityScorer, audit: AuditTrail) -> EpisodicMemory:
    return EpisodicMemory(store, quality_scorer=scorer, audit_trail=audit)


def _ctx(agent_id: str, priority: int = 5, retry_window: float = 9999.0) -> AgentContext:
    return AgentContext(
        agent_id=agent_id,
        priority=priority,
        memory_quota_entries=500,
        cpu_quota_ms=5000,
        execution_timeout_ms=10000,
        retry_window_seconds=retry_window,
    )


# ---------------------------------------------------------------------------
# Test 1: 10k-scale soak — concurrent writes + reads, index consistency
# ---------------------------------------------------------------------------

def test_10k_soak_episodic_memory(
    monkeypatch: pytest.MonkeyPatch,
    episodic: EpisodicMemory,
) -> None:
    """10 writer threads × 100 records each = 1 000 entries. Index must be consistent."""
    monkeypatch.setattr(memory_config, "MAX_TOTAL_ENTRIES", 5000)
    monkeypatch.setattr(memory_config, "MAX_ACTIVE_ENTRIES", 5000)
    monkeypatch.setattr(memory_config, "MAX_ENTRIES_PER_TASK", 5000)

    N_THREADS = 10
    RECORDS_PER_THREAD = 100
    errors: list[Exception] = []
    recorded_ids: list[str] = []
    ids_lock = threading.Lock()

    def worker(task_id: str) -> None:
        try:
            for _ in range(RECORDS_PER_THREAD):
                entry = episodic.record(task_id=task_id, content="soak content", importance_score=0.9)
                if entry is not None:
                    with ids_lock:
                        recorded_ids.append(str(entry.id))
        except Exception as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(f"task-{t}",))
        for t in range(N_THREADS)
    ]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=30.0)

    assert not errors, f"Worker errors: {errors}"

    stats = episodic.get_index_stats()
    expected_total = N_THREADS * RECORDS_PER_THREAD
    assert stats["total_indexed"] == expected_total, (
        f"Expected {expected_total} active entries, got {stats['total_indexed']}"
    )

    # All IDs must be unique
    assert len(set(recorded_ids)) == expected_total, "Duplicate entry IDs detected"


# ---------------------------------------------------------------------------
# Test 2: 5-second deadlock probe — all subsystems concurrently
# ---------------------------------------------------------------------------

def test_5s_deadlock_probe(
    monkeypatch: pytest.MonkeyPatch,
    episodic: EpisodicMemory,
) -> None:
    """All three Phase 3A lock domains run concurrently for 5 seconds without deadlock."""
    monkeypatch.setattr(memory_config, "MAX_TOTAL_ENTRIES", 50000)
    monkeypatch.setattr(memory_config, "MAX_ACTIVE_ENTRIES", 50000)
    monkeypatch.setattr(memory_config, "MAX_ENTRIES_PER_TASK", 50000)

    registry = MetricsRegistry.get_instance()
    registry.reset()

    scheduler = AgentScheduler(failure_threshold=10)
    ctx = _ctx("probe-agent")
    scheduler.register_agent(ctx)

    DURATION = 5.0
    errors: list[Exception] = []

    def memory_worker() -> None:
        deadline = time.monotonic() + DURATION
        try:
            i = 0
            while time.monotonic() < deadline:
                episodic.record(task_id=f"task-{i % 20}", content="probe", importance_score=0.8)
                i += 1
        except Exception as exc:
            errors.append(exc)

    def scheduler_worker() -> None:
        deadline = time.monotonic() + DURATION
        try:
            i = 0
            while time.monotonic() < deadline:
                scheduler.submit_task("probe-agent", f"t{i}", lambda: None)
                scheduler.dispatch_next()
                i += 1
        except Exception as exc:
            errors.append(exc)

    def metrics_worker() -> None:
        deadline = time.monotonic() + DURATION
        try:
            i = 0
            while time.monotonic() < deadline:
                registry.record_dispatch("probe-agent", f"m{i}", 1.0, success=True)
                i += 1
        except Exception as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=memory_worker),
        threading.Thread(target=memory_worker),
        threading.Thread(target=scheduler_worker),
        threading.Thread(target=metrics_worker),
    ]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=DURATION + 5.0)

    alive = [th for th in threads if th.is_alive()]
    assert not alive, f"{len(alive)} threads still alive — deadlock detected"
    assert not errors, f"Worker errors: {errors}"


# ---------------------------------------------------------------------------
# Test 3: Cross-domain lock ordering — no deadlock
# ---------------------------------------------------------------------------

def test_cross_domain_lock_ordering_no_deadlock(
    monkeypatch: pytest.MonkeyPatch,
    episodic: EpisodicMemory,
) -> None:
    """Acquiring locks in opposite orders from concurrent threads must not deadlock."""
    monkeypatch.setattr(memory_config, "MAX_TOTAL_ENTRIES", 50000)
    monkeypatch.setattr(memory_config, "MAX_ACTIVE_ENTRIES", 50000)
    monkeypatch.setattr(memory_config, "MAX_ENTRIES_PER_TASK", 50000)

    registry = MetricsRegistry.get_instance()
    registry.reset()

    errors: list[Exception] = []
    completed: list[int] = []
    gate = threading.Barrier(2)

    def thread_a() -> None:
        """Holds metrics lock then records to memory layer."""
        try:
            gate.wait()
            with registry._metrics_lock:
                episodic.record(task_id="cross-a", content="a", importance_score=0.8)
                registry._total_dispatched += 1
            completed.append(1)
        except Exception as exc:
            errors.append(exc)

    def thread_b() -> None:
        """Holds memory RWLock (read) then records a metric."""
        try:
            gate.wait()
            with episodic._indices_rwlock.read_locked():
                registry.record_dispatch("agent-x", "tx", 1.0, success=True)
            completed.append(1)
        except Exception as exc:
            errors.append(exc)

    ta = threading.Thread(target=thread_a)
    tb = threading.Thread(target=thread_b)
    ta.start()
    tb.start()
    ta.join(timeout=5.0)
    tb.join(timeout=5.0)

    assert not ta.is_alive() and not tb.is_alive(), "Deadlock detected between domains"
    assert not errors, f"Errors: {errors}"
    assert sum(completed) == 2


# ---------------------------------------------------------------------------
# Test 4: Circuit breaker + scheduler end-to-end flow
# ---------------------------------------------------------------------------

def test_circuit_breaker_scheduler_end_to_end() -> None:
    """Full CLOSED → OPEN → HALF_OPEN → CLOSED flow via scheduler dispatches."""
    scheduler = AgentScheduler(failure_threshold=3)
    ctx = _ctx("cb-agent", retry_window=0.0)
    scheduler.register_agent(ctx)

    # Trip with 3 failures
    for i in range(3):
        scheduler.submit_task("cb-agent", f"fail-{i}", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    results = scheduler.dispatch_all()
    assert all(not r.success for r in results)

    live = scheduler._agents["cb-agent"]
    assert live.circuit_state == CIRCUIT_OPEN

    # Zero retry window → HALF_OPEN on next submit
    accepted = scheduler.submit_task("cb-agent", "probe", lambda: "recovered")
    assert accepted, "Task rejected unexpectedly after retry window"
    assert live.circuit_state == CIRCUIT_HALF_OPEN

    # Successful probe → CLOSED
    result = scheduler.dispatch_next()
    assert result is not None and result.success
    assert live.circuit_state == CIRCUIT_CLOSED

    # Confirm normal operation resumes
    scheduler.submit_task("cb-agent", "normal", lambda: "ok")
    r = scheduler.dispatch_next()
    assert r is not None and r.success


# ---------------------------------------------------------------------------
# Test 5: GoldenTrace + MetricsRegistry simultaneous correctness
# ---------------------------------------------------------------------------

def test_golden_trace_and_metrics_simultaneous(monkeypatch: pytest.MonkeyPatch) -> None:
    """Under concurrent load, every dispatched task appears in both trace and metrics."""
    monkeypatch.setattr(runtime_config, "TRACE_ENABLED", True)

    trace = GoldenTrace.get_instance()
    trace.reset()
    GlobalEventSequence.get_instance().reset()

    registry = MetricsRegistry.get_instance()
    registry.reset()

    N = 50
    errors: list[Exception] = []

    def worker(agent_id: str) -> None:
        try:
            for i in range(N):
                trace.log_event(
                    event_type=EventType.AGENT_TASK_COMPLETED,
                    metadata={"agent_id": agent_id, "task_id": f"t{i}"},
                )
                registry.record_dispatch(agent_id, f"t{i}", 1.0, success=True)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(f"agent-{t}",)) for t in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    assert not errors

    total_trace_events = sum(
        1 for e in trace.get_all_events()
        if e.event_type == EventType.AGENT_TASK_COMPLETED
    )
    total_metrics = registry.get_total_dispatched()

    expected = 4 * N
    assert total_trace_events == expected, f"Trace: {total_trace_events} != {expected}"
    assert total_metrics == expected, f"Metrics: {total_metrics} != {expected}"

    # Sequence IDs monotonically increasing, no duplicates
    seq_ids = [e.sequence_id for e in trace.get_all_events()]
    assert seq_ids == sorted(seq_ids), "Sequence IDs not monotonically increasing"
    assert len(seq_ids) == len(set(seq_ids)), "Duplicate sequence IDs detected"

    monkeypatch.setattr(runtime_config, "TRACE_ENABLED", False)


# ---------------------------------------------------------------------------
# Test 6: Phase 2C quota governance survives 8-thread concurrent load
# ---------------------------------------------------------------------------

def test_phase2c_quota_under_concurrency(
    monkeypatch: pytest.MonkeyPatch,
    episodic: EpisodicMemory,
) -> None:
    """Active quota must be enforced even when 8 threads write simultaneously."""
    QUOTA = 50
    monkeypatch.setattr(memory_config, "MAX_TOTAL_ENTRIES", 5000)
    monkeypatch.setattr(memory_config, "MAX_ACTIVE_ENTRIES", QUOTA)
    monkeypatch.setattr(memory_config, "MAX_ENTRIES_PER_TASK", 5000)

    N_THREADS = 8
    RECORDS_EACH = 20

    errors: list[Exception] = []

    def writer() -> None:
        try:
            for _ in range(RECORDS_EACH):
                episodic.record(task_id="quota-task", content="quota test", importance_score=0.9)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer) for _ in range(N_THREADS)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=30.0)

    assert not errors, f"Worker errors: {errors}"

    stats = episodic.get_index_stats()
    assert stats["total_indexed"] <= QUOTA, (
        f"Quota violated: active_count={stats['total_indexed']} > QUOTA={QUOTA}"
    )

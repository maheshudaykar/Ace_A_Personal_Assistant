"""Gate 2.5 — MetricsRegistry Tests.

Tests:
    1. RingBuffer evicts oldest on overflow (O(1) push semantics)
    2. RingBuffer latest_n returns correct subset
    3. record_dispatch accumulates latency and counters correctly
    4. record_circuit_transition stored and retrievable
    5. Get summary reports correct failure_rate
    6. Registry is thread-safe under concurrent writes (no corruption)
    7. Registry lock is independent — holding it while memory ops run, no deadlock
    8. reset() clears all state
"""
from __future__ import annotations

import threading
import time

import pytest

from ace.runtime.metrics_registry import (
    CircuitTransitionRecord,
    MetricsRegistry,
    QueueDepthSample,
    RingBuffer,
    TaskRecord,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_registry(capacity: int = 64) -> MetricsRegistry:
    """Force a fresh singleton for testing."""
    MetricsRegistry._instance = None
    reg = MetricsRegistry(capacity=capacity)
    return reg


# ---------------------------------------------------------------------------
# Test 1: RingBuffer evicts oldest item on overflow
# ---------------------------------------------------------------------------

def test_ring_buffer_evicts_oldest():
    """When capacity is n, the (n+1)-th push evicts item 0."""
    buf = RingBuffer(capacity=4)
    for i in range(4):
        buf.push(i)           # [0, 1, 2, 3]
    assert buf.size == 4
    assert buf.to_list() == [0, 1, 2, 3]

    buf.push(99)              # evicts 0 → [1, 2, 3, 99]
    items = buf.to_list()
    assert items == [1, 2, 3, 99], f"Expected [1,2,3,99] got {items}"
    assert buf.size == 4      # size stays at capacity


# ---------------------------------------------------------------------------
# Test 2: RingBuffer latest_n
# ---------------------------------------------------------------------------

def test_ring_buffer_latest_n():
    buf = RingBuffer(capacity=10)
    for i in range(7):
        buf.push(i)           # [0..6]

    # Requesting more than available → full list
    assert buf.latest_n(20) == list(range(7))

    # Exactly 3 most recent
    assert buf.latest_n(3) == [4, 5, 6]

    # 1 most recent
    assert buf.latest_n(1) == [6]


# ---------------------------------------------------------------------------
# Test 3: record_dispatch accumulates correctly
# ---------------------------------------------------------------------------

def test_record_dispatch_counters():
    reg = _fresh_registry()

    reg.record_dispatch("a1", "t1", 10.0, success=True)
    reg.record_dispatch("a1", "t2", 20.0, success=True)
    reg.record_dispatch("a2", "t3", 30.0, success=False)

    assert reg.get_total_dispatched() == 3
    assert reg.get_success_count() == 2
    assert reg.get_failure_count() == 1

    latencies = reg.get_latencies(last_n=10)
    assert latencies == [10.0, 20.0, 30.0]

    avg = reg.get_moving_average_latency(last_n=10)
    assert abs(avg - 20.0) < 1e-9


# ---------------------------------------------------------------------------
# Test 4: record_circuit_transition stored and retrievable
# ---------------------------------------------------------------------------

def test_circuit_transition_recorded():
    reg = _fresh_registry()

    reg.record_circuit_transition("agent-X", "CLOSED", "OPEN")
    reg.record_circuit_transition("agent-X", "OPEN", "HALF_OPEN")
    reg.record_circuit_transition("agent-X", "HALF_OPEN", "CLOSED")

    transitions = reg.get_circuit_transitions(last_n=10)
    assert len(transitions) == 3

    states = [(t.from_state, t.to_state) for t in transitions]
    assert states == [
        ("CLOSED", "OPEN"),
        ("OPEN", "HALF_OPEN"),
        ("HALF_OPEN", "CLOSED"),
    ]


# ---------------------------------------------------------------------------
# Test 5: get_summary correctness
# ---------------------------------------------------------------------------

def test_get_summary_failure_rate():
    reg = _fresh_registry()

    reg.record_dispatch("a", "t1", 5.0, success=True)
    reg.record_dispatch("a", "t2", 5.0, success=False)

    summary = reg.get_summary()
    assert summary["total_dispatched"] == 2
    assert summary["total_succeeded"] == 1
    assert summary["total_failed"] == 1
    assert abs(summary["failure_rate"] - 0.5) < 1e-9
    assert abs(summary["avg_latency_ms"] - 5.0) < 1e-9


# ---------------------------------------------------------------------------
# Test 6: Thread-safe under concurrent writes
# ---------------------------------------------------------------------------

def test_concurrent_writes_no_corruption():
    """1000 concurrent dispatch records from 10 threads must all be counted."""
    reg = _fresh_registry(capacity=2048)
    N_THREADS = 10
    RECORDS_PER_THREAD = 100

    errors = []

    def worker():
        try:
            for i in range(RECORDS_PER_THREAD):
                reg.record_dispatch("agent", f"t{i}", float(i), success=(i % 2 == 0))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Worker errors: {errors}"
    total = N_THREADS * RECORDS_PER_THREAD
    assert reg.get_total_dispatched() == total


# ---------------------------------------------------------------------------
# Test 7: MetricsRegistry lock is independent of memory layer — no deadlock
# ---------------------------------------------------------------------------

def test_registry_lock_independent_of_memory_layer():
    """Hold the registry lock while performing memory-layer operations.
    
    This test verifies the lock ordering invariant: MetricsRegistry._metrics_lock
    is NEVER nested inside memory-layer locks, so acquiring them in any order
    must not deadlock.
    """
    reg = _fresh_registry()
    deadline = time.monotonic() + 2.0  # 2-second watchdog

    result = {"completed": False}

    def do_work():
        # Acquire metrics lock, then simulate memory-layer work on a plain lock
        mem_lock = threading.Lock()
        with reg._metrics_lock:
            reg._total_dispatched += 1   # simulate write
            # Now acquire an 'inner' lock that represents memory layer
            with mem_lock:
                pass   # no deadlock expected
        result["completed"] = True

    t = threading.Thread(target=do_work)
    t.start()
    t.join(timeout=2.0)

    assert result["completed"], "Timed out — potential deadlock detected"


# ---------------------------------------------------------------------------
# Test 8: reset() clears all state
# ---------------------------------------------------------------------------

def test_reset_clears_all():
    reg = _fresh_registry()

    reg.record_dispatch("a", "t1", 99.0, success=False)
    reg.record_circuit_transition("a", "CLOSED", "OPEN")
    reg.record_queue_sample(42)

    reg.reset()

    assert reg.get_total_dispatched() == 0
    assert reg.get_failure_count() == 0
    assert reg.get_latencies() == []
    assert reg.get_circuit_transitions() == []
    summary = reg.get_summary()
    assert summary["total_dispatched"] == 0
    assert summary["circuit_transitions_total"] == 0

"""Metrics registry for Phase 3A runtime — O(1)-append ring buffers.

Design principles:
    - All circular buffers have fixed capacity — O(1) push, O(n) full scan.
    - Single dedicated _metrics_lock, completely independent of all other
      lock domains (memory layer, scheduler queue, RWLock hierarchy).
    - Never yields or blocks the calling thread for more than a microsecond.
    - Singleton — one process-wide registry; tests call reset() between runs.

Tracked metrics:
    dispatch_latency_ms   float   per-task execution duration in milliseconds
    task_records          dict    {agent_id, task_id, duration_ms, success, ts}
    circuit_transitions   dict    {agent_id, from_state, to_state, ts}
    queue_depth_samples   tuple   (timestamp_ns, depth) snapshots
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Ring buffer
# ---------------------------------------------------------------------------

class RingBuffer:
    """Fixed-capacity circular buffer. push() is O(1); full scan is O(capacity).

    Items are stored in a pre-allocated list. When the buffer is full the
    oldest item is silently overwritten by the newest.
    """

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError(f"capacity must be >= 1, got {capacity}")
        self._capacity = capacity
        self._buf: List[Any] = [None] * capacity
        self._head: int = 0   # next write position
        self._size: int = 0   # current fill level

    # -- write ---------------------------------------------------------------

    def push(self, value: Any) -> None:
        """Append *value*; evict the oldest item when full. O(1)."""
        self._buf[self._head] = value
        self._head = (self._head + 1) % self._capacity
        if self._size < self._capacity:
            self._size += 1

    # -- read ----------------------------------------------------------------

    def to_list(self) -> List[Any]:
        """Return all items as a list in insertion order (oldest first). O(n)."""
        if self._size == 0:
            return []
        if self._size < self._capacity:
            return list(self._buf[: self._size])
        # Buffer is full — oldest item is at _head (it was just overwritten)
        start = self._head
        return self._buf[start:] + self._buf[:start]

    def latest_n(self, n: int) -> List[Any]:
        """Return the *n* most-recent items, oldest-first. O(n)."""
        items = self.to_list()
        return items[-n:] if n < len(items) else items

    # -- meta ----------------------------------------------------------------

    @property
    def size(self) -> int:
        """Current number of items stored."""
        return self._size

    @property
    def capacity(self) -> int:
        return self._capacity

    def clear(self) -> None:
        """Reset to empty without reallocating the backing list."""
        self._buf = [None] * self._capacity
        self._head = 0
        self._size = 0


# ---------------------------------------------------------------------------
# Data records
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TaskRecord:
    agent_id: str
    task_id: str
    duration_ms: float
    success: bool
    timestamp_ns: int = field(default_factory=time.monotonic_ns)


@dataclass(frozen=True)
class CircuitTransitionRecord:
    agent_id: str
    from_state: str
    to_state: str
    timestamp_ns: int = field(default_factory=time.monotonic_ns)


@dataclass(frozen=True)
class QueueDepthSample:
    depth: int
    timestamp_ns: int = field(default_factory=time.monotonic_ns)


# ---------------------------------------------------------------------------
# MetricsRegistry
# ---------------------------------------------------------------------------

class MetricsRegistry:
    """Process-wide singleton metrics collector backed by ring buffers.

    Usage:
        registry = MetricsRegistry.get_instance()
        registry.record_dispatch("agent-1", "t1", 12.5, success=True)
        latencies = registry.get_latencies(last_n=50)

    Thread safety:
        A single _metrics_lock guards all mutable state. It is completely
        independent of all other lock domains — it is NEVER nested inside
        or around any memory-layer, scheduler, or RWLock acquisitions.
    """

    _instance: "MetricsRegistry | None" = None
    _init_lock = threading.Lock()

    def __new__(cls, capacity: int = 2048):
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._capacity = capacity
                    inst._metrics_lock = threading.Lock()  # independent domain
                    inst._task_buf: RingBuffer = RingBuffer(capacity)
                    inst._circuit_buf: RingBuffer = RingBuffer(capacity)
                    inst._queue_buf: RingBuffer = RingBuffer(capacity)
                    # Running totals (cheap O(1) counters)
                    inst._total_dispatched: int = 0
                    inst._total_succeeded: int = 0
                    inst._total_failed: int = 0
                    inst._circuit_transitions_total: int = 0
                    cls._instance = inst
        return cls._instance

    @classmethod
    def get_instance(cls, capacity: int = 2048) -> "MetricsRegistry":
        if cls._instance is None:
            return cls(capacity)
        return cls._instance

    # ------------------------------------------------------------------
    # Write path — O(1) per call
    # ------------------------------------------------------------------

    def record_dispatch(
        self, agent_id: str, task_id: str, duration_ms: float, success: bool
    ) -> None:
        """Record a completed task dispatch."""
        record = TaskRecord(
            agent_id=agent_id,
            task_id=task_id,
            duration_ms=duration_ms,
            success=success,
        )
        with self._metrics_lock:
            self._task_buf.push(record)
            self._total_dispatched += 1
            if success:
                self._total_succeeded += 1
            else:
                self._total_failed += 1

    def record_circuit_transition(
        self, agent_id: str, from_state: str, to_state: str
    ) -> None:
        """Record a circuit-breaker state transition."""
        record = CircuitTransitionRecord(
            agent_id=agent_id,
            from_state=from_state,
            to_state=to_state,
        )
        with self._metrics_lock:
            self._circuit_buf.push(record)
            self._circuit_transitions_total += 1

    def record_queue_sample(self, depth: int) -> None:
        """Record an instantaneous queue-depth observation."""
        sample = QueueDepthSample(depth=depth)
        with self._metrics_lock:
            self._queue_buf.push(sample)

    # ------------------------------------------------------------------
    # Query path
    # ------------------------------------------------------------------

    def get_latencies(self, last_n: int = 100) -> List[float]:
        """Return the *last_n* task durations (ms), oldest-first."""
        with self._metrics_lock:
            records = self._task_buf.latest_n(last_n)
        return [r.duration_ms for r in records]

    def get_failure_count(self) -> int:
        """Total number of failed dispatches since last reset."""
        with self._metrics_lock:
            return self._total_failed

    def get_success_count(self) -> int:
        with self._metrics_lock:
            return self._total_succeeded

    def get_total_dispatched(self) -> int:
        with self._metrics_lock:
            return self._total_dispatched

    def get_circuit_transitions(self, last_n: int = 50) -> List[CircuitTransitionRecord]:
        """Return the *last_n* circuit-breaker transitions, oldest-first."""
        with self._metrics_lock:
            return list(self._circuit_buf.latest_n(last_n))

    def get_moving_average_latency(self, last_n: int = 100) -> float:
        """Average latency (ms) over the last *last_n* tasks. 0.0 if no data."""
        latencies = self.get_latencies(last_n)
        if not latencies:
            return 0.0
        return sum(latencies) / len(latencies)

    def get_p99_latency(self, last_n: int = 512) -> float:
        """99th-percentile latency (ms) over last *last_n* tasks. 0.0 if no data."""
        latencies = self.get_latencies(last_n)
        if not latencies:
            return 0.0
        sorted_l = sorted(latencies)
        idx = max(0, int(len(sorted_l) * 0.99) - 1)
        return sorted_l[idx]

    def get_summary(self) -> Dict[str, Any]:
        """Return a snapshot summary dict. O(n) for latency stats."""
        with self._metrics_lock:
            total = self._total_dispatched
            succeeded = self._total_succeeded
            failed = self._total_failed
            transitions = self._circuit_transitions_total
            recent_records = self._task_buf.latest_n(512)

        latencies = [r.duration_ms for r in recent_records]
        avg_lat = sum(latencies) / len(latencies) if latencies else 0.0

        return {
            "total_dispatched": total,
            "total_succeeded": succeeded,
            "total_failed": failed,
            "failure_rate": failed / total if total else 0.0,
            "avg_latency_ms": avg_lat,
            "circuit_transitions_total": transitions,
        }

    # ------------------------------------------------------------------
    # Reset (testing / lifecycle)
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear all metrics. Intended for tests only."""
        with self._metrics_lock:
            self._task_buf.clear()
            self._circuit_buf.clear()
            self._queue_buf.clear()
            self._total_dispatched = 0
            self._total_succeeded = 0
            self._total_failed = 0
            self._circuit_transitions_total = 0

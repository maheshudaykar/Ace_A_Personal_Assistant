"""Phase 3A Gate 2.2 — Deterministic replay validation under concurrent execution.

Tests that:
1. GlobalEventSequence produces strictly monotonic IDs under concurrent record() calls.
2. The GoldenTrace events captured during concurrent execution, when replayed via
   DeterminismValidator.extract_memory_snapshot(), produce a snapshot that matches
   the actual final state of the memory store — no divergence.
3. Replay is idempotent: replaying the same trace twice produces the same result.
4. Concurrent record() + archive_entries() events are totally ordered (no ties in
   sequence_id, even from different threads).
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import List
from uuid import UUID

import pytest

from ace.ace_diagnostics.evaluation_engine import EvaluationEngine
from ace.ace_kernel.audit_trail import AuditTrail
from ace.ace_memory.episodic_memory import EpisodicMemory
from ace.ace_memory.memory_schema import MemoryType
from ace.ace_memory.memory_store import MemoryStore
from ace.ace_memory.quality_scorer import QualityScorer
from ace.runtime import runtime_config
from ace.runtime.determinism_validator import DeterminismValidator
from ace.runtime.event_sequence import GlobalEventSequence
from ace.runtime.golden_trace import EventType, GoldenTrace


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_trace_state():
    """Reset GoldenTrace and GlobalEventSequence before each test."""
    GlobalEventSequence.get_instance().reset()
    GoldenTrace.get_instance().reset()
    yield
    GoldenTrace.get_instance().reset()
    GlobalEventSequence.get_instance().reset()


@pytest.fixture
def trace_enabled(monkeypatch):
    """Enable tracing for the duration of the test."""
    monkeypatch.setattr(runtime_config, "TRACE_ENABLED", True)
    yield


@pytest.fixture
def audit_trail(tmp_path: Path) -> AuditTrail:
    return AuditTrail(tmp_path / "audit.jsonl")


@pytest.fixture
def memory_store(tmp_path: Path, audit_trail: AuditTrail) -> MemoryStore:
    return MemoryStore(tmp_path / "memory.jsonl", audit_trail=audit_trail)


@pytest.fixture
def quality_scorer() -> QualityScorer:
    return QualityScorer(EvaluationEngine())


@pytest.fixture
def episodic(memory_store: MemoryStore, quality_scorer: QualityScorer, audit_trail: AuditTrail) -> EpisodicMemory:
    return EpisodicMemory(memory_store, quality_scorer=quality_scorer, audit_trail=audit_trail)


# ---------------------------------------------------------------------------
# Test 1: sequence IDs are strictly monotonic under concurrency
# ---------------------------------------------------------------------------

class TestConcurrentSequenceOrdering:
    """GlobalEventSequence total order holds under 8 concurrent threads."""

    def test_sequence_ids_strictly_monotonic_concurrent(self, trace_enabled) -> None:
        """
        8 threads each call record() 10 times.
        The resulting RECORD_ENTRY events must have unique, strictly increasing sequence_ids.
        """
        THREADS = 8
        RECORDS_PER_THREAD = 10

        def write_tasks(task_id: str, tmp_path: Path) -> None:
            audit = AuditTrail(tmp_path / f"audit_{task_id}.jsonl")
            store = MemoryStore(tmp_path / f"mem_{task_id}.jsonl", audit_trail=audit)
            scorer = QualityScorer(EvaluationEngine())
            mem = EpisodicMemory(store, quality_scorer=scorer, audit_trail=audit)
            for i in range(RECORDS_PER_THREAD):
                mem.record(task_id=task_id, content=f"entry-{i}", importance_score=0.9)

        import tempfile
        tmp = Path(tempfile.mkdtemp())
        threads = [
            threading.Thread(target=write_tasks, args=(f"task-{i}", tmp), daemon=True)
            for i in range(THREADS)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        # Collect all events
        events = GoldenTrace.get_instance().get_all_events()
        record_events = [e for e in events if e.event_type == EventType.RECORD_ENTRY]

        # Must have captured all records
        assert len(record_events) == THREADS * RECORDS_PER_THREAD, (
            f"Expected {THREADS * RECORDS_PER_THREAD} RECORD_ENTRY events, "
            f"got {len(record_events)}"
        )

        # Sequence IDs must be unique (no two events share a sequence_id)
        seq_ids = [e.sequence_id for e in record_events]
        assert len(seq_ids) == len(set(seq_ids)), "Duplicate sequence_ids found"

        # Sequence IDs must be strictly increasing when sorted
        sorted_ids = sorted(seq_ids)
        for prev, curr in zip(sorted_ids, sorted_ids[1:]):
            assert curr == prev + 1 or curr > prev, f"Gap or non-monotonic: {prev} -> {curr}"


# ---------------------------------------------------------------------------
# Test 2: replay matches actual final memory state (no divergence)
# ---------------------------------------------------------------------------

class TestReplayMatchesActualState:
    """DeterminismValidator snapshot must match the real memory store final state."""

    def test_replay_matches_store_after_concurrent_ops(
        self,
        episodic: EpisodicMemory,
        memory_store: MemoryStore,
        trace_enabled,
    ) -> None:
        """
        Perform concurrent record() + archive_entries() with TRACE_ENABLED.
        Extract snapshot from trace events.
        Query actual store for ground truth.
        Assert they agree on active_count and archived_count.
        """
        THREADS = 4
        RECORDS_PER_THREAD = 8
        all_ids: List[UUID] = []
        ids_lock = threading.Lock()

        def recorder(task_id: str) -> None:
            for i in range(RECORDS_PER_THREAD):
                entry = episodic.record(
                    task_id=task_id,
                    content=f"content-{task_id}-{i}",
                    importance_score=0.9,
                )
                if entry is not None:
                    with ids_lock:
                        all_ids.append(entry.id)

        # Phase 1: record from multiple threads
        threads = [
            threading.Thread(target=recorder, args=(f"task-{i}",), daemon=True)
            for i in range(THREADS)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        # Phase 2: archive some entries (single-threaded, deterministic)
        with ids_lock:
            to_archive = list(all_ids[:6])
        if to_archive:
            episodic.archive_entries(to_archive)

        # ---- Ground truth from actual store ----
        all_entries = memory_store.load_all()
        actual_active_ids = {
            str(e.id) for e in all_entries
            if not e.archived and e.memory_type == MemoryType.EPISODIC
        }
        actual_archived_ids = {
            str(e.id) for e in all_entries
            if e.archived and e.memory_type == MemoryType.EPISODIC
        }

        # ---- Snapshot from trace replay ----
        events = GoldenTrace.get_instance().get_all_events()
        validator = DeterminismValidator()
        sorted_trace = validator.load_trace(events)
        snapshot = validator.extract_memory_snapshot(sorted_trace)

        # Counts must agree
        assert snapshot["active_count"] == len(actual_active_ids), (
            f"Replay active_count={snapshot['active_count']} "
            f"but store active_count={len(actual_active_ids)}"
        )
        assert snapshot["archived_count"] == len(actual_archived_ids), (
            f"Replay archived_count={snapshot['archived_count']} "
            f"but store archived_count={len(actual_archived_ids)}"
        )

        # Active IDs must match exactly
        assert snapshot["active_ids"] == actual_active_ids, (
            "Replay active_ids diverged from actual store"
        )


# ---------------------------------------------------------------------------
# Test 3: replay is idempotent
# ---------------------------------------------------------------------------

class TestReplayIdempotency:
    """Replaying the same trace twice must produce identical snapshots."""

    def test_replay_is_idempotent(
        self,
        episodic: EpisodicMemory,
        trace_enabled,
    ) -> None:
        """Two consecutive replays of the same trace produce the same output."""
        for i in range(5):
            episodic.record(task_id="task-idem", content=f"entry-{i}", importance_score=0.9)

        events = GoldenTrace.get_instance().get_all_events()
        validator = DeterminismValidator()
        sorted_trace = validator.load_trace(events)

        snap1 = validator.extract_memory_snapshot(sorted_trace)
        snap2 = validator.extract_memory_snapshot(sorted_trace)

        is_valid, mismatches = validator.validate_determinism(snap1, snap2)
        assert is_valid, f"Idempotency failed: {mismatches}"


# ---------------------------------------------------------------------------
# Test 4: total ordering — no two events share a sequence_id
# ---------------------------------------------------------------------------

class TestTotalOrdering:
    """All events captured across concurrent threads must have unique sequence_ids."""

    def test_total_order_no_ties(
        self,
        trace_enabled,
    ) -> None:
        """
        4 threads do mixed record() + archive_entries() operations.
        All produced events must have globally unique, non-repeating sequence_ids.
        """
        import tempfile

        THREADS = 4
        RECORDS = 6

        def do_ops(task_id: str, tmp_dir: Path) -> None:
            audit = AuditTrail(tmp_dir / f"audit_{task_id}.jsonl")
            store = MemoryStore(tmp_dir / f"mem_{task_id}.jsonl", audit_trail=audit)
            scorer = QualityScorer(EvaluationEngine())
            mem = EpisodicMemory(store, quality_scorer=scorer, audit_trail=audit)
            recorded_ids = []
            for i in range(RECORDS):
                entry = mem.record(task_id=task_id, content=f"c-{i}", importance_score=0.9)
                if entry:
                    recorded_ids.append(entry.id)
            if len(recorded_ids) >= 2:
                mem.archive_entries(recorded_ids[:2])

        tmp = Path(tempfile.mkdtemp())
        threads = [
            threading.Thread(target=do_ops, args=(f"task-{i}", tmp), daemon=True)
            for i in range(THREADS)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        events = GoldenTrace.get_instance().get_all_events()
        seq_ids = [e.sequence_id for e in events]

        assert len(seq_ids) == len(set(seq_ids)), (
            f"Duplicate sequence_ids found among {len(seq_ids)} events"
        )
        assert sorted(seq_ids) == list(range(1, len(seq_ids) + 1)), (
            "Sequence IDs are not contiguous starting from 1 — "
            "gap detected in total ordering"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

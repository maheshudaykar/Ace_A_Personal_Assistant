"""Phase 3A Gate 2 — RWLock integration and deadlock-safety tests.

Five test scenarios:
1. write_blocks_concurrent_read          — write-lock held; reader blocks until writer releases.
2. multiple_concurrent_reads_allowed     — N readers co-exist without blocking each other.
3. write_lock_timeout_on_write_contention — second writer times out while first holds write-lock.
4. read_lock_timeout_on_write_contention  — reader times out while writer holds write-lock.
5. no_deadlock_concurrent_record_archive  — concurrent record() + archive_entries() on real
                                            EpisodicMemory complete without deadlock.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import List
from uuid import UUID

import pytest

from ace.ace_diagnostics.evaluation_engine import EvaluationEngine
from ace.ace_kernel.audit_trail import AuditTrail
from ace.ace_memory.episodic_memory import EpisodicMemory
from ace.ace_memory.memory_store import MemoryStore
from ace.ace_memory.quality_scorer import QualityScorer
from ace.runtime.rwlock import RWLock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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
# Scenario 1: write-lock blocks concurrent readers until released
# ---------------------------------------------------------------------------

class TestWriteBlocksRead:
    """A held write-lock must prevent readers from progressing."""

    def test_write_blocks_concurrent_read(self) -> None:
        lock = RWLock()
        read_entered = threading.Event()
        write_released = threading.Event()
        read_completed = threading.Event()

        def writer() -> None:
            with lock.write_locked():
                # Signal that write-lock is held, then park briefly.
                time.sleep(0.05)  # hold write for 50 ms
            write_released.set()

        def reader() -> None:
            # Try to enter read-lock; should block until writer finishes.
            with lock.read_locked():
                read_entered.set()
                read_completed.set()

        t_w = threading.Thread(target=writer, daemon=True)
        t_r = threading.Thread(target=reader, daemon=True)

        t_w.start()
        time.sleep(0.01)  # ensure writer acquires first
        t_r.start()

        # Reader should NOT enter while write-lock is held.
        assert not read_entered.wait(timeout=0.02), (
            "reader should be blocked while write-lock is held"
        )

        t_w.join(timeout=1.0)
        assert write_released.wait(timeout=1.0), "writer did not finish"

        # Now reader should proceed.
        assert read_completed.wait(timeout=1.0), "reader did not complete after write release"

        t_r.join(timeout=1.0)


# ---------------------------------------------------------------------------
# Scenario 2: multiple concurrent readers are allowed
# ---------------------------------------------------------------------------

class TestConcurrentReads:
    """Multiple threads must be able to hold the read-lock simultaneously."""

    def test_multiple_concurrent_reads_allowed(self) -> None:
        lock = RWLock()
        READERS = 8
        barrier = threading.Barrier(READERS)
        errors: List[str] = []

        def reader(idx: int) -> None:
            with lock.read_locked(timeout=2.0):
                # All readers synchronize at the barrier — only possible if
                # they can hold the lock concurrently.
                try:
                    barrier.wait(timeout=2.0)
                except threading.BrokenBarrierError:
                    errors.append(f"reader {idx}: barrier broken (readers did not overlap)")

        threads = [threading.Thread(target=reader, args=(i,), daemon=True) for i in range(READERS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=3.0)

        assert not errors, f"Concurrent read failures: {errors}"
        assert lock.reader_count() == 0, "lock not fully released after all readers finished"


# ---------------------------------------------------------------------------
# Scenario 3: write-lock timeout when another write-lock is held
# ---------------------------------------------------------------------------

class TestWriteTimeoutOnWriteContention:
    """A second write-lock attempt must time out when the first is still held."""

    def test_write_lock_timeout_on_write_contention(self) -> None:
        lock = RWLock()
        first_write_held = threading.Event()
        second_write_result: List[bool] = []
        second_write_exception: List[Exception] = []

        def first_writer() -> None:
            with lock.write_locked():
                first_write_held.set()
                time.sleep(0.3)  # hold for 300 ms

        def second_writer() -> None:
            # Wait until first writer is holding the lock.
            first_write_held.wait(timeout=1.0)
            try:
                with lock.write_locked(timeout=0.05):  # timeout after 50 ms
                    second_write_result.append(True)
            except TimeoutError:
                second_write_result.append(False)
                second_write_exception.append(TimeoutError())

        t1 = threading.Thread(target=first_writer, daemon=True)
        t2 = threading.Thread(target=second_writer, daemon=True)

        t1.start()
        t2.start()
        t1.join(timeout=1.0)
        t2.join(timeout=1.0)

        assert len(second_write_result) == 1
        assert second_write_result[0] is False, (
            "second write-lock should have timed out while first was held"
        )
        assert len(second_write_exception) == 1, "expected TimeoutError"


# ---------------------------------------------------------------------------
# Scenario 4: read-lock timeout when write-lock is held
# ---------------------------------------------------------------------------

class TestReadTimeoutOnWriteContention:
    """A read-lock attempt must time out when a write-lock is held."""

    def test_read_lock_timeout_on_write_contention(self) -> None:
        lock = RWLock()
        write_held = threading.Event()
        read_result: List[bool] = []

        def writer() -> None:
            with lock.write_locked():
                write_held.set()
                time.sleep(0.3)  # hold for 300 ms

        def reader() -> None:
            write_held.wait(timeout=1.0)
            try:
                with lock.read_locked(timeout=0.05):  # timeout after 50 ms
                    read_result.append(True)
            except TimeoutError:
                read_result.append(False)

        t_w = threading.Thread(target=writer, daemon=True)
        t_r = threading.Thread(target=reader, daemon=True)

        t_w.start()
        t_r.start()
        t_w.join(timeout=1.0)
        t_r.join(timeout=1.0)

        assert len(read_result) == 1
        assert read_result[0] is False, (
            "read-lock should have timed out while write-lock was held"
        )


# ---------------------------------------------------------------------------
# Scenario 5: no deadlock in concurrent record() + archive_entries()
# ---------------------------------------------------------------------------

class TestNoDeadlockEpisodicMemory:
    """Concurrent record() and archive_entries() must not deadlock."""

    def test_no_deadlock_concurrent_record_archive(
        self,
        episodic: EpisodicMemory,
    ) -> None:
        """
        Run 20 record() calls interleaved with archive_entries() calls across 4 threads.
        Must complete within 10 seconds (far above any legitimate runtime).
        If a deadlock exists, the test will time out and fail.
        """
        RECORDS_PER_THREAD = 5
        THREADS = 4
        recorded_ids: List[UUID] = []
        ids_lock = threading.Lock()
        errors: List[str] = []
        done = threading.Event()

        def recorder(task_id: str) -> None:
            for i in range(RECORDS_PER_THREAD):
                entry = episodic.record(
                    task_id=task_id,
                    content=f"content-{task_id}-{i}",
                    importance_score=0.9,
                )
                if entry is not None:
                    with ids_lock:
                        recorded_ids.append(entry.id)

        def archiver() -> None:
            # Wait a moment for some entries to accumulate, then archive.
            time.sleep(0.02)
            with ids_lock:
                ids_to_archive = list(recorded_ids[:5])
            if ids_to_archive:
                try:
                    episodic.archive_entries(ids_to_archive)
                except Exception as exc:
                    errors.append(f"archiver error: {exc}")

        threads = []
        for i in range(THREADS):
            threads.append(threading.Thread(
                target=recorder, args=(f"task-{i}",), daemon=True
            ))
        threads.append(threading.Thread(target=archiver, daemon=True))

        start = time.monotonic()
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)
        elapsed = time.monotonic() - start

        # Sanity checks
        assert not errors, f"Errors during concurrent execution: {errors}"
        assert elapsed < 10.0, f"Test took {elapsed:.2f}s — possible deadlock"

        # All threads must have completed (not still alive).
        still_alive = [t for t in threads if t.is_alive()]
        assert not still_alive, (
            f"{len(still_alive)} thread(s) still alive after 10s — deadlock suspected"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

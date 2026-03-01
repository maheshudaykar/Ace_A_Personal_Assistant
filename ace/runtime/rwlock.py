"""Production read-write lock for ACE Phase 3A.

Writer-preference RWLock:
- Multiple concurrent readers allowed.
- Writers are exclusive (block all readers and other writers).
- Waiting writers block new readers to prevent writer starvation.
- Timeout support for deadlock-safety tests.

Lock domain: EpisodicMemory._indices_rwlock
- Scope: _task_index + _recency_tiers mutations ONLY.
- Never held during: I/O, sleep, logging, event-sequence calls.
- No nesting with any other lock domain.
- No read->write upgrade.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Generator


class RWLock:
    """Read-write lock with writer preference and timeout support.

    Concurrency semantics:
    - Any number of readers may hold the lock simultaneously.
    - Only one writer at a time, exclusive with all readers.
    - When a writer is waiting, new reader acquisitions block
      (writer preference prevents indefinite reader starvation).
    - Timeout on acquire_read / acquire_write returns False without
      raising so callers can choose their error policy.
    """

    def __init__(self) -> None:
        self._cond = threading.Condition(threading.Lock())
        self._readers: int = 0           # active reader count
        self._writers: int = 0           # active writer count (0 or 1)
        self._writers_waiting: int = 0   # writers blocked, not yet active

    # ------------------------------------------------------------------
    # Low-level acquire / release
    # ------------------------------------------------------------------

    def acquire_read(self, timeout: float | None = None) -> bool:
        """Acquire the read-lock.  Returns True on success, False on timeout."""
        deadline = (time.monotonic() + timeout) if timeout is not None else None
        with self._cond:
            while self._writers > 0 or self._writers_waiting > 0:
                remaining = (deadline - time.monotonic()) if deadline is not None else None
                if remaining is not None and remaining <= 0.0:
                    return False
                self._cond.wait(timeout=remaining)
            self._readers += 1
            return True

    def release_read(self) -> None:
        """Release the read-lock held by the calling thread."""
        with self._cond:
            self._readers -= 1
            if self._readers == 0:
                self._cond.notify_all()

    def acquire_write(self, timeout: float | None = None) -> bool:
        """Acquire the write-lock.  Returns True on success, False on timeout."""
        deadline = (time.monotonic() + timeout) if timeout is not None else None
        with self._cond:
            self._writers_waiting += 1
            try:
                while self._readers > 0 or self._writers > 0:
                    remaining = (deadline - time.monotonic()) if deadline is not None else None
                    if remaining is not None and remaining <= 0.0:
                        return False
                    self._cond.wait(timeout=remaining)
                self._writers += 1
                return True
            finally:
                # Always decrement: we either acquired (no longer waiting)
                # or timed out (giving up), in both cases we stop being
                # a waiting writer.
                self._writers_waiting -= 1

    def release_write(self) -> None:
        """Release the write-lock held by the calling thread."""
        with self._cond:
            self._writers -= 1
            self._cond.notify_all()

    # ------------------------------------------------------------------
    # Context-manager API (preferred)
    # ------------------------------------------------------------------

    @contextmanager
    def read_locked(self, timeout: float | None = None) -> Generator[None, None, None]:
        """Context manager that acquires a read-lock on entry.

        Args:
            timeout: Seconds to wait.  None means wait indefinitely.

        Raises:
            TimeoutError: If timeout elapses before the lock is acquired.
        """
        if not self.acquire_read(timeout=timeout):
            raise TimeoutError("RWLock read acquire timed out")
        try:
            yield
        finally:
            self.release_read()

    @contextmanager
    def write_locked(self, timeout: float | None = None) -> Generator[None, None, None]:
        """Context manager that acquires a write-lock on entry.

        Args:
            timeout: Seconds to wait.  None means wait indefinitely.

        Raises:
            TimeoutError: If timeout elapses before the lock is acquired.
        """
        if not self.acquire_write(timeout=timeout):
            raise TimeoutError("RWLock write acquire timed out")
        try:
            yield
        finally:
            self.release_write()

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def reader_count(self) -> int:
        """Return current active reader count (for testing/diagnostics)."""
        with self._cond:
            return self._readers

    def writer_count(self) -> int:
        """Return current active writer count (for testing/diagnostics)."""
        with self._cond:
            return self._writers

    def writers_waiting_count(self) -> int:
        """Return count of writers blocked waiting to acquire (for testing)."""
        with self._cond:
            return self._writers_waiting

    def __repr__(self) -> str:
        return (
            f"RWLock(readers={self._readers}, "
            f"writers={self._writers}, "
            f"writers_waiting={self._writers_waiting})"
        )

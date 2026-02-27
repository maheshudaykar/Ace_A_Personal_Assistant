"""Working memory ring buffer - short-lived task context."""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Union

from ace.ace_memory.memory_schema import MemoryEntry, MemoryType


@dataclass(slots=True)
class WorkingEntry:
    """Lightweight working-memory entry."""

    task_id: str
    content: str
    importance_score: float
    timestamp: datetime
    memory_type: str = MemoryType.WORKING.value


class WorkingMemory:
    """Thread-safe ring buffer for short-term task context."""

    def __init__(self, max_capacity: int = 10) -> None:
        if max_capacity <= 0:
            raise ValueError("max_capacity must be positive")
        self._buffer: deque[Union[MemoryEntry, WorkingEntry]] = deque(maxlen=max_capacity)
        self._lock = threading.Lock()

    def add(self, entry: MemoryEntry) -> None:
        """Add entry to working memory (oldest evicted if at capacity)."""
        if entry.memory_type != MemoryType.WORKING:
            entry.memory_type = MemoryType.WORKING
        
        with self._lock:
            self._buffer.append(entry)

    def add_raw(self, task_id: str, content: str, importance_score: float = 0.4) -> None:
        """Add a lightweight working-memory entry."""
        entry = WorkingEntry(
            task_id=task_id,
            content=content,
            importance_score=importance_score,
            timestamp=datetime.now(timezone.utc),
        )
        with self._lock:
            self._buffer.append(entry)

    def get_all(self) -> List[Union[MemoryEntry, WorkingEntry]]:
        """Retrieve all current working memory entries."""
        with self._lock:
            return list(self._buffer)

    def clear(self) -> None:
        """Clear working memory (called after task completion)."""
        with self._lock:
            self._buffer.clear()

    def size(self) -> int:
        """Return current buffer size."""
        with self._lock:
            return len(self._buffer)

"""Episodic memory - task-level persistent storage with write gating."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List
from uuid import UUID

from ace.ace_memory.memory_schema import MemoryEntry, MemoryType
from ace.ace_memory.memory_store import MemoryStore

if TYPE_CHECKING:
    from ace.ace_memory.quality_scorer import QualityScorer


class EpisodicMemory:
    """Task-level persistent memory storage with write gating optimization."""

    def __init__(self, memory_store: MemoryStore, write_threshold: float = 0.5) -> None:
        """
        Initialize episodic memory with write gating.
        
        Args:
            memory_store: Persistent storage backend
            write_threshold: Minimum importance score to persist (FluxMem pattern)
        """
        self._store = memory_store
        self._write_threshold = write_threshold
        self._filtered_count = 0  # Track how many entries were filtered
        
        # Retrieval statistics (no behavioral changes)
        self._stats: Dict[str, Any] = {
            "total_by_task": 0,
            "total_all_active": 0,
            "total_top_k": 0,
            "latency_by_task_ms": [],
            "latency_all_active_ms": [],
            "latency_top_k_ms": [],
        }

    def record(
        self,
        task_id: str,
        content: str,
        importance_score: float = 0.5,
        embedding: List[float] | None = None,
        validate: bool = True,
    ) -> MemoryEntry | None:
        """
        Record a new episodic memory entry with write gating.
        
        Only persists entries above the importance threshold (FluxMem pattern).
        Low-importance entries should remain in working memory only.
        
        Args:
            task_id: Unique task identifier
            content: Memory content
            importance_score: Importance rating (0-1)
            embedding: Optional embedding vector
            validate: Whether to validate with Pydantic
        
        Returns:
            MemoryEntry if persisted, None if filtered by write gate
        """
        # Write gating: only persist high-importance entries
        if importance_score < self._write_threshold:
            self._filtered_count += 1
            return None
        
        if validate:
            entry = MemoryEntry(
                task_id=task_id,
                content=content,
                importance_score=importance_score,
                embedding=embedding,
                memory_type=MemoryType.EPISODIC,
                timestamp=datetime.now(timezone.utc),
            )
        else:
            entry = MemoryEntry.model_construct(
                task_id=task_id,
                content=content,
                importance_score=importance_score,
                embedding=embedding,
                memory_type=MemoryType.EPISODIC,
                timestamp=datetime.now(timezone.utc),
                access_count=0,
                last_accessed=datetime.now(timezone.utc),
                archived=False,
            )
        
        self._store.save(entry)
        return entry

    def retrieve_by_task(self, task_id: str) -> List[MemoryEntry]:
        """Retrieve all episodic memories for a specific task."""
        start_time = time.perf_counter()
        
        entries = self._store.load_by_task(task_id)
        
        # Update access tracking for retrieved entries
        for entry in entries:
            if entry.memory_type == MemoryType.EPISODIC and not entry.archived:
                entry.update_access()
                self._store.save(entry)
        
        # Track statistics
        latency_ms = (time.perf_counter() - start_time) * 1000.0
        self._stats["total_by_task"] += 1
        self._stats["latency_by_task_ms"].append(latency_ms)
        
        return entries

    def retrieve_all_active(self) -> List[MemoryEntry]:
        """Retrieve all non-archived episodic memories."""
        start_time = time.perf_counter()
        
        result = [
            entry for entry in self._store.load_active()
            if entry.memory_type == MemoryType.EPISODIC
        ]
        
        # Track statistics
        latency_ms = (time.perf_counter() - start_time) * 1000.0
        self._stats["total_all_active"] += 1
        self._stats["latency_all_active_ms"].append(latency_ms)
        
        return result

    def retrieve_top_k(self, scorer: QualityScorer, k: int = 10) -> List[MemoryEntry]:
        """
        Retrieve top-K entries by quality score (bounded context - CogMem pattern).
        
        This is significantly faster than retrieve_all_active() when memory
        is large, as it limits the context window to the most relevant entries.
        
        Args:
            scorer: Quality scorer instance
            k: Maximum number of entries to return
        
        Returns:
            Top-K entries sorted by quality score (descending)
        """
        start_time = time.perf_counter()
        
        # Use score_batch for efficiency (single datetime.now() call)
        all_entries = [
            entry for entry in self._store.load_active()
            if entry.memory_type == MemoryType.EPISODIC
        ]
        
        # Batch score all entries
        scored = scorer.score_batch(all_entries)
        
        # Sort by score descending and take top-K
        scored.sort(key=lambda x: x[1], reverse=True)
        
        # Track statistics
        latency_ms = (time.perf_counter() - start_time) * 1000.0
        self._stats["total_top_k"] += 1
        self._stats["latency_top_k_ms"].append(latency_ms)
        
        return [entry for entry, _score in scored[:k]]

    def archive_entries(self, entry_ids: List[UUID]) -> int:
        """Archive episodic entries (delegate to store)."""
        return self._store.prune(entry_ids)
    
    def get_filtered_count(self) -> int:
        """Return number of entries filtered by write gating."""
        return self._filtered_count

    def get_statistics(self) -> Dict[str, float]:
        """Get retrieval statistics."""
        def avg(values: List[float]) -> float:
            return sum(values) / len(values) if values else 0.0
        
        return {
            "total_by_task_calls": self._stats["total_by_task"],
            "total_all_active_calls": self._stats["total_all_active"],
            "total_top_k_calls": self._stats["total_top_k"],
            "avg_latency_by_task_ms": avg(self._stats["latency_by_task_ms"]),
            "avg_latency_all_active_ms": avg(self._stats["latency_all_active_ms"]),
            "avg_latency_top_k_ms": avg(self._stats["latency_top_k_ms"]),
        }


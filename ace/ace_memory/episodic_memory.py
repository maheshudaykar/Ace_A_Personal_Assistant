"""Episodic memory - task-level persistent storage with hierarchical indexing."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Set
from uuid import UUID

from ace.ace_memory.memory_schema import MemoryEntry, MemoryType
from ace.ace_memory.memory_store import MemoryStore

if TYPE_CHECKING:
    from ace.ace_memory.quality_scorer import QualityScorer


class EpisodicMemory:
    """
    Task-level persistent memory storage with hierarchical indexing for scalable retrieval.
    
    Indices:
    - Task index: Maps task_id -> Set[UUID] for quick per-task lookup
    - Recency tiers: Hot (<7d), Warm (7-30d), Cold (>30d) for efficient top-K search
    """

    def __init__(self, memory_store: MemoryStore, write_threshold: float = 0.5) -> None:
        """
        Initialize episodic memory with hierarchical indexing.
        
        Args:
            memory_store: Persistent storage backend
            write_threshold: Minimum importance score to persist (FluxMem pattern)
        """
        self._store = memory_store
        self._write_threshold = write_threshold
        self._filtered_count = 0
        
        # Hierarchical indices (Phase 2B)
        self._task_index: Dict[str, Set[UUID]] = {}  # task_id -> entry IDs
        self._recency_tiers: Dict[str, Set[UUID]] = {
            "hot": set(),    # < 7 days
            "warm": set(),   # 7-30 days
            "cold": set(),   # > 30 days
        }
        
        # Retrieval statistics
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
        Record a new episodic memory entry with write gating and indexing.
        
        Only persists entries above the importance threshold (FluxMem pattern).
        Updates hierarchical indices on success.
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
        
        # Update indices
        self._update_task_index(entry.task_id, entry.id, add=True)
        self._update_recency_tier(entry)

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
        Retrieve top-K entries by quality score using hierarchical indexing.
        
        PHASE 2B Optimization:
        1. Search hot tier first (< 7 days)
        2. If insufficient, include warm tier (7-30 days)
        3. If still insufficient, include cold tier (> 30 days)
        4. Score and rank within selected entries
        5. Return top-K with deterministic tie-breaking by UUID
        """
        start_time = time.perf_counter()
        
        # Start with hot tier entries
        candidates = self._get_entries_by_tier("hot")
        
        # If insufficient, add warm tier
        if len(candidates) < k:
            candidates.extend(self._get_entries_by_tier("warm"))
        
        # If still insufficient, add cold tier
        if len(candidates) < k:
            candidates.extend(self._get_entries_by_tier("cold"))
        
        # Batch score with deterministic ordering
        scored = scorer.score_batch(candidates)
        
        # Sort by score DESC, then by UUID ASC (deterministic tie-breaking)
        scored.sort(key=lambda x: (-x[1], str(x[0].id)))
        
        # Track statistics
        latency_ms = (time.perf_counter() - start_time) * 1000.0
        self._stats["total_top_k"] += 1
        self._stats["latency_top_k_ms"].append(latency_ms)
        
        return [entry for entry, _score in scored[:k]]

    def archive_entries(self, entry_ids: List[UUID]) -> int:
        """Archive episodic entries and update indices."""
        count = self._store.prune(entry_ids)
        
        # Update indices: remove archived entries
        for entry_id in entry_ids:
            # Remove from all recency tiers
            for tier_set in self._recency_tiers.values():
                tier_set.discard(entry_id)
        
        return count

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

    # ========== PHASE 2B: Hierarchical Indexing Support ==========

    def _update_task_index(self, task_id: str, entry_id: UUID, add: bool = True) -> None:
        """Update task-level index."""
        if add:
            if task_id not in self._task_index:
                self._task_index[task_id] = set()
            self._task_index[task_id].add(entry_id)
        else:
            if task_id in self._task_index:
                self._task_index[task_id].discard(entry_id)

    def _update_recency_tier(self, entry: MemoryEntry) -> None:
        """Update recency tier based on entry age."""
        age = (datetime.now(timezone.utc) - entry.timestamp).days
        
        # Remove from all tiers first
        for tier_set in self._recency_tiers.values():
            tier_set.discard(entry.id)
        
        # Add to appropriate tier
        if age < 7:
            self._recency_tiers["hot"].add(entry.id)
        elif age < 30:
            self._recency_tiers["warm"].add(entry.id)
        else:
            self._recency_tiers["cold"].add(entry.id)

    def _get_entries_by_tier(self, tier: str) -> List[MemoryEntry]:
        """Get all non-archived entries from a specific recency tier."""
        if tier not in self._recency_tiers:
            return []
        
        tier_ids = self._recency_tiers[tier]
        all_entries = self._store.load_active()
        
        # Filter to tier IDs, exclude archived
        return [
            e for e in all_entries
            if e.id in tier_ids and e.memory_type == MemoryType.EPISODIC and not e.archived
        ]

    def get_index_stats(self) -> Dict[str, Any]:
        """Get hierarchical index statistics for debugging."""
        return {
            "task_index_size": len(self._task_index),
            "hot_tier_count": len(self._recency_tiers["hot"]),
            "warm_tier_count": len(self._recency_tiers["warm"]),
            "cold_tier_count": len(self._recency_tiers["cold"]),
            "total_indexed": sum(len(tier) for tier in self._recency_tiers.values()),
        }


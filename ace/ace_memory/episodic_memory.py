"""Episodic memory - task-level persistent storage with hierarchical indexing."""

from __future__ import annotations

import time
from collections import deque
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Set
from uuid import UUID

from ace.ace_diagnostics.evaluation_engine import EvaluationEngine
from ace.ace_kernel.audit_trail import AuditTrail
from ace.ace_memory import memory_config
from ace.ace_memory.memory_schema import MemoryEntry, MemoryType
from ace.ace_memory.memory_store import MemoryStore
from ace.ace_memory.quality_scorer import QualityScorer
from ace.runtime.golden_trace import EventType, GoldenTrace
from ace.runtime.rwlock import RWLock

if TYPE_CHECKING:
    from ace.ace_memory.consolidation_engine import ConsolidationEngine


class EpisodicMemory:
    """
    Task-level persistent memory storage with hierarchical indexing for scalable retrieval.

    Indices:
    - Task index: Maps task_id -> Set[UUID] for quick per-task lookup
    - Recency tiers: Hot (<7d), Warm (7-30d), Cold (>30d) for efficient top-K search

    Phase 3A Gate 2 locking discipline:
    - _indices_rwlock (RWLock): guards _task_index and _recency_tiers ONLY.
    - Lock is NEVER held during: I/O, quota enforcement, logging, or event-sequence calls.
    - Completely independent domain from MemoryStore._lock and AuditTrail._lock.
    - No read->write upgrades. No nesting.
    """

    def __init__(
        self,
        memory_store: MemoryStore,
        write_threshold: float = 0.5,
        quality_scorer: QualityScorer | None = None,
        audit_trail: AuditTrail | None = None,
    ) -> None:
        """
        Initialize episodic memory with hierarchical indexing.

        Args:
            memory_store: Persistent storage backend
            write_threshold: Minimum importance score to persist (FluxMem pattern)
        """
        self._store = memory_store
        self._write_threshold = write_threshold
        self._filtered_count = 0
        self._audit = audit_trail
        self._scorer = quality_scorer or QualityScorer(EvaluationEngine())
        self._consolidation_engine: ConsolidationEngine | None = None
        self._record_timestamps: deque[float] = deque()

        # Hierarchical indices (Phase 2B)
        self._task_index: Dict[str, Set[UUID]] = {}  # task_id -> entry IDs
        self._recency_tiers: Dict[str, Set[UUID]] = {
            "hot": set(),    # < 7 days
            "warm": set(),   # 7-30 days
            "cold": set(),   # > 30 days
        }
        # Phase 3A Gate 2: RWLock for index isolation.
        # Scope: _task_index + _recency_tiers mutations ONLY.
        # Never held during: I/O, logging, quota enforcement, event-sequence calls.
        # Completely independent domain — never nested with MemoryStore._lock or AuditTrail._lock.
        self._indices_rwlock = RWLock()

        # Phase 2C incremental counters (performance optimization)
        self._total_count = 0
        self._active_count = 0
        self._archived_count = 0
        self._task_counts: Dict[str, int] = {}
        self._compaction_pending = False
        self._initialize_counters()

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

        Phase 3A Gate 2: index mutations are protected by _indices_rwlock (write-lock).
        Lock is acquired AFTER I/O completes and released BEFORE quota enforcement
        and BEFORE Gate 1.5 trace logging.
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

        # I/O outside lock (MemoryStore manages its own Level-2 lock).
        self._store.save(entry)

        # Phase 3A Gate 2: write-lock covers ONLY in-memory index + counter mutations.
        # Released BEFORE quota enforcement (which may call archive_entries -> write-lock again).
        # Released BEFORE logging (independent lock domain).
        with self._indices_rwlock.write_locked():
            self._update_task_index(entry.task_id, entry.id, add=True)
            self._update_recency_tier(entry)
            # Phase 2C incremental counter updates — inside lock to stay consistent with index.
            self._total_count += 1
            self._active_count += 1
            self._task_counts[entry.task_id] = self._task_counts.get(entry.task_id, 0) + 1

        # Phase 2C hardening — OUTSIDE lock (quota enforcement may call archive_entries
        # which needs write-lock; holding write-lock here would deadlock).
        self._enforce_per_task_cap_if_needed(entry.task_id)
        self._enforce_total_quota_if_needed()
        self._enforce_active_quota_if_needed()
        self._track_growth_spike()

        # Gate 1.5: log state mutation OUTSIDE lock and OUTSIDE I/O.
        GoldenTrace.get_instance().log_event(
            EventType.RECORD_ENTRY,
            {
                "entry_id": str(entry.id),
                "task_id": entry.task_id,
                "importance_score": entry.importance_score,
            },
        )

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

        PHASE 3A Gate 2: Read-lock acquires tier-ID snapshots, released before all I/O.
        """
        start_time = time.perf_counter()

        # Phase 3A Gate 2: read-lock to snapshot tier IDs (no I/O while locked).
        with self._indices_rwlock.read_locked():
            hot_ids = frozenset(self._recency_tiers["hot"])
            warm_ids = frozenset(self._recency_tiers["warm"])
            cold_ids = frozenset(self._recency_tiers["cold"])

        # I/O and scoring OUTSIDE lock using the snapshotted ID sets.
        candidates = self._get_entries_by_tier("hot", hot_ids)

        # If insufficient, add warm tier
        if len(candidates) < k:
            candidates.extend(self._get_entries_by_tier("warm", warm_ids))

        # If still insufficient, add cold tier
        if len(candidates) < k:
            candidates.extend(self._get_entries_by_tier("cold", cold_ids))

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
        """Archive episodic entries and update indices.

        Phase 3A Gate 2: index mutations are protected by _indices_rwlock (write-lock).
        Lock is acquired AFTER all I/O completes and released BEFORE compaction flag
        and BEFORE Gate 1.5 trace logging.
        """
        # I/O outside lock (MemoryStore manages its own Level-2 lock).
        all_entries = self._store.load_all()
        entry_task_map = {entry.id: (entry.task_id, entry.archived) for entry in all_entries}

        count = self._store.prune(entry_ids)

        # Phase 3A Gate 2: write-lock for index + counter mutations ONLY.
        # Released BEFORE compaction check and BEFORE logging.
        with self._indices_rwlock.write_locked():
            for entry_id in entry_ids:
                # Remove from all recency tiers
                for tier_set in self._recency_tiers.values():
                    tier_set.discard(entry_id)

                task_info = entry_task_map.get(entry_id)
                if task_info is not None:
                    task_id, was_archived = task_info
                    self._update_task_index(task_id, entry_id, add=False)
                    if task_id in self._task_index and not self._task_index[task_id]:
                        del self._task_index[task_id]

                    # Update counters only for newly archived entries
                    if not was_archived:
                        self._active_count -= 1
                        self._archived_count += 1
                        if task_id in self._task_counts:
                            self._task_counts[task_id] -= 1
                            if self._task_counts[task_id] == 0:
                                del self._task_counts[task_id]

        # Compaction flag and Gate 1.5 logging OUTSIDE lock.
        if self._archived_count > 0 and (self._archived_count / max(self._total_count, 1)) > 0.30:
            self._compaction_pending = True

        # Gate 1.5: log archive event OUTSIDE lock
        GoldenTrace.get_instance().log_event(
            EventType.ARCHIVE_ENTRY,
            {
                "entry_ids": sorted([str(eid) for eid in entry_ids]),
                "count": count,
            },
        )

        return count

    def set_consolidation_engine(self, engine: ConsolidationEngine) -> None:
        """Attach a consolidation engine for active quota enforcement."""
        self._consolidation_engine = engine

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

    # ========== PHASE 2C: Quota + Growth Governance ==========

    def _initialize_counters(self) -> None:
        """Initialize incremental counters from store state (once at startup)."""
        all_entries = self._store.load_all()
        self._total_count = len(all_entries)
        self._active_count = sum(1 for e in all_entries if not e.archived)
        self._archived_count = sum(1 for e in all_entries if e.archived)
        self._task_counts.clear()
        for entry in all_entries:
            if not entry.archived and entry.memory_type == MemoryType.EPISODIC:
                self._task_counts[entry.task_id] = self._task_counts.get(entry.task_id, 0) + 1

    def _enforce_per_task_cap_if_needed(self, task_id: str) -> int:
        """Enforce per-task cap only when threshold is crossed."""
        task_count = self._task_counts.get(task_id, 0)
        max_per_task = memory_config.MAX_ENTRIES_PER_TASK
        if task_count <= max_per_task:
            return 0
        return self._enforce_per_task_cap(task_id)

    def _enforce_per_task_cap(self, task_id: str) -> int:
        """Archive lowest-quality active entries if a task exceeds hard cap."""
        task_entries = [
            entry for entry in self._store.load_by_task(task_id)
            if not entry.archived and entry.memory_type == MemoryType.EPISODIC
        ]

        max_per_task = memory_config.MAX_ENTRIES_PER_TASK
        if len(task_entries) <= max_per_task:
            return 0

        reference_time = datetime.now(timezone.utc)
        scored_entries = self._scorer.score_batch(task_entries, reference_time=reference_time)
        scored_entries.sort(key=lambda item: (item[1], item[0].timestamp, str(item[0].id)))

        to_archive_count = len(task_entries) - max_per_task
        ids_to_archive = [entry.id for entry, _score in scored_entries[:to_archive_count]]
        archived_count = self.archive_entries(ids_to_archive)

        if self._audit is not None and archived_count > 0:
            self._audit.append({
                "type": "memory.per_task_quota_enforced",
                "task_id": task_id,
                "archived_count": archived_count,
                "max_entries_per_task": max_per_task,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        return archived_count

    def _enforce_total_quota_if_needed(self) -> int:
        """Enforce total quota only when threshold is crossed."""
        max_total = memory_config.MAX_TOTAL_ENTRIES
        if self._total_count <= max_total:
            return 0
        return self._enforce_total_quota()

    def _enforce_total_quota(self) -> int:
        """Permanently prune archived entries when total entry quota is exceeded."""
        max_total = memory_config.MAX_TOTAL_ENTRIES
        overflow = self._total_count - max_total
        if overflow <= 0:
            return 0

        deleted_count = self._store.prune_oldest_archived(overflow)
        self._total_count -= deleted_count
        self._archived_count -= deleted_count

        # Trigger compaction if pending
        compacted_count = 0
        if self._compaction_pending:
            compacted_count = self._store.compact_archived_entries()
            self._total_count -= compacted_count
            self._archived_count -= compacted_count
            self._compaction_pending = False

        if self._audit is not None:
            self._audit.append({
                "type": "memory.total_quota_enforced",
                "total_entries": self._total_count + deleted_count,
                "max_total_entries": max_total,
                "overflow": overflow,
                "deleted_archived_count": deleted_count,
                "compacted_archived_count": compacted_count,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        return deleted_count

    def _enforce_active_quota_if_needed(self) -> int:
        """Enforce active quota only when threshold is crossed."""
        max_active = memory_config.MAX_ACTIVE_ENTRIES
        if self._active_count <= max_active:
            return 0
        return self._enforce_active_quota()

    def _enforce_active_quota(self) -> int:
        """Trigger deterministic consolidation pass when active entries exceed quota."""
        max_active = memory_config.MAX_ACTIVE_ENTRIES
        if self._active_count <= max_active:
            return 0

        active_before = self._active_count
        merged_count = self._run_consolidation_pass()

        # Consolidation archives originals and creates new consolidated entries
        # Update counters based on actual consolidation results
        active_after = self._store.count_active_entries()
        self._active_count = active_after
        self._archived_count = self._total_count - self._active_count

        if self._audit is not None:
            self._audit.append({
                "type": "memory.active_quota_enforced",
                "active_entries": active_before,
                "max_active_entries": max_active,
                "merged_count": merged_count,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        return merged_count

    def _run_consolidation_pass(self) -> int:
        """Run one deterministic consolidation pass for quota enforcement."""
        if self._consolidation_engine is not None:
            return self._consolidation_engine.consolidate()

        if self._audit is None:
            return 0

        from ace.ace_memory.consolidation_engine import ConsolidationEngine

        engine = ConsolidationEngine(
            memory_store=self._store,
            episodic_memory=self,
            quality_scorer=self._scorer,
            audit_trail=self._audit,
        )
        return engine.consolidate()

    def _track_growth_spike(self) -> None:
        """Track rolling entries/minute and log observability-only warning on spikes."""
        now_monotonic = time.monotonic()
        self._record_timestamps.append(now_monotonic)

        while self._record_timestamps and (now_monotonic - self._record_timestamps[0]) > 60.0:
            self._record_timestamps.popleft()

        growth_rate = len(self._record_timestamps)
        threshold = memory_config.GROWTH_SPIKE_ENTRIES_PER_MINUTE
        if self._audit is not None and growth_rate > threshold:
            self._audit.append({
                "type": "memory.growth_spike_warning",
                "entries_per_minute": growth_rate,
                "threshold": threshold,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    # ========== PHASE 2B: Hierarchical Indexing Support ==========

    def _update_task_index(self, task_id: str, entry_id: UUID, add: bool = True) -> None:
        """Update task-level index.

        Must be called from within a _indices_rwlock.write_locked() context.
        """
        if add:
            if task_id not in self._task_index:
                self._task_index[task_id] = set()
            self._task_index[task_id].add(entry_id)
        else:
            if task_id in self._task_index:
                self._task_index[task_id].discard(entry_id)

    def _update_recency_tier(self, entry: MemoryEntry) -> None:
        """Update recency tier based on entry age.

        Must be called from within a _indices_rwlock.write_locked() context.
        """
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

    def _get_entries_by_tier(
        self,
        tier: str,
        tier_ids: frozenset | None = None,
    ) -> List[MemoryEntry]:
        """Get all non-archived entries from a specific recency tier.

        Args:
            tier: Tier name ("hot", "warm", "cold").
            tier_ids: Pre-snapshotted frozenset of IDs (caller already released read-lock).
                      When None, reads _recency_tiers directly — only safe in
                      single-threaded contexts.
        """
        if tier_ids is None:
            if tier not in self._recency_tiers:
                return []
            tier_ids = frozenset(self._recency_tiers[tier])

        if not tier_ids:
            return []

        all_entries = self._store.load_active()

        # Filter to tier IDs, exclude archived
        return [
            e for e in all_entries
            if e.id in tier_ids and e.memory_type == MemoryType.EPISODIC and not e.archived
        ]

    def get_index_stats(self) -> Dict[str, Any]:
        """Get hierarchical index statistics for debugging."""
        with self._indices_rwlock.read_locked():
            return {
                "task_index_size": len(self._task_index),
                "hot_tier_count": len(self._recency_tiers["hot"]),
                "warm_tier_count": len(self._recency_tiers["warm"]),
                "cold_tier_count": len(self._recency_tiers["cold"]),
                "total_indexed": sum(len(tier) for tier in self._recency_tiers.values()),
            }

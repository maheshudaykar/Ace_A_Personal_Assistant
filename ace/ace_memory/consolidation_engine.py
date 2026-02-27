"""Memory consolidation engine - merge similar entries."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List
from uuid import uuid4

from ace.ace_kernel.audit_trail import AuditTrail
from ace.ace_memory.episodic_memory import EpisodicMemory
from ace.ace_memory.memory_schema import MemoryEntry, MemoryType
from ace.ace_memory.memory_store import MemoryStore
from ace.ace_memory.quality_scorer import QualityScorer


class ConsolidationEngine:
    """Consolidate and merge similar episodic memories."""

    def __init__(
        self,
        memory_store: MemoryStore,
        episodic_memory: EpisodicMemory,
        quality_scorer: QualityScorer,
        audit_trail: AuditTrail,
    ) -> None:
        self._store = memory_store
        self._episodic = episodic_memory
        self._scorer = quality_scorer
        self._audit = audit_trail

    def should_consolidate(self) -> bool:
        """Check if consolidation trigger conditions are met."""
        active_entries = self._store.load_active()
        episodic_count = sum(1 for e in active_entries if e.memory_type == MemoryType.EPISODIC)
        return episodic_count >= 100

    def consolidate(self, merge_threshold: float = 0.8) -> int:
        """Perform memory consolidation and return count of merged entries."""
        active_entries = self._episodic.retrieve_all_active()
        
        if len(active_entries) == 0:
            return 0

        # Score all entries
        scored_entries = [(entry, self._scorer.score(entry)) for entry in active_entries]
        scored_entries.sort(key=lambda x: x[1], reverse=True)

        # Simple merging: group entries by task_id similarity (placeholder)
        # In production, use cosine similarity on embeddings or text similarity
        task_groups: dict[str, List[MemoryEntry]] = {}
        for entry, _score in scored_entries:
            task_groups.setdefault(entry.task_id, []).append(entry)

        merged_count = 0
        for task_id, entries in task_groups.items():
            if len(entries) >= 2:
                # Merge top entries for this task
                merged_entry = self._merge_entries(entries[:5], task_id)
                self._store.save(merged_entry)
                
                # Archive merged entries (not delete)
                entry_ids = [e.id for e in entries[:5]]
                self._episodic.archive_entries(entry_ids)
                merged_count += len(entry_ids)

        self._audit.append({
            "type": "consolidation.complete",
            "merged_count": merged_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        return merged_count

    def _merge_entries(self, entries: List[MemoryEntry], task_id: str) -> MemoryEntry:
        """Merge multiple entries into a consolidated summary."""
        merged_content = " | ".join(e.content[:100] for e in entries[:3])
        avg_importance = sum(e.importance_score for e in entries) / len(entries)
        
        return MemoryEntry(
            id=uuid4(),
            task_id=task_id,
            content=f"[CONSOLIDATED] {merged_content}",
            importance_score=min(avg_importance + 0.1, 1.0),
            memory_type=MemoryType.CONSOLIDATED,
            timestamp=datetime.now(timezone.utc),
        )

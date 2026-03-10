"""Memory consolidation engine - deterministic similarity-based merging."""

from __future__ import annotations

import difflib
from datetime import datetime, timezone
from typing import List, Set
from uuid import UUID, uuid4

from ace.ace_kernel.audit_trail import AuditTrail
from ace.ace_memory import memory_config
from ace.ace_memory.episodic_memory import EpisodicMemory
from ace.ace_memory.memory_schema import MemoryEntry, MemoryType
from ace.ace_memory.memory_store import MemoryStore
from ace.ace_memory.quality_scorer import QualityScorer


class ConsolidationEngine:
    """Consolidate and merge similar episodic memories with deterministic similarity."""

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
        self._episodic.set_consolidation_engine(self)

    def should_consolidate(self) -> bool:
        """Check if consolidation trigger conditions are met."""
        active_entries = self._store.load_active()
        episodic_count = sum(1 for e in active_entries if e.memory_type == MemoryType.EPISODIC)
        return episodic_count >= 100

    def consolidate(
        self,
        merge_threshold: float = 0.85,
        max_comparisons_per_pass: int | None = None,
    ) -> int:
        """
        Perform memory consolidation with deterministic similarity-based merging.

        Returns count of merged entries.
        """
        active_entries = self._episodic.retrieve_all_active()

        if len(active_entries) == 0:
            return 0

        # Score all entries
        scored_entries = [(entry, self._scorer.score(entry)) for entry in active_entries]

        # Stable sort: by score DESC, then by ID ASC (deterministic ordering)
        scored_entries.sort(key=lambda x: (-x[1], str(x[0].id)))

        # Find merge groups using deterministic similarity
        merge_groups: List[List[MemoryEntry]] = []
        processed_ids: Set[UUID] = set()
        comparison_count = 0
        max_comparisons = max_comparisons_per_pass or memory_config.MAX_COMPARISONS_PER_PASS
        guard_triggered = False

        for entry, _score in scored_entries:
            if entry.id in processed_ids:
                continue

            # Start a new merge group
            current_group = [entry]
            processed_ids.add(entry.id)

            # Find similar entries (deterministic scan)
            for candidate, _cand_score in scored_entries:
                if candidate.id in processed_ids:
                    continue

                if comparison_count >= max_comparisons:
                    guard_triggered = True
                    break

                similarity = self._compute_similarity(entry, candidate)
                comparison_count += 1
                if similarity >= merge_threshold:
                    current_group.append(candidate)
                    processed_ids.add(candidate.id)

            # Only form a merge group if we have 2+ entries
            if len(current_group) >= 2:
                merge_groups.append(current_group)

            if guard_triggered:
                break

        # Execute merges
        merged_count = 0
        for group in merge_groups:
            merged_entry = self._merge_entries(group)
            self._store.save(merged_entry)

            # Archive originals (not delete)
            entry_ids = [e.id for e in group]
            self._episodic.archive_entries(entry_ids)
            merged_count += len(entry_ids)

        if guard_triggered:
            self._audit.append({
                "type": "consolidation_guard_triggered",
                "comparisons": comparison_count,
                "max_comparisons_per_pass": max_comparisons,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        self._audit.append({
            "type": "consolidation.complete",
            "merged_count": merged_count,
            "merge_groups": len(merge_groups),
            "comparisons": comparison_count,
            "guard_triggered": guard_triggered,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        return merged_count

    def _compute_similarity(self, entry1: MemoryEntry, entry2: MemoryEntry) -> float:
        """
        Compute deterministic similarity between two entries.

        Uses:
        - Cosine similarity if both have embeddings
        - Text similarity (difflib) otherwise
        """
        # Prefer embeddings (deterministic, vectorized)
        if entry1.embedding and entry2.embedding:
            return self._cosine_similarity(entry1.embedding, entry2.embedding)

        # Fallback to text similarity (deterministic difflib)
        # Normalize: both are lowercased
        text1 = entry1.content.lower()
        text2 = entry2.content.lower()

        # difflib.SequenceMatcher is deterministic
        matcher = difflib.SequenceMatcher(None, text1, text2)
        return matcher.ratio()

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Compute cosine similarity between two vectors (deterministic)."""
        if len(vec1) != len(vec2) or len(vec1) == 0:
            return 0.0

        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        mag1 = sum(x * x for x in vec1) ** 0.5
        mag2 = sum(x * x for x in vec2) ** 0.5

        if mag1 == 0 or mag2 == 0:
            return 0.0

        return dot_product / (mag1 * mag2)

    def _merge_entries(self, entries: List[MemoryEntry]) -> MemoryEntry:
        """
        Merge multiple similar entries into a consolidated summary.

        Specifications:
        - Type: CONSOLIDATED
        - Content: Concatenate first 5 entries (deterministic)
        - Importance: Average + small boost, capped at 1.0
        - Embedding: Inherited from highest-quality entry
        """
        # Deterministic: Use entries in score-sorted order
        merged_content = " | ".join(e.content[:200] for e in entries[:5])
        avg_importance = sum(e.importance_score for e in entries) / len(entries)
        boost_importance = min(avg_importance + 0.1, 1.0)

        # Inherit embedding from first entry (highest quality by our sort)
        inherited_embedding = entries[0].embedding if entries else None

        return MemoryEntry(
            id=uuid4(),
            task_id=entries[0].task_id,  # Use task_id from first entry
            content=f"[CONSOLIDATED] {merged_content}",
            importance_score=boost_importance,
            embedding=inherited_embedding,
            memory_type=MemoryType.CONSOLIDATED,
            timestamp=datetime.now(timezone.utc),
        )

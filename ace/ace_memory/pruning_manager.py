"""Memory pruning manager - remove low-quality entries."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from ace.ace_kernel.audit_trail import AuditTrail
from ace.ace_memory.memory_store import MemoryStore
from ace.ace_memory.quality_scorer import QualityScorer


class PruningManager:
    """Manage memory pruning based on quality scores."""

    def __init__(
        self,
        memory_store: MemoryStore,
        quality_scorer: QualityScorer,
        audit_trail: AuditTrail,
    ) -> None:
        self._store = memory_store
        self._scorer = quality_scorer
        self._audit = audit_trail

    def should_prune(self) -> bool:
        """Check if pruning trigger conditions are met."""
        active_entries = self._store.load_active()
        return len(active_entries) > 1000

    def prune(self, prune_percentage: float = 0.1) -> int:
        """Prune bottom percentage of entries by quality score."""
        active_entries = self._store.load_active()

        if len(active_entries) == 0:
            return 0

        # Filter out recent entries (last 24 hours)
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)
        prunable_entries = [
            entry for entry in active_entries
            if entry.timestamp < cutoff_time
        ]

        if len(prunable_entries) == 0:
            return 0

        # Score and sort
        scored_entries = [(entry, self._scorer.score(entry)) for entry in prunable_entries]
        scored_entries.sort(key=lambda x: x[1])

        # Prune bottom percentage
        prune_count = max(1, int(len(scored_entries) * prune_percentage))
        entries_to_prune = [entry for entry, _score in scored_entries[:prune_count]]

        # Archive (not delete)
        pruned = self._store.prune([e.id for e in entries_to_prune])

        self._audit.append({
            "type": "pruning.complete",
            "pruned_count": pruned,
            "total_active_before": len(active_entries),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        return pruned

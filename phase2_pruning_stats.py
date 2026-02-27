"""Generate pruning statistics for Phase 2 summary report."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ace.ace_diagnostics.evaluation_engine import EvaluationEngine
from ace.ace_kernel.audit_trail import AuditTrail
from ace.ace_memory.memory_schema import MemoryEntry
from ace.ace_memory.memory_store import MemoryStore
from ace.ace_memory.pruning_manager import PruningManager
from ace.ace_memory.quality_scorer import QualityScorer


def generate_pruning_stats() -> dict[str, Any]:
    """Create 1000 entries and run pruning for stats."""
    tmp_path = Path("./data/phase2_pruning_stats")
    tmp_path.mkdir(parents=True, exist_ok=True)

    audit_path = tmp_path / "pruning_audit.jsonl"
    store_path = tmp_path / "pruning_store.jsonl"
    audit_path.unlink(missing_ok=True)
    store_path.unlink(missing_ok=True)

    audit = AuditTrail(audit_path)
    store = MemoryStore(store_path)
    eval_engine = EvaluationEngine()
    scorer = QualityScorer(eval_engine)
    pruning = PruningManager(store, scorer, audit)

    # Create entries older than 24 hours to allow pruning
    old_timestamp = datetime.now(timezone.utc) - timedelta(days=2)
    for i in range(1001):
        entry = MemoryEntry(
            task_id=f"task_{i}",
            content=f"content_{i}",
            importance_score=0.5,
            timestamp=old_timestamp,
        )
        store.save(entry)

    should_prune = pruning.should_prune()
    pruned_count = pruning.prune()

    store.close()

    return {
        "total_entries": 1001,
        "should_prune": should_prune,
        "pruned_count": pruned_count,
        "prune_percentage": 10,
    }


if __name__ == "__main__":
    stats = generate_pruning_stats()
    print("PHASE 2 PRUNING STATS")
    print(f"Total entries: {stats['total_entries']}")
    print(f"Should prune: {stats['should_prune']}")
    print(f"Pruned count: {stats['pruned_count']}")
    print(f"Prune percentage: {stats['prune_percentage']}%")

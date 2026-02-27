"""Memory quality scoring with weighted formula."""

from __future__ import annotations

import math
from datetime import datetime, timezone

from ace.ace_diagnostics.evaluation_engine import EvaluationEngine
from ace.ace_memory.memory_schema import MemoryEntry


class QualityScorer:
    """Compute quality scores for memory entries."""

    def __init__(self, evaluation_engine: EvaluationEngine) -> None:
        self._evaluation = evaluation_engine

    def score(self, entry: MemoryEntry) -> float:
        """Compute quality score using weighted formula."""
        importance_weight = 0.4
        recency_weight = 0.3
        access_frequency_weight = 0.2
        task_success_weight = 0.1

        # Component 1: Importance score (already normalized 0-1)
        importance = entry.importance_score

        # Component 2: Recency (inverse exponential decay)
        recency = self._compute_recency(entry.timestamp)

        # Component 3: Access frequency (normalized)
        access_freq = min(entry.access_count / 10.0, 1.0)

        # Component 4: Task success bonus (from evaluation engine)
        task_success = self._compute_task_success_bonus(entry.task_id)

        quality_score = (
            importance_weight * importance +
            recency_weight * recency +
            access_frequency_weight * access_freq +
            task_success_weight * task_success
        )

        return max(0.0, min(1.0, quality_score))

    def _compute_recency(self, timestamp: datetime) -> float:
        """Inverse exponential decay based on age."""
        now = datetime.now(timezone.utc)
        age_seconds = (now - timestamp).total_seconds()
        age_days = age_seconds / 86400.0
        
        # Exponential decay: e^(-age_days / 30)
        # Recent entries (0 days) → 1.0
        # Old entries (90+ days) → ~0.05
        decay_constant = 30.0
        recency = math.exp(-age_days / decay_constant)
        
        return max(0.0, min(1.0, recency))

    def _compute_task_success_bonus(self, task_id: str) -> float:
        """Compute success bonus from evaluation metrics."""
        # For now, return default 0.5 (neutral)
        # In full implementation, query evaluation_engine for task success
        # report = self._evaluation.report()
        # If task_id in failures, reduce to 0.3
        # If task_id in successes, increase to 0.7
        return 0.5

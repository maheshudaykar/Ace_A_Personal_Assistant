"""Memory quality scoring with weighted formula."""

from __future__ import annotations

import math
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from ace.ace_diagnostics.evaluation_engine import EvaluationEngine
from ace.ace_memory.memory_schema import MemoryEntry


class QualityScorer:
    """Compute quality scores for memory entries."""

    def __init__(self, evaluation_engine: EvaluationEngine) -> None:
        self._evaluation = evaluation_engine
        # Recency cache: bucketed by whole days, max 100 entries
        self._recency_cache: OrderedDict[int, float] = OrderedDict()
        self._max_cache_size = 100

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

    def _compute_recency(self, timestamp: datetime, reference_time: datetime | None = None) -> float:
        """Inverse exponential decay based on age (with caching)."""
        now = reference_time or datetime.now(timezone.utc)
        age_seconds = (now - timestamp).total_seconds()
        age_days = age_seconds / 86400.0

        # Cache by whole days to reduce exp() calls
        age_days_bucket = int(age_days)

        if age_days_bucket in self._recency_cache:
            return self._recency_cache[age_days_bucket]

        # Exponential decay: e^(-age_days / 30)
        # Recent entries (0 days) → 1.0
        # Old entries (90+ days) → ~0.05
        decay_constant = 30.0
        recency = math.exp(-age_days / decay_constant)
        recency = max(0.0, min(1.0, recency))

        # Cache result (evict oldest if at capacity)
        if len(self._recency_cache) >= self._max_cache_size:
            self._recency_cache.popitem(last=False)
        self._recency_cache[age_days_bucket] = recency

        return recency

    def score_with_explanation(self, entry: MemoryEntry) -> Dict[str, float]:
        """Compute quality score with component breakdown."""
        importance_weight = 0.4
        recency_weight = 0.3
        access_frequency_weight = 0.2
        task_success_weight = 0.1

        importance = entry.importance_score
        recency = self._compute_recency(entry.timestamp)
        access_freq = min(entry.access_count / 10.0, 1.0)
        task_success = self._compute_task_success_bonus(entry.task_id)

        total = (
            importance_weight * importance +
            recency_weight * recency +
            access_frequency_weight * access_freq +
            task_success_weight * task_success
        )

        return {
            "importance": importance,
            "recency": recency,
            "access_frequency": access_freq,
            "task_success": task_success,
            "total": max(0.0, min(1.0, total))
        }

    def score_batch(
        self, entries: List[MemoryEntry], reference_time: datetime | None = None
    ) -> List[Tuple[MemoryEntry, float]]:
        """Batch score entries with single datetime.now() call."""
        # Compute reference time once
        ref_time = reference_time or datetime.now(timezone.utc)

        scored: List[Tuple[MemoryEntry, float]] = []
        for entry in entries:
            importance_weight = 0.4
            recency_weight = 0.3
            access_frequency_weight = 0.2
            task_success_weight = 0.1

            importance = entry.importance_score
            recency = self._compute_recency(entry.timestamp, reference_time=ref_time)
            access_freq = min(entry.access_count / 10.0, 1.0)
            task_success = self._compute_task_success_bonus(entry.task_id)

            quality_score = (
                importance_weight * importance +
                recency_weight * recency +
                access_frequency_weight * access_freq +
                task_success_weight * task_success
            )

            scored.append((entry, max(0.0, min(1.0, quality_score))))

        return scored

    def _compute_task_success_bonus(self, _task_id: str) -> float:
        """Compute success bonus from evaluation metrics.

        Uses the global success_rate from the evaluation engine as a proxy
        for task-level health. Returns 0.5 (neutral) when no data is available.
        """
        try:
            report = self._evaluation.report()
            task_count = report.get("task_count", 0.0)
            if task_count > 0:
                return max(0.0, min(1.0, report.get("success_rate", 0.5)))
        except (AttributeError, TypeError, ValueError):
            return 0.5
        return 0.5

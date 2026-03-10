"""Evaluation engine for tracking task performance metrics."""

from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Dict, List


@dataclass(frozen=True)
class TaskMetrics:
    """Per-task metrics snapshot."""

    task_id: str
    success: bool
    steps: int
    tool_successes: int
    tool_failures: int
    cpu_time_ms: int
    tokens_used: int


class EvaluationEngine:
    """Collect and report performance metrics."""

    def __init__(self) -> None:
        self._records: List[TaskMetrics] = []
        self._lock = threading.RLock()

    def record_task(self, metrics: TaskMetrics) -> None:
        """Record metrics for a completed task."""
        with self._lock:
            self._records.append(metrics)

    def report(self) -> Dict[str, float]:
        """Generate aggregated performance report."""
        with self._lock:
            records = list(self._records)

        total = len(records)
        if total == 0:
            return {
                "task_count": 0,
                "success_rate": 0.0,
                "avg_steps": 0.0,
                "tool_success_rate": 0.0,
                "avg_cpu_time_ms": 0.0,
                "total_tokens": 0.0,
            }

        successes = sum(1 for r in records if r.success)
        steps = sum(r.steps for r in records)
        tool_successes = sum(r.tool_successes for r in records)
        tool_failures = sum(r.tool_failures for r in records)
        cpu_time = sum(r.cpu_time_ms for r in records)
        tokens = sum(r.tokens_used for r in records)
        tool_total = tool_successes + tool_failures

        return {
            "task_count": float(total),
            "success_rate": successes / total,
            "avg_steps": steps / total,
            "tool_success_rate": (tool_successes / tool_total) if tool_total else 0.0,
            "avg_cpu_time_ms": cpu_time / total,
            "total_tokens": float(tokens),
        }

    def reset(self) -> None:
        """Clear recorded metrics."""
        with self._lock:
            self._records.clear()

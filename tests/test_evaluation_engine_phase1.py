"""Phase 1 tests for ace.ace_diagnostics.evaluation_engine."""

from __future__ import annotations

from ace.ace_diagnostics.evaluation_engine import EvaluationEngine, TaskMetrics


def test_report_metrics() -> None:
    engine = EvaluationEngine()
    engine.record_task(
        TaskMetrics(
            task_id="t1",
            success=True,
            steps=3,
            tool_successes=2,
            tool_failures=0,
            cpu_time_ms=100,
            tokens_used=50,
        )
    )
    engine.record_task(
        TaskMetrics(
            task_id="t2",
            success=False,
            steps=5,
            tool_successes=1,
            tool_failures=1,
            cpu_time_ms=200,
            tokens_used=75,
        )
    )

    report = engine.report()
    assert report["task_count"] == 2.0
    assert report["success_rate"] == 0.5
    assert report["avg_steps"] == 4.0
    assert report["tool_success_rate"] == 0.75
    assert report["avg_cpu_time_ms"] == 150.0
    assert report["total_tokens"] == 125.0

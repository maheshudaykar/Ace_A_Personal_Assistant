"""Phase 1 tests for ace.ace_cognitive.meta_monitor."""

from __future__ import annotations

from ace.ace_cognitive.meta_monitor import MetaMonitor


def test_meta_monitor_deltas() -> None:
    monitor = MetaMonitor()
    first = monitor.update({"success_rate": 0.5, "avg_steps": 3.0})
    second = monitor.update({"success_rate": 0.75, "avg_steps": 4.0})

    assert first["success_rate"] == 0.0
    assert second["success_rate"] == 0.25
    assert second["avg_steps"] == 1.0

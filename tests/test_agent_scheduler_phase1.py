"""Phase 1 tests for ace.ace_cognitive.agent_scheduler."""

from __future__ import annotations

import threading

from ace.ace_cognitive.agent_scheduler import AgentScheduler


def test_dispatch_respects_max_agents() -> None:
    scheduler = AgentScheduler(max_agents=1)
    gate = threading.Event()
    results: list[str] = []

    def task(name: str) -> None:
        gate.wait(0.2)
        results.append(name)

    scheduler.submit("t1", task, "first", priority=0)
    scheduler.submit("t2", task, "second", priority=1)

    futures = scheduler.dispatch()
    stats = scheduler.stats()

    assert len(futures) == 1
    assert stats["active_count"] == 1
    assert stats["queue_size"] == 1

    gate.set()
    futures[0].result(timeout=1)

    futures = scheduler.dispatch()
    futures[0].result(timeout=1)

    assert results == ["first", "second"]
    scheduler.shutdown()

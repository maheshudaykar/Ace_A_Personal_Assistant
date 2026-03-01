"""Phase 3A Gate 2.3 — AgentScheduler tests.

Verifies:
1. Priority ordering: higher-priority agents dispatched first.
2. Deterministic tie-break: among equal priority, agent_id ASC wins.
3. Starvation prevention: after MAX_CONSECUTIVE runs an agent is deprioritized.
4. Dead-letter routing: OPEN-circuit and permanently-failed agents are rejected.
5. Concurrent submit + dispatch: queue not corrupted under 8 concurrent submitters.
"""

from __future__ import annotations

import threading
from typing import List

import pytest

from ace.runtime import runtime_config
from ace.runtime.agent_context import (
    CIRCUIT_OPEN,
    AgentContext,
    PERMANENT_FAILURE_THRESHOLD,
)
from ace.runtime.agent_scheduler import AgentScheduler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_ctx(agent_id: str, priority: int = 5) -> AgentContext:
    return AgentContext(
        agent_id=agent_id,
        priority=priority,
        memory_quota_entries=100,
        cpu_quota_ms=200,
        execution_timeout_ms=1000,
    )


def noop() -> str:
    return "ok"


# ---------------------------------------------------------------------------
# Test 1: Priority ordering
# ---------------------------------------------------------------------------

class TestPriorityOrdering:
    def test_higher_priority_dispatched_first(self) -> None:
        """Agent with priority=9 must be dispatched before priority=3."""
        s = AgentScheduler()
        s.register_agent(make_ctx("low", priority=3))
        s.register_agent(make_ctx("high", priority=9))

        s.submit_task("low", "t-low", noop)
        s.submit_task("high", "t-high", noop)

        first = s.dispatch_next()
        assert first is not None
        assert first.agent_id == "high", f"Expected 'high' first, got '{first.agent_id}'"

        second = s.dispatch_next()
        assert second is not None
        assert second.agent_id == "low"

    def test_submit_order_does_not_affect_dispatch_order(self) -> None:
        """Submitting low-priority first must NOT cause it to be dispatched first."""
        s = AgentScheduler()
        s.register_agent(make_ctx("a", priority=1))
        s.register_agent(make_ctx("b", priority=8))

        # Submit low-priority first
        s.submit_task("a", "ta", noop)
        s.submit_task("b", "tb", noop)

        result = s.dispatch_next()
        assert result is not None
        assert result.agent_id == "b"


# ---------------------------------------------------------------------------
# Test 2: Deterministic tie-break
# ---------------------------------------------------------------------------

class TestDeterministicTieBreak:
    def test_equal_priority_uses_agent_id_asc(self) -> None:
        """Among same priority, agent with lexicographically smaller ID goes first."""
        s = AgentScheduler()
        s.register_agent(make_ctx("zebra", priority=5))
        s.register_agent(make_ctx("alpha", priority=5))
        s.register_agent(make_ctx("mango", priority=5))

        s.submit_task("zebra", "tz", noop)
        s.submit_task("alpha", "ta", noop)
        s.submit_task("mango", "tm", noop)

        order = []
        for _ in range(3):
            r = s.dispatch_next()
            assert r is not None
            order.append(r.agent_id)

        assert order == ["alpha", "mango", "zebra"], f"Got: {order}"


# ---------------------------------------------------------------------------
# Test 3: Starvation prevention
# ---------------------------------------------------------------------------

class TestStarvationPrevention:
    def test_agent_deprioritized_after_max_consecutive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After MAX_CONSECUTIVE_EXECUTIONS_PER_AGENT runs, high-priority agent
        must yield to low-priority agent."""
        monkeypatch.setattr(runtime_config, "MAX_CONSECUTIVE_EXECUTIONS_PER_AGENT", 3)

        s = AgentScheduler()
        s.register_agent(make_ctx("high", priority=9))
        s.register_agent(make_ctx("low", priority=1))

        # Submit 3 tasks for high, 1 for low
        for i in range(3):
            s.submit_task("high", f"th-{i}", noop)
        s.submit_task("low", "tl-0", noop)

        # Dispatch 3: all should be 'high' (consecutive cap not yet hit)
        dispatched = []
        for _ in range(3):
            r = s.dispatch_next()
            assert r is not None
            dispatched.append(r.agent_id)

        assert all(a == "high" for a in dispatched), f"Expected all 'high': {dispatched}"

        # Now high has consecutive_count=3 == MAX; submit one more for high
        s.submit_task("high", "th-3", noop)

        # Next dispatch must yield to 'low' (high is capped)
        r = s.dispatch_next()
        assert r is not None
        assert r.agent_id == "low", (
            f"Expected 'low' after starvation cap, got '{r.agent_id}'"
        )

        # After 'low' ran, high's consecutive count is reset; high goes next
        r2 = s.dispatch_next()
        assert r2 is not None
        assert r2.agent_id == "high"

    def test_consecutive_reset_when_different_agent_runs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When agent B runs, agent A's consecutive count resets to 0."""
        monkeypatch.setattr(runtime_config, "MAX_CONSECUTIVE_EXECUTIONS_PER_AGENT", 10)

        s = AgentScheduler()
        ctx_a = make_ctx("A", priority=5)
        ctx_b = make_ctx("B", priority=3)
        s.register_agent(ctx_a)
        s.register_agent(ctx_b)

        # A runs once
        s.submit_task("A", "ta1", noop)
        s.dispatch_next()
        assert ctx_a.consecutive_execution_count == 1

        # B runs once
        s.submit_task("B", "tb1", noop)
        s.dispatch_next()
        # A's consecutive count must be reset
        assert ctx_a.consecutive_execution_count == 0


# ---------------------------------------------------------------------------
# Test 4: Dead-letter routing
# ---------------------------------------------------------------------------

class TestDeadLetterRouting:
    def test_open_circuit_task_goes_to_dead_letter(self) -> None:
        """Task submitted when agent circuit is OPEN is dead-lettered."""
        s = AgentScheduler()
        ctx = make_ctx("agent-x", priority=5)
        ctx.circuit_state = CIRCUIT_OPEN
        ctx.last_failure_time = float("inf")  # retry window never elapses
        ctx.retry_window_seconds = 1e9
        s.register_agent(ctx)

        accepted = s.submit_task("agent-x", "t1", noop)
        assert not accepted, "Task should be rejected (circuit OPEN)"
        assert s.dead_letter_depth() == 1
        assert s.queue_depth() == 0

    def test_permanently_failed_agent_dead_lettered(self) -> None:
        """Agent that has exceeded failure threshold sends all tasks to dead-letter."""
        s = AgentScheduler()
        ctx = make_ctx("flaky", priority=5)
        ctx.failure_count = PERMANENT_FAILURE_THRESHOLD  # at the threshold
        s.register_agent(ctx)

        accepted = s.submit_task("flaky", "t1", noop)
        assert not accepted
        assert s.dead_letter_depth() == 1

    def test_successful_task_not_dead_lettered(self) -> None:
        """A normal CLOSED-circuit agent's tasks are queued, not dead-lettered."""
        s = AgentScheduler()
        s.register_agent(make_ctx("ok-agent"))
        accepted = s.submit_task("ok-agent", "t1", noop)
        assert accepted
        assert s.dead_letter_depth() == 0
        assert s.queue_depth() == 1


# ---------------------------------------------------------------------------
# Test 5: Concurrent submit + dispatch
# ---------------------------------------------------------------------------

class TestConcurrentSubmitDispatch:
    def test_concurrent_submit_does_not_corrupt_queue(self) -> None:
        """8 threads submitting tasks concurrently must not corrupt the queue."""
        THREADS = 8
        TASKS_PER_THREAD = 10

        s = AgentScheduler()
        for i in range(4):
            s.register_agent(make_ctx(f"agent-{i}", priority=i + 1))

        errors: List[str] = []

        def submitter(thread_id: int) -> None:
            agent_id = f"agent-{thread_id % 4}"
            for j in range(TASKS_PER_THREAD):
                try:
                    s.submit_task(agent_id, f"t-{thread_id}-{j}", noop)
                except Exception as exc:
                    errors.append(f"thread {thread_id}: {exc}")

        threads = [threading.Thread(target=submitter, args=(i,), daemon=True) for i in range(THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert not errors, f"Errors during concurrent submit: {errors}"

        # Drain the queue and verify all tasks succeed
        results = s.dispatch_all()
        total_submitted = THREADS * TASKS_PER_THREAD
        assert len(results) == total_submitted, (
            f"Expected {total_submitted} results, got {len(results)}"
        )
        assert all(r.success for r in results), (
            f"Some tasks failed: {[r for r in results if not r.success]}"
        )
        assert s.queue_depth() == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

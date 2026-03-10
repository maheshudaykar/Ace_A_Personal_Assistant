"""Agent scheduler with priority queue and concurrency caps."""

from __future__ import annotations

import heapq
import itertools
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Tuple


@dataclass(order=True)
class ScheduledTask:
    """Scheduled task envelope."""

    priority: int
    order: int
    task_id: str
    func: Callable[..., Any]
    args: Tuple[Any, ...]
    kwargs: Dict[str, Any]


class AgentScheduler:
    """Priority-based scheduler with hard concurrency limits."""

    def __init__(self, max_agents: int) -> None:
        if max_agents <= 0:
            raise ValueError("max_agents must be positive")
        self._max_agents = max_agents
        self._queue: List[ScheduledTask] = []
        self._order = itertools.count()
        self._executor = ThreadPoolExecutor(max_workers=max_agents)
        self._lock = threading.Lock()
        self._active_count = 0
        self._inflight_futures: set[int] = set()

    def submit(
        self,
        task_id: str,
        func: Callable[..., Any],
        *args: Any,
        priority: int = 0,
        **kwargs: Any,
    ) -> None:
        """Submit a task to the scheduler."""
        with self._lock:
            task = ScheduledTask(
                priority=priority,
                order=next(self._order),
                task_id=task_id,
                func=func,
                args=args,
                kwargs=kwargs,
            )
            heapq.heappush(self._queue, task)

    def dispatch(self) -> List[Future[Any]]:
        """Dispatch queued tasks up to the concurrency limit."""
        futures: List[Future[Any]] = []
        with self._lock:
            slots = self._max_agents - self._active_count
            while slots > 0 and self._queue:
                task = heapq.heappop(self._queue)
                self._active_count += 1
                slots -= 1
                future = self._executor.submit(task.func, *task.args, **task.kwargs)
                self._inflight_futures.add(id(future))
                future.add_done_callback(self._on_task_done)
                futures.append(future)
        return futures

    def stats(self) -> Dict[str, int]:
        """Return scheduler stats for monitoring."""
        with self._lock:
            # Keep counters bounded if completions race with config updates.
            active_count = min(self._active_count, len(self._inflight_futures))
            return {
                "queue_size": len(self._queue),
                "active_count": active_count,
                "max_agents": self._max_agents,
            }

    def set_max_agents(self, max_agents: int) -> None:
        """Update the concurrency cap."""
        if max_agents <= 0:
            raise ValueError("max_agents must be positive")
        with self._lock:
            self._max_agents = max_agents

    def shutdown(self) -> None:
        """Shutdown the scheduler executor."""
        self._executor.shutdown(wait=True)

    def _on_task_done(self, _future: Future[Any]) -> None:
        with self._lock:
            future_key = id(_future)
            if future_key in self._inflight_futures:
                self._inflight_futures.remove(future_key)
                self._active_count = max(0, self._active_count - 1)


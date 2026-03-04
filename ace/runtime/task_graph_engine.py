"""TaskGraphEngine: Parallel task execution with dependency ordering."""
from __future__ import annotations

import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

__all__ = ["GraphTask", "TaskGraphEngine"]

logger = logging.getLogger(__name__)


@dataclass
class GraphTask:
    """A single node in the execution dependency graph."""

    task_id: str
    name: str
    fn: Callable
    args: Dict[str, Any]
    dependencies: List[str]  # task_ids this task depends on
    status: str = "pending"   # pending / running / done / failed
    result: Any = None
    error: Optional[str] = None


class TaskGraphEngine:
    """Execute a set of GraphTasks respecting dependencies, running independent tasks in parallel."""

    def __init__(self, max_workers: int = 4) -> None:
        self._max_workers = max_workers
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(self, tasks: List[GraphTask]) -> Dict[str, GraphTask]:
        """
        Execute *tasks* in dependency order.

        Returns a mapping task_id → completed GraphTask.

        Note: For heavy tasks in a distributed deployment, consider routing
        through TaskDelegator (ace.distributed.task_delegator) instead of
        running locally via this engine.
        """
        task_map: Dict[str, GraphTask] = {t.task_id: t for t in tasks}
        completed: Dict[str, GraphTask] = {}

        self._validate_no_cycles(task_map)

        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            running_ids: set = set()
            while len(completed) < len(task_map):
                ready = self._get_ready_tasks(task_map, completed, running_ids)
                if not ready:
                    # Check for stuck tasks (all pending but none ready = cycle guard)
                    pending = [t for t in task_map.values() if t.task_id not in completed and t.task_id not in running_ids]
                    if pending and not running_ids:
                        logger.error("TaskGraphEngine: deadlock detected; aborting remaining tasks")
                        for t in pending:
                            t.status = "failed"
                            t.error = "deadlock"
                            completed[t.task_id] = t
                        break
                    elif not running_ids:
                        break
                    else:
                        # Wait for running tasks to finish
                        break

                futures = {}
                for task in ready:
                    task.status = "running"
                    running_ids.add(task.task_id)
                    fut = pool.submit(self._run_task, task, completed)
                    futures[fut] = task

                for fut in as_completed(futures):
                    task = futures[fut]
                    running_ids.discard(task.task_id)
                    try:
                        fut.result()
                    except Exception as exc:
                        task.status = "failed"
                        task.error = str(exc)
                        logger.exception("TaskGraphEngine: task %s failed", task.task_id)
                    completed[task.task_id] = task

        return completed

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _run_task(task: GraphTask, completed: Dict[str, GraphTask]) -> None:
        try:
            task.result = task.fn(**{k: v for k, v in task.args.items()})
            task.status = "done"
        except Exception as exc:
            task.status = "failed"
            task.error = str(exc)
            raise

    @staticmethod
    def _get_ready_tasks(
        task_map: Dict[str, GraphTask], completed: Dict[str, GraphTask],
        running_ids: set
    ) -> List[GraphTask]:
        ready = []
        for task in task_map.values():
            if task.task_id in completed:
                continue
            if task.task_id in running_ids:
                continue
            if all(dep in completed and completed[dep].status == "done" for dep in task.dependencies):
                ready.append(task)
        return ready

    @staticmethod
    def _validate_no_cycles(task_map: Dict[str, GraphTask]) -> None:
        """Kahn's algorithm for cycle detection."""
        in_degree: Dict[str, int] = {tid: 0 for tid in task_map}
        for task in task_map.values():
            for dep in task.dependencies:
                if dep in in_degree:
                    in_degree[task.task_id] += 1

        queue = [tid for tid, deg in in_degree.items() if deg == 0]
        visited = 0
        while queue:
            tid = queue.pop(0)
            visited += 1
            for other in task_map.values():
                if tid in other.dependencies:
                    in_degree[other.task_id] -= 1
                    if in_degree[other.task_id] == 0:
                        queue.append(other.task_id)

        if visited != len(task_map):
            raise ValueError("TaskGraphEngine: cycle detected in task graph")

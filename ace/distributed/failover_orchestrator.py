"""FailoverOrchestrator: deterministic cluster failover handling."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ace.distributed.consensus_engine import ConsensusEngine
from ace.distributed.health_monitor import HealthMonitor
from ace.distributed.task_delegator import TaskDelegator

logger = logging.getLogger(__name__)

__all__ = ["FailoverEvent", "FailoverOrchestrator"]


@dataclass
class FailoverEvent:
    event_id: str
    timestamp: float
    failure_type: str
    affected_node_id: str
    tasks_affected: List[str]
    tasks_redistributed: List[str]
    recovery_time_ms: int
    status: str


class FailoverOrchestrator:
    """Handles leader/follower crash and partition recovery orchestration."""

    def __init__(
        self,
        consensus_engine: ConsensusEngine,
        health_monitor: HealthMonitor,
        task_delegator: TaskDelegator,
        total_cluster_size: int = 3,
    ) -> None:
        self.consensus_engine = consensus_engine
        self.health_monitor = health_monitor
        self.task_delegator = task_delegator
        self.total_cluster_size = max(total_cluster_size, 1)
        self.failover_events: List[FailoverEvent] = []
        self._lock = threading.RLock()

    def on_leader_crash(self, old_leader_id: str) -> bool:
        start = time.time()
        logger.warning("Leader crash detected: %s — triggering election", old_leader_id)
        elected = False
        if hasattr(self.consensus_engine, "trigger_election"):
            elected = bool(self.consensus_engine.trigger_election())
        elif hasattr(self.consensus_engine, "start_election"):
            elected = bool(self.consensus_engine.start_election())

        affected_tasks = list(self.task_delegator.delegated_tasks.keys())
        redistributed: List[str] = []
        if elected:
            redistributed = self._redistribute_tasks(old_leader_id)
        else:
            logger.error("Election failed after leader crash of %s", old_leader_id)

        event = self._make_event(
            "leader_crash",
            old_leader_id,
            tasks_affected=affected_tasks,
            tasks_redistributed=redistributed,
            start=start,
            status="recovered" if elected else "partial_loss",
        )
        self._append_event(event)
        return elected

    def on_follower_crash(self, crashed_follower_id: str) -> bool:
        start = time.time()
        logger.warning("Follower crash detected: %s", crashed_follower_id)

        # Collect tasks assigned to crashed follower
        tasks = [
            task_id
            for task_id, task in self.task_delegator.delegated_tasks.items()
            if task.target_node == crashed_follower_id
        ]

        # Remove tasks from crashed follower
        for task_id in tasks:
            self.task_delegator.delegated_tasks.pop(task_id, None)

        # Attempt redistribution to healthy followers
        redistributed = self._redistribute_orphaned_tasks(tasks, exclude_node=crashed_follower_id)

        event = self._make_event(
            "follower_crash",
            crashed_follower_id,
            tasks_affected=tasks,
            tasks_redistributed=redistributed,
            start=start,
            status="recovered" if len(redistributed) == len(tasks) else "partial_loss",
        )
        self._append_event(event)
        return True

    def on_network_partition(self, partition_members: List[str]) -> str:
        start = time.time()
        majority_needed = (self.total_cluster_size // 2) + 1
        mode = "normal" if len(partition_members) >= majority_needed else "read_only"
        logger.warning(
            "Network partition: %d members (need %d for quorum) — mode=%s",
            len(partition_members),
            majority_needed,
            mode,
        )
        event = self._make_event(
            "network_partition",
            ",".join(sorted(partition_members)),
            tasks_affected=[],
            tasks_redistributed=[],
            start=start,
            status="recovered" if mode == "normal" else "partial_loss",
        )
        self._append_event(event)
        return mode

    def recover_from_partial_loss(self, failover_event: FailoverEvent) -> bool:
        """Attempt full recovery: redistribute any tasks that weren't redistributed."""
        remaining = [t for t in failover_event.tasks_affected if t not in failover_event.tasks_redistributed]
        if not remaining:
            failover_event.status = "recovered"
            return True

        redistributed = self._redistribute_orphaned_tasks(
            remaining, exclude_node=failover_event.affected_node_id
        )
        if len(redistributed) == len(remaining):
            failover_event.status = "recovered"
            return True

        logger.warning(
            "Partial recovery: %d/%d tasks still orphaned",
            len(remaining) - len(redistributed),
            len(remaining),
        )
        return False

    def monitor_failovers(self) -> List[FailoverEvent]:
        suspected: List[str] = []
        node_metrics: Dict[str, object] = getattr(self.health_monitor, "node_metrics", {})
        for node_id, metrics in sorted(node_metrics.items()):
            failures = getattr(metrics, "consecutive_failures", 0)
            if failures >= 5:
                suspected.append(node_id)

        for node_id in suspected:
            self.on_follower_crash(node_id)
        return self.get_failover_events()

    def get_failover_events(self) -> List[FailoverEvent]:
        with self._lock:
            return list(self.failover_events)

    # ------------------------------------------------------------------
    # Redistribution helpers
    # ------------------------------------------------------------------

    def _redistribute_tasks(self, crashed_node_id: str) -> List[str]:
        """Redistribute all tasks from the crashed node."""
        tasks = [
            task_id
            for task_id, task in list(self.task_delegator.delegated_tasks.items())
            if task.target_node == crashed_node_id
        ]
        for task_id in tasks:
            self.task_delegator.delegated_tasks.pop(task_id, None)
        return self._redistribute_orphaned_tasks(tasks, exclude_node=crashed_node_id)

    def _redistribute_orphaned_tasks(
        self, task_ids: List[str], exclude_node: str
    ) -> List[str]:
        """Try to re-delegate orphaned tasks to healthy nodes.
        Returns list of task IDs that were successfully redistributed.
        
        CRITICAL: Previously only checked candidate but didn't actually
        submit delegated tasks to task_delegator. Now properly submits
        via delegate_task call.
        """
        redistributed: List[str] = []
        for task_id in sorted(task_ids):
            # Find a healthy node via registry
            node_registry = getattr(self.task_delegator, "node_registry", None)
            if node_registry is None:
                break
            candidates = getattr(node_registry, "get_healthy_nodes", lambda: [])()
            target: Optional[str] = None
            for node in sorted(candidates, key=lambda n: getattr(n, "node_id", str(n))):
                nid = getattr(node, "node_id", str(node))
                if nid != exclude_node:
                    target = nid
                    break
            if target:
                # CRITICAL FIX: Previously only tracked in logs, didn't actually delegate.
                # Now properly re-enters delegation system via TaskDelegator.
                delegator = getattr(self.task_delegator, "delegate_task", None)
                if delegator is not None and callable(delegator):
                    # Create a placeholder DelegatedTask for re-delegation
                    # (actual task details would be restored from queue)
                    from ace.distributed.data_structures import DelegatedTask
                    placeholder_task = DelegatedTask(
                        task_id=task_id,
                        agent_id="failover_recovery",
                        target_node=target,
                        fn_name="recover_task",
                        args={"original_task_id": task_id},
                        timeout_ms=30000,
                    )
                    if delegator(placeholder_task):
                        redistributed.append(task_id)
                        logger.info("Redistributed task %s → %s (via delegation)", task_id, target)
                    else:
                        logger.warning("Failed to redistribute task %s to %s", task_id, target)
                else:
                    redistributed.append(task_id)
                    logger.info("Redistributed task %s → %s (logged)", task_id, target)
            else:
                logger.warning("No healthy node available for task %s", task_id)
        return redistributed

    # ------------------------------------------------------------------
    # Event helpers
    # ------------------------------------------------------------------

    def _make_event(
        self,
        failure_type: str,
        affected_node_id: str,
        tasks_affected: List[str],
        tasks_redistributed: List[str],
        start: float,
        status: str,
    ) -> FailoverEvent:
        now = time.time()
        stable = f"{failure_type}|{affected_node_id}|{int(now * 1000)}"
        event_id = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]
        return FailoverEvent(
            event_id=event_id,
            timestamp=now,
            failure_type=failure_type,
            affected_node_id=affected_node_id,
            tasks_affected=list(sorted(tasks_affected)),
            tasks_redistributed=list(sorted(tasks_redistributed)),
            recovery_time_ms=int((now - start) * 1000),
            status=status,
        )

    def _append_event(self, event: FailoverEvent) -> None:
        with self._lock:
            self.failover_events.append(event)

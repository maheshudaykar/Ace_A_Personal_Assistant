"""
HealthMonitor: Node health tracking, failure detection, and recovery coordination.

Monitors node health metrics, detects failures, triggers recovery actions.
Integrates with ConsensusEngine for leader election on node failures.
Integrates with ByzantineDetector for anomalous node isolation.
"""

import threading
import time
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict

from .data_structures import NodeHealthMetrics, ClusterHealth
from .types import NodeStatus

__all__ = [
    "HealthMonitor",
    "HealthStatus",
    "RecoveryAction",
]

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """Health status of a node."""
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    QUARANTINED = "QUARANTINED"


class RecoveryAction(Enum):
    """Recovery actions for failed nodes."""
    THROTTLE = "THROTTLE"  # Reduce task submission rate
    AVOID_ROUTING = "AVOID_ROUTING"  # Don't route new tasks
    MARK_OFFLINE = "MARK_OFFLINE"  # Node is unavailable
    REDISTRIBUTE = "REDISTRIBUTE"  # Move in-flight tasks
    TRIGGER_ELECTION = "TRIGGER_ELECTION"  # If leader failed
    QUARANTINE = "QUARANTINE"  # Disconnect from cluster
    MANUAL_REVIEW = "MANUAL_REVIEW"  # Alert operator


class HealthMonitor:
    """Monitor node health and trigger recovery actions."""

    def __init__(self, heartbeat_timeout_ms: int = 30000):
        """
        Initialize HealthMonitor.

        Args:
            heartbeat_timeout_ms: Milliseconds without heartbeat to mark FAILED
        """
        self._lock = threading.RLock()
        self._heartbeat_timeout_ms = heartbeat_timeout_ms

        # Track metrics for each node
        self._metrics: Dict[str, NodeHealthMetrics] = {}
        self._last_heartbeat: Dict[str, float] = {}
        self._health_status: Dict[str, HealthStatus] = {}
        self._consecutive_failures: Dict[str, int] = defaultdict(int)
        self._status_transition_time: Dict[str, float] = {}
        self._recovery_callbacks: List = []

    def register_recovery_callback(self, callback) -> None:
        """Register callback to execute recovery actions."""
        with self._lock:
            self._recovery_callbacks.append(callback)

    def update_metrics(
        self, node_id: str, metrics: NodeHealthMetrics
    ) -> Tuple[HealthStatus, Optional[RecoveryAction]]:
        """
        Receive heartbeat with health metrics, update node health status.

        Args:
            node_id: Node identifier
            metrics: Current health metrics

        Returns:
            (new_status, recovery_action) if status changed or action needed
        """
        with self._lock:
            old_status = self._health_status.get(node_id, HealthStatus.HEALTHY)
            current_time = time.time()

            # Store metrics and update heartbeat
            self._metrics[node_id] = metrics
            self._last_heartbeat[node_id] = current_time
            self._consecutive_failures[node_id] = 0

            # Evaluate new status
            new_status = self._evaluate_health(node_id, metrics)
            recovery_action = None

            # Always store the status (even if unchanged, for new nodes)
            self._health_status[node_id] = new_status

            if new_status != old_status:
                logger.info(
                    f"Node {node_id}: status transition "
                    f"{old_status.value} → {new_status.value}"
                )
                self._status_transition_time[node_id] = current_time

                # Determine recovery action
                recovery_action = self._get_recovery_action(
                    node_id, old_status, new_status
                )

                if recovery_action:
                    self._execute_recovery(node_id, recovery_action)

            return new_status, recovery_action

    def check_heartbeat_timeout(self) -> Dict[str, Tuple[HealthStatus, Optional[RecoveryAction]]]:
        """
        Check for nodes that have stopped sending heartbeats.

        Returns:
            dict of node_id → (new_status, recovery_action) for changed nodes
        """
        with self._lock:
            current_time = time.time()
            changes = {}

            for node_id, last_hb in list(self._last_heartbeat.items()):
                elapsed_ms = (current_time - last_hb) * 1000
                old_status = self._health_status.get(node_id, HealthStatus.HEALTHY)

                if elapsed_ms > self._heartbeat_timeout_ms:
                    self._consecutive_failures[node_id] += 1

                    # Mark as FAILED after missing heartbeats
                    if old_status != HealthStatus.FAILED:
                        logger.warning(
                            f"Node {node_id}: heartbeat timeout "
                            f"({elapsed_ms:.0f}ms > {self._heartbeat_timeout_ms}ms)"
                        )
                        self._health_status[node_id] = HealthStatus.FAILED
                        self._status_transition_time[node_id] = current_time

                        recovery_action = self._get_recovery_action(
                            node_id, old_status, HealthStatus.FAILED
                        )

                        if recovery_action:
                            self._execute_recovery(node_id, recovery_action)

                        changes[node_id] = (HealthStatus.FAILED, recovery_action)

            return changes

    def _evaluate_health(self, node_id: str, metrics: NodeHealthMetrics) -> HealthStatus:
        """Determine health status from metrics."""
        if metrics.error_rate_per_minute > 10:
            return HealthStatus.DEGRADED

        if metrics.consecutive_failures > 5:
            return HealthStatus.FAILED

        if metrics.cpu_percent > 80 or metrics.memory_percent > 85:
            return HealthStatus.DEGRADED

        return HealthStatus.HEALTHY

    def _get_recovery_action(
        self, node_id: str, old_status: HealthStatus, new_status: HealthStatus
    ) -> Optional[RecoveryAction]:
        """Determine recovery action from status transition."""
        if new_status == HealthStatus.DEGRADED:
            return RecoveryAction.THROTTLE
        elif new_status == HealthStatus.FAILED:
            return RecoveryAction.REDISTRIBUTE
        elif new_status == HealthStatus.QUARANTINED:
            return RecoveryAction.QUARANTINE
        return None

    def _execute_recovery(self, node_id: str, action: RecoveryAction) -> None:
        """Execute recovery action via registered callbacks."""
        logger.info(f"Node {node_id}: executing recovery action {action.value}")

        for callback in self._recovery_callbacks:
            try:
                callback(node_id, action)
            except Exception as e:
                logger.error(f"Recovery callback failed: {e}", exc_info=True)

    def get_node_status(self, node_id: str) -> HealthStatus:
        """Get current health status of node."""
        with self._lock:
            return self._health_status.get(node_id, HealthStatus.HEALTHY)

    def get_node_metrics(self, node_id: str) -> Optional[NodeHealthMetrics]:
        """Get current health metrics of node."""
        with self._lock:
            return self._metrics.get(node_id)

    def get_cluster_health(self) -> ClusterHealth:
        """Get aggregate health view."""
        with self._lock:
            healthy = []
            degraded = []
            failed = []
            quarantined = []

            for node_id, status in self._health_status.items():
                if status == HealthStatus.HEALTHY:
                    healthy.append(node_id)
                elif status == HealthStatus.DEGRADED:
                    degraded.append(node_id)
                elif status == HealthStatus.FAILED:
                    failed.append(node_id)
                elif status == HealthStatus.QUARANTINED:
                    quarantined.append(node_id)

            return ClusterHealth(
                healthy_nodes=healthy,
                degraded_nodes=degraded,
                failed_nodes=failed,
                quarantined_nodes=quarantined,
            )

    def mark_quarantined(self, node_id: str, reason: str) -> None:
        """Mark node as quarantined (by ByzantineDetector)."""
        with self._lock:
            old_status = self._health_status.get(node_id, HealthStatus.HEALTHY)

            if old_status != HealthStatus.QUARANTINED:
                logger.warning(f"Node {node_id}: quarantined - {reason}")
                self._health_status[node_id] = HealthStatus.QUARANTINED
                self._status_transition_time[node_id] = time.time()

                recovery_action = RecoveryAction.QUARANTINE
                self._execute_recovery(node_id, recovery_action)

    def trigger_manual_recovery(self, node_id: str) -> None:
        """Trigger manual operator review for recovery."""
        with self._lock:
            logger.info(f"Node {node_id}: triggered manual recovery review")
            self._execute_recovery(node_id, RecoveryAction.MANUAL_REVIEW)

    def allow_rejoin(self, node_id: str) -> None:
        """Allow quarantined node to rejoin cluster."""
        with self._lock:
            if self._health_status.get(node_id) == HealthStatus.QUARANTINED:
                logger.info(f"Node {node_id}: rejoin authorization granted")
                self._health_status[node_id] = HealthStatus.HEALTHY
                self._consecutive_failures[node_id] = 0
                self._last_heartbeat[node_id] = time.time()

    def get_health_summary(self) -> Dict[str, dict]:
        """Get detailed health summary for all nodes."""
        with self._lock:
            summary = {}

            for node_id in list(self._health_status.keys()):
                metrics = self._metrics.get(node_id)
                status = self._health_status.get(node_id, HealthStatus.HEALTHY)
                last_hb = self._last_heartbeat.get(node_id, time.time())
                current_time = time.time()

                summary[node_id] = {
                    "status": status.value,
                    "cpu_percent": metrics.cpu_percent if metrics else 0,
                    "memory_percent": metrics.memory_percent if metrics else 0,
                    "error_rate": metrics.error_rate_per_minute if metrics else 0,
                    "failures": self._consecutive_failures[node_id],
                    "last_heartbeat_ms": (current_time - last_hb) * 1000,
                    "uptime_s": (
                        current_time - self._status_transition_time.get(node_id, current_time)
                    ),
                }

            return summary

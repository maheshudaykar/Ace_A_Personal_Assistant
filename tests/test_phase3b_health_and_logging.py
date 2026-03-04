"""
Tests for Phase 3B.5: HealthMonitor and RemoteLogging

Coverage:
- HealthMonitor: status transitions, metrics evaluation, recovery actions
- RemoteLogging: event logging, ordering, replay, synchronization
"""

import pytest
import time
import threading
from dataclasses import dataclass, field

from ace.distributed.health_monitor import HealthMonitor, HealthStatus, RecoveryAction
from ace.distributed.remote_logging import RemoteLogging, ReplayResult
from ace.distributed.data_structures import (
    NodeHealthMetrics,
    DistributedEvent,
    AuditSyncPacket,
)


# ============================================================================
# HealthMonitor Tests
# ============================================================================


class TestHealthMonitor:
    """Test HealthMonitor functionality."""

    def test_initial_state(self):
        """HealthMonitor starts with no nodes."""
        monitor = HealthMonitor()
        health = monitor.get_cluster_health()

        assert health.total_nodes == 0
        assert len(health.healthy_nodes) == 0

    def test_update_healthy_metrics(self):
        """Node with good metrics stays HEALTHY."""
        monitor = HealthMonitor()

        metrics = NodeHealthMetrics(
            cpu_percent=30.0,
            memory_percent=40.0,
            disk_percent=50.0,
            task_queue_depth=5,
            error_rate_per_minute=0.5,
            network_latency_ms=10.0,
            last_successful_task=time.time(),
            consecutive_failures=0,
        )

        status, action = monitor.update_metrics("node_1", metrics)

        assert status == HealthStatus.HEALTHY
        assert action is None

    def test_high_cpu_triggers_degraded(self):
        """CPU >80% transitions to DEGRADED."""
        monitor = HealthMonitor()

        metrics = NodeHealthMetrics(
            cpu_percent=85.0,
            memory_percent=40.0,
            disk_percent=50.0,
            task_queue_depth=5,
            error_rate_per_minute=0.5,
            network_latency_ms=10.0,
            last_successful_task=time.time(),
            consecutive_failures=0,
        )

        status, action = monitor.update_metrics("node_1", metrics)

        assert status == HealthStatus.DEGRADED
        assert action == RecoveryAction.THROTTLE

    def test_high_memory_triggers_degraded(self):
        """Memory >85% transitions to DEGRADED."""
        monitor = HealthMonitor()

        metrics = NodeHealthMetrics(
            cpu_percent=40.0,
            memory_percent=90.0,
            disk_percent=50.0,
            task_queue_depth=5,
            error_rate_per_minute=0.5,
            network_latency_ms=10.0,
            last_successful_task=time.time(),
            consecutive_failures=0,
        )

        status, action = monitor.update_metrics("node_1", metrics)

        assert status == HealthStatus.DEGRADED
        assert action == RecoveryAction.THROTTLE

    def test_high_error_rate_triggers_degraded(self):
        """Error rate >10/min transitions to DEGRADED."""
        monitor = HealthMonitor()

        metrics = NodeHealthMetrics(
            cpu_percent=40.0,
            memory_percent=40.0,
            disk_percent=50.0,
            task_queue_depth=5,
            error_rate_per_minute=15.0,
            network_latency_ms=10.0,
            last_successful_task=time.time(),
            consecutive_failures=0,
        )

        status, action = monitor.update_metrics("node_1", metrics)

        assert status == HealthStatus.DEGRADED
        assert action == RecoveryAction.THROTTLE

    def test_consecutive_failures_triggers_failed(self):
        """5+ consecutive failures transitions to FAILED."""
        monitor = HealthMonitor()

        metrics = NodeHealthMetrics(
            cpu_percent=40.0,
            memory_percent=40.0,
            disk_percent=50.0,
            task_queue_depth=5,
            error_rate_per_minute=0.5,
            network_latency_ms=10.0,
            last_successful_task=time.time(),
            consecutive_failures=6,
        )

        status, action = monitor.update_metrics("node_1", metrics)

        assert status == HealthStatus.FAILED
        assert action == RecoveryAction.REDISTRIBUTE

    def test_heartbeat_timeout(self):
        """Missing heartbeat transitions to FAILED."""
        monitor = HealthMonitor(heartbeat_timeout_ms=100)

        # First heartbeat
        metrics = NodeHealthMetrics(
            cpu_percent=40.0,
            memory_percent=40.0,
            disk_percent=50.0,
            task_queue_depth=5,
            error_rate_per_minute=0.5,
            network_latency_ms=10.0,
            last_successful_task=time.time(),
            consecutive_failures=0,
        )

        status, _ = monitor.update_metrics("node_1", metrics)
        assert status == HealthStatus.HEALTHY

        # Wait for timeout
        time.sleep(0.15)
        changes = monitor.check_heartbeat_timeout()

        assert "node_1" in changes
        assert changes["node_1"][0] == HealthStatus.FAILED

    def test_recovery_callback(self):
        """Recovery callbacks are executed."""
        monitor = HealthMonitor()

        recovery_calls = []

        def recovery_callback(node_id, action):
            recovery_calls.append((node_id, action))

        monitor.register_recovery_callback(recovery_callback)

        metrics = NodeHealthMetrics(
            cpu_percent=85.0,
            memory_percent=40.0,
            disk_percent=50.0,
            task_queue_depth=5,
            error_rate_per_minute=0.5,
            network_latency_ms=10.0,
            last_successful_task=time.time(),
            consecutive_failures=0,
        )

        monitor.update_metrics("node_1", metrics)

        assert len(recovery_calls) == 1
        assert recovery_calls[0] == ("node_1", RecoveryAction.THROTTLE)

    def test_get_cluster_health(self):
        """Cluster health aggregates node statuses."""
        monitor = HealthMonitor()

        # Healthy node
        metrics_healthy = NodeHealthMetrics(
            cpu_percent=30.0,
            memory_percent=40.0,
            disk_percent=50.0,
            task_queue_depth=5,
            error_rate_per_minute=0.5,
            network_latency_ms=10.0,
            last_successful_task=time.time(),
            consecutive_failures=0,
        )

        # Degraded node
        metrics_degraded = NodeHealthMetrics(
            cpu_percent=85.0,
            memory_percent=40.0,
            disk_percent=50.0,
            task_queue_depth=5,
            error_rate_per_minute=0.5,
            network_latency_ms=10.0,
            last_successful_task=time.time(),
            consecutive_failures=0,
        )

        monitor.update_metrics("node_1", metrics_healthy)
        monitor.update_metrics("node_2", metrics_degraded)

        health = monitor.get_cluster_health()

        assert health.total_nodes == 2
        assert "node_1" in health.healthy_nodes
        assert "node_2" in health.degraded_nodes

    def test_mark_quarantined(self):
        """ByzantineDetector can mark node quarantined."""
        monitor = HealthMonitor()

        monitor.mark_quarantined("node_1", "Byzantine behavior detected")

        status = monitor.get_node_status("node_1")
        assert status == HealthStatus.QUARANTINED

    def test_allow_rejoin(self):
        """Operator can allow quarantined node to rejoin."""
        monitor = HealthMonitor()

        monitor.mark_quarantined("node_1", "Test quarantine")
        assert monitor.get_node_status("node_1") == HealthStatus.QUARANTINED

        monitor.allow_rejoin("node_1")
        assert monitor.get_node_status("node_1") == HealthStatus.HEALTHY

    def test_health_summary(self):
        """Health summary provides detailed node info."""
        monitor = HealthMonitor()

        metrics = NodeHealthMetrics(
            cpu_percent=30.0,
            memory_percent=40.0,
            disk_percent=50.0,
            task_queue_depth=5,
            error_rate_per_minute=0.5,
            network_latency_ms=10.0,
            last_successful_task=time.time(),
            consecutive_failures=0,
        )

        monitor.update_metrics("node_1", metrics)

        summary = monitor.get_health_summary()

        assert "node_1" in summary
        assert summary["node_1"]["status"] == "HEALTHY"
        assert summary["node_1"]["cpu_percent"] == 30.0
        assert summary["node_1"]["memory_percent"] == 40.0


# ============================================================================
# RemoteLogging Tests
# ============================================================================


class TestRemoteLogging:
    """Test RemoteLogging functionality."""

    def test_initial_state(self):
        """RemoteLogging starts empty."""
        logging = RemoteLogging()
        stats = logging.get_log_stats()

        assert stats["total_events"] == 0
        assert len(stats["events_by_node"]) == 0

    def test_log_event(self):
        """Log single event."""
        logging = RemoteLogging()

        event = logging.log_distributed_event(
            node_id="node_1",
            raft_log_index=1,
            raft_term=1,
            event_type="TASK_SUBMIT",
            payload={"task_id": "task_1"},
            checksum="abc123",
        )

        assert event.event_id is not None
        assert event.node_id == "node_1"
        assert event.raft_log_index == 1

        stats = logging.get_log_stats()
        assert stats["total_events"] == 1

    def test_multiple_events_ordering(self):
        """Multiple events maintain order by raft log index."""
        logging = RemoteLogging()

        # Log events out of order
        logging.log_distributed_event(
            node_id="node_2",
            raft_log_index=3,
            raft_term=1,
            event_type="TASK_RESULT",
            payload={"task_id": "task_3"},
        )

        logging.log_distributed_event(
            node_id="node_1",
            raft_log_index=1,
            raft_term=1,
            event_type="TASK_SUBMIT",
            payload={"task_id": "task_1"},
        )

        logging.log_distributed_event(
            node_id="node_1",
            raft_log_index=2,
            raft_term=1,
            event_type="TASK_SUBMIT",
            payload={"task_id": "task_2"},
        )

        # Replay should return in order
        _, replay_events, _ = logging.replay_distributed_trace(since_index=0)

        assert len(replay_events) == 3
        assert replay_events[0].raft_log_index == 1
        assert replay_events[1].raft_log_index == 2
        assert replay_events[2].raft_log_index == 3

    def test_replay_with_index_filter(self):
        """Replay since_index filters events."""
        logging = RemoteLogging()

        for i in range(1, 6):
            logging.log_distributed_event(
                node_id="node_1",
                raft_log_index=i,
                raft_term=1,
                event_type="TASK",
                payload={"seq": i},
            )

        _, replay_events, _ = logging.replay_distributed_trace(since_index=3)

        assert len(replay_events) == 3
        assert replay_events[0].raft_log_index == 3
        assert replay_events[-1].raft_log_index == 5

    def test_total_ordering(self):
        """Total ordering sorts by (raft_log_index, node_id)."""
        logging = RemoteLogging()

        # Create unsorted events
        events = []
        nodes = ["node_2", "node_1", "node_3"]

        for node in nodes:
            for idx in [3, 1, 2]:
                event = DistributedEvent(
                    event_id=f"{node}_{idx}",
                    node_id=node,
                    raft_log_index=idx,
                    raft_term=1,
                    lamport_time=(1, node, idx),
                    event_type="TEST",
                    payload={},
                    checksum="",
                    timestamp=time.time(),
                )
                events.append(event)

        sorted_events = logging.get_total_ordering(events)

        # Should be sorted by (raft_log_index, node_id)
        for i in range(1, len(sorted_events)):
            prev = sorted_events[i - 1]
            curr = sorted_events[i]

            key_prev = (prev.raft_log_index, prev.node_id)
            key_curr = (curr.raft_log_index, curr.node_id)

            assert key_prev <= key_curr

    def test_sync_from_follower(self):
        """Leader receives and merges follower events."""
        logging = RemoteLogging()

        # Pre-populate leader with some events
        logging.log_distributed_event(
            node_id="node_1",
            raft_log_index=1,
            raft_term=1,
            event_type="TASK",
            payload={"seq": 1},
        )

        # Create sync packet from follower
        follower_events = [
            DistributedEvent(
                event_id="e2",
                node_id="node_2",
                raft_log_index=2,
                raft_term=1,
                lamport_time=(1, "node_2", 1),
                event_type="TASK",
                payload={"seq": 2},
                checksum="",
                timestamp=time.time(),
            ),
            DistributedEvent(
                event_id="e3",
                node_id="node_2",
                raft_log_index=3,
                raft_term=1,
                lamport_time=(1, "node_2", 2),
                event_type="TASK",
                payload={"seq": 3},
                checksum="",
                timestamp=time.time(),
            ),
        ]

        packet = AuditSyncPacket(
            source_node="node_2",
            events=follower_events,
            since_raft_index=1,
            packet_checksum="valid",
        )

        success, merged, details = logging.sync_from_follower("node_2", packet)

        assert success is True
        assert merged == 2  # Both events are new

        stats = logging.get_log_stats()
        assert stats["total_events"] == 3

    def test_checksum_divergence_detection(self):
        """Checksum mismatch detected on sync."""
        logging = RemoteLogging()

        # Pre-populate with event at index 2
        logging.log_distributed_event(
            node_id="node_1",
            raft_log_index=2,
            raft_term=1,
            event_type="TASK",
            payload={"seq": 2},
            checksum="original_checksum",
        )

        # Try to sync with different checksum at same index
        conflict_events = [
            DistributedEvent(
                event_id="e2",
                node_id="node_1",
                raft_log_index=2,
                raft_term=1,
                lamport_time=(1, "node_1", 1),
                event_type="TASK",
                payload={"seq": 2, "modified": True},
                checksum="different_checksum",
                timestamp=time.time(),
            ),
        ]

        packet = AuditSyncPacket(
            source_node="node_2",
            events=conflict_events,
            since_raft_index=1,
            packet_checksum="valid",
        )

        success, merged, details = logging.sync_from_follower("node_2", packet)

        assert success is False
        assert "mismatch" in details.lower() or "divergence" in details.lower()

    def test_replay_mode(self):
        """Enter/exit replay mode."""
        logging = RemoteLogging()

        assert logging.is_in_replay_mode() is False

        logging.enter_replay_mode()
        assert logging.is_in_replay_mode() is True

        duration = logging.exit_replay_mode()
        assert logging.is_in_replay_mode() is False
        assert duration >= 0

    def test_get_events_by_node(self):
        """Filter events by node."""
        logging = RemoteLogging()

        logging.log_distributed_event(
            node_id="node_1",
            raft_log_index=1,
            raft_term=1,
            event_type="TASK",
            payload={},
        )

        logging.log_distributed_event(
            node_id="node_2",
            raft_log_index=2,
            raft_term=1,
            event_type="TASK",
            payload={},
        )

        logging.log_distributed_event(
            node_id="node_1",
            raft_log_index=3,
            raft_term=1,
            event_type="TASK",
            payload={},
        )

        node1_events = logging.get_events_by_node("node_1")
        assert len(node1_events) == 2
        assert all(e.node_id == "node_1" for e in node1_events)

    def test_get_events_by_type(self):
        """Filter events by type."""
        logging = RemoteLogging()

        logging.log_distributed_event(
            node_id="node_1",
            raft_log_index=1,
            raft_term=1,
            event_type="TASK_SUBMIT",
            payload={},
        )

        logging.log_distributed_event(
            node_id="node_1",
            raft_log_index=2,
            raft_term=1,
            event_type="TASK_RESULT",
            payload={},
        )

        logging.log_distributed_event(
            node_id="node_1",
            raft_log_index=3,
            raft_term=1,
            event_type="TASK_SUBMIT",
            payload={},
        )

        submit_events = logging.get_events_by_type("TASK_SUBMIT")
        assert len(submit_events) == 2

    def test_get_max_log_index(self):
        """Track highest log index per node."""
        logging = RemoteLogging()

        logging.log_distributed_event(
            node_id="node_1",
            raft_log_index=5,
            raft_term=1,
            event_type="TASK",
            payload={},
        )

        logging.log_distributed_event(
            node_id="node_2",
            raft_log_index=3,
            raft_term=1,
            event_type="TASK",
            payload={},
        )

        assert logging.get_max_log_index("node_1") == 5
        assert logging.get_max_log_index("node_2") == 3
        assert logging.get_max_log_index("node_3") == 0

    def test_log_statistics(self):
        """Log statistics track events by type and node."""
        logging = RemoteLogging()

        logging.log_distributed_event(
            node_id="node_1",
            raft_log_index=1,
            raft_term=1,
            event_type="TASK_SUBMIT",
            payload={},
        )

        logging.log_distributed_event(
            node_id="node_1",
            raft_log_index=2,
            raft_term=1,
            event_type="TASK_SUBMIT",
            payload={},
        )

        logging.log_distributed_event(
            node_id="node_2",
            raft_log_index=3,
            raft_term=1,
            event_type="TASK_RESULT",
            payload={},
        )

        stats = logging.get_log_stats()

        assert stats["total_events"] == 3
        assert stats["events_by_node"]["node_1"] == 2
        assert stats["events_by_node"]["node_2"] == 1
        assert stats["events_by_type"]["TASK_SUBMIT"] == 2
        assert stats["events_by_type"]["TASK_RESULT"] == 1

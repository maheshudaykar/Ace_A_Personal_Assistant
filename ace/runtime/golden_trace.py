"""Golden trace recording for deterministic maintenance cycle and agent-event replay."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ace.runtime import runtime_config
from ace.runtime.event_sequence import GlobalEventSequence

if TYPE_CHECKING:
    from ace.ace_kernel.audit_trail import AuditTrail


class EventType:
    """Event types representing persistent state mutations and agent lifecycle events."""

    # ── Memory layer (Gate 1.5) ──────────────────────────────────────────────
    RECORD_ENTRY = "record_entry"
    ARCHIVE_ENTRY = "archive_entry"
    ACTIVE_QUOTA_ENFORCED = "active_quota_enforced"
    TOTAL_QUOTA_ENFORCED = "total_quota_enforced"
    PER_TASK_QUOTA_ENFORCED = "per_task_quota_enforced"

    # ── Maintenance cycle boundaries ─────────────────────────────────────────
    CYCLE_START = "cycle_start"
    CYCLE_END = "cycle_end"

    # ── Consolidation (Gate 1.5) ─────────────────────────────────────────────
    CONSOLIDATION_GROUP_FORMED = "consolidation_group_formed"
    CONSOLIDATION_GUARD_TRIGGERED = "consolidation_guard_triggered"
    CONSOLIDATION_COMPLETE = "consolidation_complete"

    # ── Compaction (Gate 1.5) ────────────────────────────────────────────────
    COMPACTION_DELETED_ENTRIES = "compaction_deleted_entries"

    # ── Agent lifecycle (Gate 2.3 / 2.4) ────────────────────────────────────
    AGENT_TASK_SCHEDULED = "agent_task_scheduled"
    AGENT_TASK_DISPATCHED = "agent_task_dispatched"
    AGENT_TASK_COMPLETED = "agent_task_completed"
    AGENT_TASK_FAILED = "agent_task_failed"

    # ── Circuit breaker transitions (Gate 2.4) ───────────────────────────────
    CIRCUIT_BREAKER_OPENED = "circuit_breaker_opened"
    CIRCUIT_BREAKER_HALF_OPEN = "circuit_breaker_half_open"
    CIRCUIT_BREAKER_CLOSED = "circuit_breaker_closed"

    # ── Fairness (Gate 2.3) ──────────────────────────────────────────────────
    FAIRNESS_CAP_HIT = "fairness_cap_hit"


@dataclass
class TraceEvent:
    """Deterministic event record for replay validation."""
    sequence_id: int
    thread_id: int
    timestamp_ns: float
    event_type: str
    deterministic_mode: bool
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for JSON storage."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        """Deserialize from dict."""
        return cls(**data)


@dataclass
class ConsolidationMetrics:
    merged_count: int
    merge_groups: int
    comparisons: int
    guard_triggered: bool


@dataclass
class CompactionMetrics:
    removed_entries: int
    archived_ratio_before: float
    archived_ratio_after: float


@dataclass
class CycleMetadata:
    cycle_id: int
    deterministic_mode: bool
    timestamp_start: str
    timestamp_end: str
    duration_ms: float
    operations_executed: int
    consolidation: ConsolidationMetrics
    compaction: CompactionMetrics
    termination_reason: str
    active_count_before: int
    active_count_after: int


class GoldenTrace:
    """Singleton trace recorder for determinism validation."""

    _instance: 'GoldenTrace | None' = None
    _init_lock = threading.Lock()

    def __new__(cls, audit_trail: "AuditTrail | None" = None) -> "GoldenTrace":
        """Enforce singleton pattern."""
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._audit = audit_trail
                    instance._events: List[TraceEvent] = []
                    instance._events_lock = threading.Lock()
                    instance._cycle_count = 0
                    cls._instance = instance
        return cls._instance

    @classmethod
    def get_instance(cls, audit_trail: "AuditTrail | None" = None) -> "GoldenTrace":
        """Get or create singleton instance."""
        if cls._instance is None:
            return cls(audit_trail)
        return cls._instance

    def log_event(
        self,
        event_type: str,
        metadata: Dict[str, Any],
        deterministic_mode: bool = True,
    ) -> None:
        """Log a determinism-critical event."""
        if not runtime_config.TRACE_ENABLED:
            return

        event = TraceEvent(
            sequence_id=GlobalEventSequence.get_instance().next(),
            thread_id=threading.get_ident(),
            timestamp_ns=time.monotonic_ns(),
            event_type=event_type,
            deterministic_mode=deterministic_mode,
            metadata=metadata,
        )

        with self._events_lock:
            self._events.append(event)

    def record_cycle_start(self, cycle_id: int, deterministic_mode: bool) -> None:
        """Log cycle start boundary."""
        self.log_event(
            event_type=EventType.CYCLE_START,
            metadata={"cycle_id": cycle_id},
            deterministic_mode=deterministic_mode,
        )

    def record_cycle_end(self, metadata: CycleMetadata) -> None:
        """Log cycle end boundary and summary."""
        self.log_event(
            event_type=EventType.CYCLE_END,
            metadata={
                "cycle_id": metadata.cycle_id,
                "status": metadata.termination_reason,
                "operations_executed": metadata.operations_executed,
                "cpu_time_ms": metadata.duration_ms,
                "active_count_before": metadata.active_count_before,
                "active_count_after": metadata.active_count_after,
            },
            deterministic_mode=metadata.deterministic_mode,
        )
        self._cycle_count += 1

    def get_all_events(self) -> List[TraceEvent]:
        """Get all recorded events in sequence order."""
        with self._events_lock:
            return list(self._events)

    def get_cycle_count(self) -> int:
        """Get number of completed cycles."""
        return self._cycle_count

    def reset(self) -> None:
        """Clear all events (testing only)."""
        with self._events_lock:
            self._events.clear()
        self._cycle_count = 0

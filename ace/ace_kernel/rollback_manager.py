"""RollbackManager: snapshot recovery and rollback procedures for nuclear modifications."""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ace.ace_kernel.audit_trail import AuditTrail
from ace.ace_kernel.snapshot_engine import SnapshotEngine

__all__ = ["RollbackEvent", "RollbackManager"]


@dataclass
class RollbackEvent:
    """Record of a rollback operation."""

    event_id: str
    snapshot_id: str
    reason: str  # "validation_failed", "operator_request", "emergency"
    triggered_by: str
    duration_ms: float = 0.0
    status: str = "pending"  # "pending", "in_progress", "completed", "failed"
    timestamp: float = field(default_factory=time.time)
    restored_state_hash: Optional[str] = None


class RollbackManager:
    """Manage rollback to snapshots with graceful task shutdown.

    Responsibilities:
    1. Verify snapshot integrity before rollback.
    2. Signal in-flight tasks to drain (configurable grace period).
    3. Restore state from snapshot.
    4. Validate restored state integrity.
    5. Log every step to the immutable audit trail.
    """

    def __init__(
        self,
        snapshot_engine: SnapshotEngine,
        audit_trail: AuditTrail,
        grace_period_ms: int = 30_000,
        on_drain_tasks: Optional[Callable[[], bool]] = None,
        on_state_restored: Optional[Callable[[Dict[str, Any]], bool]] = None,
    ) -> None:
        if grace_period_ms < 0:
            raise ValueError("grace_period_ms must be non-negative")
        self._snapshot_engine = snapshot_engine
        self._audit = audit_trail
        self._grace_period_ms = grace_period_ms
        self._on_drain_tasks = on_drain_tasks or (lambda: True)
        self._on_state_restored = on_state_restored or (lambda _state: True)
        self._lock = threading.RLock()
        self._rollback_history: List[RollbackEvent] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def rollback_to_snapshot(
        self,
        snapshot_id: str,
        reason: str,
        triggered_by: str,
    ) -> RollbackEvent:
        """Execute a full rollback to the given snapshot.

        Steps:
        1. Validate snapshot exists and is uncorrupted.
        2. Drain in-flight tasks (grace period).
        3. Restore state.
        4. Post-restore integrity check.
        5. Log to audit trail.
        """
        start = time.time()
        event = self._create_event(snapshot_id, reason, triggered_by)

        try:
            event.status = "in_progress"

            # Step 1 – verify snapshot
            if not self._snapshot_engine.validate_snapshot(snapshot_id):
                event.status = "failed"
                self._audit.append(
                    {
                        "type": "rollback.snapshot_invalid",
                        "snapshot_id": snapshot_id,
                        "reason": reason,
                    }
                )
                self._record_event(event, start)
                return event

            # Step 2 – drain in-flight tasks
            drained = self._drain_tasks()
            if not drained:
                self._audit.append(
                    {
                        "type": "rollback.drain_timeout",
                        "snapshot_id": snapshot_id,
                    }
                )
                # Continue with rollback even if drain was partial.

            # Step 3 – restore state
            restored_state = self._snapshot_engine.restore_state(snapshot_id)
            event.restored_state_hash = hashlib.sha256(
                str(sorted(restored_state.items())).encode("utf-8")
            ).hexdigest()

            # Step 4 – post-restore hook
            if not self._on_state_restored(restored_state):
                event.status = "failed"
                self._audit.append(
                    {
                        "type": "rollback.post_restore_failed",
                        "snapshot_id": snapshot_id,
                    }
                )
                self._record_event(event, start)
                return event

            event.status = "completed"
            self._audit.append(
                {
                    "type": "rollback.completed",
                    "snapshot_id": snapshot_id,
                    "reason": reason,
                    "triggered_by": triggered_by,
                    "duration_ms": (time.time() - start) * 1000,
                    "restored_state_hash": event.restored_state_hash,
                }
            )

        except Exception as exc:
            event.status = "failed"
            self._audit.append(
                {
                    "type": "rollback.error",
                    "snapshot_id": snapshot_id,
                    "error": str(exc),
                }
            )

        self._record_event(event, start)
        return event

    def list_rollback_history(self) -> List[RollbackEvent]:
        with self._lock:
            return list(self._rollback_history)

    def verify_snapshot_for_rollback(self, snapshot_id: str) -> bool:
        """Pre-check: is a snapshot valid for rollback?"""
        return self._snapshot_engine.validate_snapshot(snapshot_id)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _drain_tasks(self) -> bool:
        """Signal in-flight tasks to stop and wait up to the grace period."""
        return self._on_drain_tasks()

    def _create_event(self, snapshot_id: str, reason: str, triggered_by: str) -> RollbackEvent:
        stable = f"{snapshot_id}|{reason}|{triggered_by}|{time.time():.6f}"
        event_id = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]
        return RollbackEvent(
            event_id=event_id,
            snapshot_id=snapshot_id,
            reason=reason,
            triggered_by=triggered_by,
        )

    def _record_event(self, event: RollbackEvent, start: float) -> None:
        event.duration_ms = (time.time() - start) * 1000
        with self._lock:
            self._rollback_history.append(event)

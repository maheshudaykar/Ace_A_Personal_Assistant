"""Tests for RollbackManager (Phase 6)."""

import pytest

from ace.ace_kernel.audit_trail import AuditTrail
from ace.ace_kernel.rollback_manager import RollbackManager
from ace.ace_kernel.snapshot_engine import SnapshotEngine


@pytest.fixture()
def audit_trail(tmp_path):
    return AuditTrail(file_path=tmp_path / "audit.jsonl")


@pytest.fixture()
def snapshot_engine(tmp_path, audit_trail):
    return SnapshotEngine(snapshot_dir=tmp_path / "snapshots", audit_trail=audit_trail)


@pytest.fixture()
def rollback_manager(snapshot_engine, audit_trail):
    return RollbackManager(
        snapshot_engine=snapshot_engine,
        audit_trail=audit_trail,
        grace_period_ms=100,
    )


class TestRollbackSuccess:
    def test_full_rollback_cycle(self, rollback_manager, snapshot_engine):
        record = snapshot_engine.save_state({"version": 1, "data": "original"})
        event = rollback_manager.rollback_to_snapshot(
            snapshot_id=record.snapshot_id,
            reason="validation_failed",
            triggered_by="admin",
        )
        assert event.status == "completed"
        assert event.restored_state_hash is not None
        assert event.duration_ms >= 0

    def test_history_recorded(self, rollback_manager, snapshot_engine):
        record = snapshot_engine.save_state({"k": "v"})
        rollback_manager.rollback_to_snapshot(record.snapshot_id, "operator_request", "admin")
        history = rollback_manager.list_rollback_history()
        assert len(history) == 1
        assert history[0].reason == "operator_request"


class TestRollbackFailure:
    def test_invalid_snapshot_fails(self, rollback_manager):
        event = rollback_manager.rollback_to_snapshot("nonexistent", "emergency", "admin")
        assert event.status == "failed"

    def test_post_restore_hook_failure(self, snapshot_engine, audit_trail):
        mgr = RollbackManager(
            snapshot_engine=snapshot_engine,
            audit_trail=audit_trail,
            on_state_restored=lambda _state: False,  # simulate failure
        )
        record = snapshot_engine.save_state({"x": 1})
        event = mgr.rollback_to_snapshot(record.snapshot_id, "test", "admin")
        assert event.status == "failed"


class TestRollbackVerification:
    def test_verify_valid_snapshot(self, rollback_manager, snapshot_engine):
        record = snapshot_engine.save_state({"check": True})
        assert rollback_manager.verify_snapshot_for_rollback(record.snapshot_id) is True

    def test_verify_nonexistent_snapshot(self, rollback_manager):
        assert rollback_manager.verify_snapshot_for_rollback("missing") is False

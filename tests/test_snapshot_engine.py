"""Tests for snapshot engine save/restore integrity."""

from __future__ import annotations

from datetime import datetime, timezone

from ace.ace_kernel.audit_trail import AuditTrail
from ace.ace_kernel.snapshot_engine import SnapshotEngine


def _fixed_time() -> datetime:
    return datetime(2026, 2, 27, 12, 0, 0, tzinfo=timezone.utc)


def test_save_and_restore(tmp_path) -> None:
    audit = AuditTrail(tmp_path / "audit.jsonl", time_fn=_fixed_time)
    engine = SnapshotEngine(tmp_path / "snapshots", audit, time_fn=_fixed_time)

    state = {"status": "ok", "value": 42}
    record = engine.save_state(state)

    assert engine.validate_snapshot(record.snapshot_id) is True

    restored = engine.restore_state(record.snapshot_id)
    assert restored == state
    assert audit.verify_chain() is True


def test_restore_missing_snapshot_raises(tmp_path) -> None:
    audit = AuditTrail(tmp_path / "audit.jsonl", time_fn=_fixed_time)
    engine = SnapshotEngine(tmp_path / "snapshots", audit, time_fn=_fixed_time)

    try:
        engine.restore_state("missing")
    except FileNotFoundError:
        assert True
    else:
        assert False

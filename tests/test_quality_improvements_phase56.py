"""Tests for code quality improvements across Phase 5/6 modules."""

import pytest

from ace.ace_kernel.audit_trail import AuditTrail
from ace.ace_kernel.nuclear_mode import NuclearModeController
from ace.ace_kernel.nuclear_switch import NuclearSwitch
from ace.ace_kernel.snapshot_engine import SnapshotEngine


@pytest.fixture()
def audit_trail(tmp_path):
    return AuditTrail(file_path=tmp_path / "audit.jsonl")


@pytest.fixture()
def snapshot_engine(tmp_path, audit_trail):
    return SnapshotEngine(snapshot_dir=tmp_path / "snapshots", audit_trail=audit_trail)


@pytest.fixture()
def nuclear_switch(audit_trail):
    return NuclearSwitch(audit_trail=audit_trail, passphrase="secret")


# ---------- SnapshotEngine integrity tests ----------

class TestSnapshotIntegrity:
    def test_save_creates_hash_sidecar(self, snapshot_engine, tmp_path):
        record = snapshot_engine.save_state({"key": "value"})
        hash_file = tmp_path / "snapshots" / f"snapshot_{record.snapshot_id}.sha256"
        assert hash_file.exists()
        assert hash_file.read_text(encoding="utf-8") == record.state_hash

    def test_restore_validates_hash(self, snapshot_engine, tmp_path):
        record = snapshot_engine.save_state({"data": 42})
        # Corrupt the hash sidecar
        hash_file = tmp_path / "snapshots" / f"snapshot_{record.snapshot_id}.sha256"
        hash_file.write_text("bad_hash", encoding="utf-8")
        with pytest.raises(ValueError, match="integrity check failed"):
            snapshot_engine.restore_state(record.snapshot_id)

    def test_restore_validates_json(self, snapshot_engine, tmp_path):
        record = snapshot_engine.save_state({"x": 1})
        # Corrupt the snapshot file itself
        snap_file = tmp_path / "snapshots" / f"snapshot_{record.snapshot_id}.json"
        snap_file.write_text("NOT JSON!", encoding="utf-8")
        # Also update the hash to match the corrupted content so hash passes
        import hashlib
        bad_hash = hashlib.sha256(b"NOT JSON!").hexdigest()
        hash_file = tmp_path / "snapshots" / f"snapshot_{record.snapshot_id}.sha256"
        hash_file.write_text(bad_hash, encoding="utf-8")
        with pytest.raises(ValueError, match="Corrupted snapshot"):
            snapshot_engine.restore_state(record.snapshot_id)

    def test_restore_roundtrip(self, snapshot_engine):
        state = {"config": {"nested": True}, "version": 3}
        record = snapshot_engine.save_state(state)
        restored = snapshot_engine.restore_state(record.snapshot_id)
        assert restored == state


# ---------- NuclearModeController quality tests ----------

class TestNuclearModeQuality:
    def test_guardrail_blocks_non_immutable(self, audit_trail, nuclear_switch, snapshot_engine):
        ctrl = NuclearModeController(audit_trail, nuclear_switch, snapshot_engine)
        with pytest.raises(PermissionError, match="nuclear mode only applies"):
            ctrl.request_nuclear_modification(
                "admin", "ace/ace_cognitive/analyzer_agent.py", "+fix", "bugfix"
            )

    def test_guardrail_audit_on_denial(self, audit_trail, nuclear_switch, snapshot_engine):
        ctrl = NuclearModeController(audit_trail, nuclear_switch, snapshot_engine)
        try:
            ctrl.request_nuclear_modification("admin", "ace/tools/registry.py", "+x", "test")
        except PermissionError:
            pass
        # Verify denial was logged
        records = list(audit_trail.iter_records())
        assert any(r.event.get("type") == "nuclear.guardrail_blocked" for r in records)

    def test_extended_checks_selective(self, audit_trail, nuclear_switch, snapshot_engine):
        ctrl = NuclearModeController(audit_trail, nuclear_switch, snapshot_engine)
        assert ctrl._requires_extended_checks("ace/distributed/consensus_engine.py") is True
        assert ctrl._requires_extended_checks("ace/distributed/memory_sync.py") is True
        # Non-critical distributed modules should NOT require extended checks
        assert ctrl._requires_extended_checks("ace/distributed/node_registry.py") is False

    def test_configurable_risk_weights(self, audit_trail, nuclear_switch, snapshot_engine):
        custom_weights = {"base": 0.5, "consensus": 0.3, "has_diff_changes": 0.1, "large_diff": 0.1}
        ctrl = NuclearModeController(
            audit_trail, nuclear_switch, snapshot_engine, risk_weights=custom_weights
        )
        risk = ctrl._compute_modification_risk("ace/ace_kernel/audit_trail.py", "-old\n+new")
        # base 0.5 + has_diff_changes 0.1 = 0.6
        assert abs(risk - 0.6) < 0.01

    def test_get_authorization_returns_copy(self, audit_trail, nuclear_switch, snapshot_engine):
        ctrl = NuclearModeController(audit_trail, nuclear_switch, snapshot_engine)
        auth = ctrl.request_nuclear_modification(
            "admin", "ace/ace_kernel/audit_trail.py", "-x\n+y", "test"
        )
        fetched = ctrl.get_authorization(auth.auth_id)
        assert fetched is not None
        # Should be a copy, not the same object
        assert fetched is not auth or fetched.auth_id == auth.auth_id
        fetched.reason = "mutated"
        original = ctrl.get_authorization(auth.auth_id)
        assert original.reason != "mutated"

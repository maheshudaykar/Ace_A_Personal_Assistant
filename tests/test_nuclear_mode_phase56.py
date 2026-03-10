from datetime import datetime, timezone

from ace.ace_kernel.audit_trail import AuditTrail
from ace.ace_kernel.nuclear_mode import NuclearModeController
from ace.ace_kernel.nuclear_switch import NuclearSwitch
from ace.ace_kernel.snapshot_engine import SnapshotEngine


def _fixed_time() -> datetime:
    return datetime(2026, 3, 1, tzinfo=timezone.utc)


def test_nuclear_mode_requires_active_switch_and_dual_snapshot_for_distributed(tmp_path) -> None:
    audit = AuditTrail(tmp_path / "audit.jsonl", time_fn=_fixed_time)
    switch = NuclearSwitch(audit, passphrase="secret", time_fn=_fixed_time)
    snapshots = SnapshotEngine(tmp_path / "snapshots", audit, time_fn=_fixed_time)

    controller = NuclearModeController(audit, switch, snapshots)

    auth = controller.request_nuclear_modification(
        requested_by="admin",
        module_to_modify="ace/distributed/consensus_engine.py",
        modification_diff="+ tighten safety checks",
        reason="security hardening",
    )

    assert switch.activate("secret")
    assert controller.authorize_nuclear_modification(auth.auth_id, authorized_by="lead")
    authorized = controller.get_authorization(auth.auth_id)

    assert authorized is not None
    assert authorized.snapshot_id_primary is not None
    assert authorized.snapshot_id_secondary is not None
    assert controller.apply_nuclear_modification(auth.auth_id)


def test_nuclear_mode_blocks_project_memory_schema_mutation(tmp_path) -> None:
    audit = AuditTrail(tmp_path / "audit.jsonl", time_fn=_fixed_time)
    switch = NuclearSwitch(audit, passphrase="secret", time_fn=_fixed_time)
    snapshots = SnapshotEngine(tmp_path / "snapshots", audit, time_fn=_fixed_time)

    controller = NuclearModeController(audit, switch, snapshots)

    try:
        controller.request_nuclear_modification(
            requested_by="admin",
            module_to_modify="ace/ace_memory/project_memory.py",
            modification_diff="+ SCHEMA_VERSION = 2",
            reason="schema change",
        )
        assert False, "Expected PermissionError"
    except PermissionError:
        assert True

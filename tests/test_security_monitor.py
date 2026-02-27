"""Tests for security monitor policy enforcement."""

from __future__ import annotations

from datetime import datetime, timezone

from ace.ace_kernel.audit_trail import AuditTrail
from ace.ace_kernel.nuclear_switch import NuclearSwitch
from ace.ace_kernel.security_monitor import SecurityMonitor


def _fixed_time() -> datetime:
    return datetime(2026, 2, 27, 12, 0, 0, tzinfo=timezone.utc)


def test_blocks_sudo_without_nuclear(tmp_path) -> None:
    audit = AuditTrail(tmp_path / "audit.jsonl", time_fn=_fixed_time)
    nuclear = NuclearSwitch(audit, passphrase="secret", time_fn=_fixed_time)
    monitor = SecurityMonitor(audit, nuclear, workspace_root=tmp_path)

    decision = monitor.evaluate_tool_call(["sudo", "echo", "hi"], requires_sudo=True)

    assert decision.allowed is False
    assert any("sudo_blocked" in reason for reason in decision.reasons)


def test_blocks_write_outside_workspace(tmp_path) -> None:
    audit = AuditTrail(tmp_path / "audit.jsonl", time_fn=_fixed_time)
    nuclear = NuclearSwitch(audit, passphrase="secret", time_fn=_fixed_time)
    monitor = SecurityMonitor(audit, nuclear, workspace_root=tmp_path)

    decision = monitor.evaluate_tool_call(
        ["write"],
        write_paths=[tmp_path / ".." / "escape.txt"],
    )

    assert decision.allowed is False
    assert any("write_outside_workspace" in reason for reason in decision.reasons)


def test_allows_in_workspace_and_hosts(tmp_path) -> None:
    audit = AuditTrail(tmp_path / "audit.jsonl", time_fn=_fixed_time)
    nuclear = NuclearSwitch(audit, passphrase="secret", time_fn=_fixed_time)
    monitor = SecurityMonitor(
        audit,
        nuclear,
        workspace_root=tmp_path,
        allowed_hosts=["example.com"],
    )

    decision = monitor.evaluate_tool_call(
        ["curl", "https://example.com"],
        write_paths=[tmp_path / "file.txt"],
        network_hosts=["example.com"],
    )

    assert decision.allowed is True

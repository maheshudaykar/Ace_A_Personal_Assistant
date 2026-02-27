"""Tests for nuclear switch activation and timeout."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ace.ace_kernel.audit_trail import AuditTrail
from ace.ace_kernel.nuclear_switch import NuclearSwitch


def test_activation_and_timeout(tmp_path) -> None:
    now = datetime(2026, 2, 27, 12, 0, 0, tzinfo=timezone.utc)
    time_state = {"now": now}

    def _time_fn() -> datetime:
        return time_state["now"]

    audit = AuditTrail(tmp_path / "audit.jsonl", time_fn=_time_fn)
    switch = NuclearSwitch(audit, passphrase="secret", timeout_minutes=10, time_fn=_time_fn)

    assert switch.activate("secret") is True
    assert switch.is_active() is True

    time_state["now"] = now + timedelta(minutes=11)
    assert switch.is_active() is False
    assert audit.verify_chain() is True


def test_activation_rejects_wrong_passphrase(tmp_path) -> None:
    now = datetime(2026, 2, 27, 12, 0, 0, tzinfo=timezone.utc)

    def _time_fn() -> datetime:
        return now

    audit = AuditTrail(tmp_path / "audit.jsonl", time_fn=_time_fn)
    switch = NuclearSwitch(audit, passphrase="secret", time_fn=_time_fn)

    assert switch.activate("wrong") is False
    assert switch.is_active() is False
    assert audit.verify_chain() is True

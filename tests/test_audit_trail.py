"""Tests for audit trail hash chaining."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ace.ace_kernel.audit_trail import AuditTrail


def _fixed_time() -> datetime:
    return datetime(2026, 2, 27, 12, 0, 0, tzinfo=timezone.utc)


def test_append_and_verify_chain(tmp_path: Path) -> None:
    audit_file = tmp_path / "audit.jsonl"
    trail = AuditTrail(audit_file, time_fn=_fixed_time)

    r1 = trail.append({"type": "boot", "detail": "start"})
    r2 = trail.append({"type": "event", "detail": "tick"})

    assert r1.prev_hash == "0" * 64
    assert r2.prev_hash == r1.hash
    assert trail.verify_chain() is True


def test_chain_detects_tamper(tmp_path: Path) -> None:
    audit_file = tmp_path / "audit.jsonl"
    trail = AuditTrail(audit_file, time_fn=_fixed_time)

    trail.append({"type": "boot", "detail": "start"})
    trail.append({"type": "event", "detail": "tick"})

    # Tamper with file contents directly.
    lines = audit_file.read_text(encoding="utf-8").splitlines()
    payload = lines[0].replace("start", "tampered")
    lines[0] = payload
    audit_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert trail.verify_chain() is False

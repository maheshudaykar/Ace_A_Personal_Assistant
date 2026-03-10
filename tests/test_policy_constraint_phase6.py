"""Tests for PolicyConstraintEngine (Phase 6)."""

import pytest

from ace.ace_kernel.audit_trail import AuditTrail
from ace.ace_kernel.policy_constraint_engine import PolicyConstraintEngine


@pytest.fixture()
def audit_trail(tmp_path):
    return AuditTrail(file_path=tmp_path / "audit.jsonl")


@pytest.fixture()
def engine(audit_trail):
    return PolicyConstraintEngine(audit_trail=audit_trail)


class TestPolicyValidation:
    def test_bugfix_allowed_for_kernel(self, engine):
        diff = """-    return x + 1\n+    return x + 2"""
        assert engine.validate_nuclear_change(
            "ace/ace_kernel/snapshot_engine.py", diff, declared_change_type="bugfix"
        ) is True

    def test_api_change_denied(self, engine):
        diff = """-def old_func():\n+def new_func():"""
        assert engine.validate_nuclear_change(
            "ace/ace_kernel/snapshot_engine.py", diff, declared_change_type="api_change"
        ) is False

    def test_removal_denied(self, engine):
        diff = """-class SnapshotEngine:\n-    pass"""
        assert engine.validate_nuclear_change(
            "ace/ace_kernel/snapshot_engine.py", diff, declared_change_type="removal"
        ) is False

    def test_governance_bypass_denied(self, engine):
        diff = """+skip_governance = True"""
        assert engine.validate_nuclear_change(
            "ace/ace_kernel/nuclear_switch.py", diff, declared_change_type="governance_bypass"
        ) is False


class TestRateLimiting:
    def test_rate_limit_enforcement(self, engine):
        module = "ace/ace_kernel/snapshot_engine.py"
        # Default allows 2 constraint_relaxation per week
        assert engine.check_rate_limit(module, "constraint_relaxation") is True
        engine.record_applied_modification(module, "constraint_relaxation")
        assert engine.check_rate_limit(module, "constraint_relaxation") is True
        engine.record_applied_modification(module, "constraint_relaxation")
        assert engine.check_rate_limit(module, "constraint_relaxation") is False

    def test_bugfix_no_rate_limit(self, engine):
        module = "ace/ace_kernel/snapshot_engine.py"
        for _ in range(10):
            engine.record_applied_modification(module, "bugfix")
        # Bugfix has no max_times_per_week
        assert engine.check_rate_limit(module, "bugfix") is True


class TestDiffSemantic:
    def test_empty_diff_rejected(self, engine):
        assert engine.validate_diff_semantic("") is False
        assert engine.validate_diff_semantic("   \n  ") is False

    def test_meaningful_diff_accepted(self, engine):
        diff = """-    return 42\n+    return 43"""
        assert engine.validate_diff_semantic(diff) is True

    def test_classify_change(self, engine):
        # Test heuristic classifier
        diff = """-def old():\n+def new():"""
        assert engine._classify_change("mod.py", diff) == "api_change"

        bugfix = """-    x = 1\n+    x = 2"""
        assert engine._classify_change("mod.py", bugfix) == "bugfix"

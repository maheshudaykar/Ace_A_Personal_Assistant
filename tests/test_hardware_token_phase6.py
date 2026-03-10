"""Tests for HardwareTokenManager (Phase 6)."""

import pytest

from ace.ace_kernel.audit_trail import AuditTrail
from ace.ace_kernel.hardware_token_manager import HardwareTokenManager


@pytest.fixture()
def audit_trail(tmp_path):
    return AuditTrail(file_path=tmp_path / "audit.jsonl")


@pytest.fixture()
def token_manager(audit_trail):
    return HardwareTokenManager(audit_trail=audit_trail, hmac_secret="test-secret")


class TestHardwareTokenRegistration:
    def test_register_and_list(self, token_manager):
        token = token_manager.register_token(
            username="admin",
            token_type="FIDO2",
            public_key_hex="aabbccdd",
            serial_number="SN-001",
        )
        assert token.token_id
        assert token.is_active
        assert token.registered_by == "admin"
        tokens = token_manager.list_tokens(username="admin")
        assert len(tokens) == 1
        assert tokens[0].token_id == token.token_id

    def test_unsupported_type_raises(self, token_manager):
        with pytest.raises(ValueError, match="Unsupported token_type"):
            token_manager.register_token("admin", "INVALID", "aabb", "SN-002")

    def test_revoke_token(self, token_manager):
        token = token_manager.register_token("admin", "PIV", "1122", "SN-003")
        assert token_manager.revoke_token(token.token_id) is True
        assert token_manager.get_token(token.token_id).is_active is False

    def test_revoke_nonexistent(self, token_manager):
        assert token_manager.revoke_token("nonexistent") is False


class TestHardwareTokenVerification:
    def test_sign_and_verify(self, token_manager):
        token = token_manager.register_token("admin", "FIDO2", "aabbccdd", "SN-010")
        signature = token_manager.sign_request("modify audit_trail.py", token.token_id)
        assert token_manager.verify_signature(signature, "modify audit_trail.py", token.token_id) is True

    def test_verify_wrong_data_fails(self, token_manager):
        token = token_manager.register_token("admin", "FIDO2", "aabbccdd", "SN-011")
        signature = token_manager.sign_request("modify audit_trail.py", token.token_id)
        # Different data should not verify
        assert token_manager.verify_signature(signature, "different data", token.token_id) is False

    def test_verify_inactive_token_fails(self, token_manager):
        token = token_manager.register_token("admin", "TPM2", "112233", "SN-012")
        token_manager.revoke_token(token.token_id)
        assert token_manager.verify_signature("abc", "data", token.token_id) is False

    def test_require_token_present(self, token_manager):
        assert token_manager.require_token_present("admin") is False
        token_manager.register_token("admin", "FIDO2", "aabb", "SN-020")
        assert token_manager.require_token_present("admin") is True

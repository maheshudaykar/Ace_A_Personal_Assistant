"""HardwareTokenManager: cryptographic hardware token verification for nuclear operations."""

from __future__ import annotations

import hashlib
import hmac
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ace.ace_kernel.audit_trail import AuditTrail

__all__ = ["HardwareToken", "HardwareTokenManager"]


@dataclass
class HardwareToken:
    """Registered hardware security token."""

    token_id: str
    token_type: str  # "FIDO2", "PIV", "TPM2"
    public_key_hex: str  # hex-encoded public key bytes
    serial_number: str
    registered_by: str
    registered_at: float = field(default_factory=time.time)
    last_used: float = 0.0
    is_active: bool = True


class HardwareTokenManager:
    """Manage hardware token registration and cryptographic verification.

    In production a real HSM/FIDO2 library drives the signing.  This
    implementation provides the governance API surface so that the rest
    of the nuclear pipeline can run end-to-end with deterministic test
    doubles injected for the actual cryptographic operations.
    """

    def __init__(
        self,
        audit_trail: AuditTrail,
        hmac_secret: str = "",
    ) -> None:
        self._audit = audit_trail
        # HMAC secret used for software-fallback signature verification.
        # In production this would be replaced by an HSM key reference.
        self._hmac_secret = hmac_secret.encode("utf-8") if hmac_secret else b""
        self._lock = threading.RLock()
        self._tokens: Dict[str, HardwareToken] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_token(
        self,
        username: str,
        token_type: str,
        public_key_hex: str,
        serial_number: str,
    ) -> HardwareToken:
        """Register a hardware security token for a user."""
        if token_type not in {"FIDO2", "PIV", "TPM2"}:
            raise ValueError(f"Unsupported token_type: {token_type}")
        if not public_key_hex or not serial_number:
            raise ValueError("public_key_hex and serial_number are required")

        token_id = hashlib.sha256(
            f"{username}|{serial_number}|{token_type}".encode("utf-8")
        ).hexdigest()[:16]

        token = HardwareToken(
            token_id=token_id,
            token_type=token_type,
            public_key_hex=public_key_hex,
            serial_number=serial_number,
            registered_by=username,
        )

        with self._lock:
            self._tokens[token_id] = token

        self._audit.append(
            {
                "type": "hardware_token.register",
                "token_id": token_id,
                "token_type": token_type,
                "registered_by": username,
                "serial_number": serial_number,
            }
        )
        return token

    def revoke_token(self, token_id: str) -> bool:
        """Deactivate a previously registered token."""
        with self._lock:
            token = self._tokens.get(token_id)
            if token is None:
                return False
            token.is_active = False
        self._audit.append({"type": "hardware_token.revoke", "token_id": token_id})
        return True

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def verify_signature(self, signature_hex: str, data: str, token_id: str) -> bool:
        """Verify that *signature_hex* was produced by the token for *data*.

        In production this delegates to the hardware device's public key via
        a FIDO2/PIV library.  The software fallback uses HMAC-SHA256 so that
        tests can exercise the full authorization pipeline deterministically.
        """
        with self._lock:
            token = self._tokens.get(token_id)
            if token is None or not token.is_active:
                self._audit.append(
                    {
                        "type": "hardware_token.verify_failed",
                        "token_id": token_id,
                        "reason": "token_not_found_or_inactive",
                    }
                )
                return False

        expected = self._compute_hmac(data, token.public_key_hex)
        valid = hmac.compare_digest(expected, signature_hex)

        with self._lock:
            if valid:
                token.last_used = time.time()

        self._audit.append(
            {
                "type": "hardware_token.verify",
                "token_id": token_id,
                "valid": valid,
            }
        )
        return valid

    def require_token_present(self, username: str) -> bool:
        """Return True if the user has at least one active registered token."""
        with self._lock:
            return any(
                t.is_active and t.registered_by == username
                for t in self._tokens.values()
            )

    def sign_request(self, data: str, token_id: str) -> str:
        """Produce an HMAC signature using the software fallback path.

        In production the private key lives inside the hardware device
        and the caller would interact with the device driver directly.
        This method exists so tests can generate valid signatures.
        """
        with self._lock:
            token = self._tokens.get(token_id)
            if token is None or not token.is_active:
                raise PermissionError("token not found or inactive")
        return self._compute_hmac(data, token.public_key_hex)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def list_tokens(self, username: Optional[str] = None) -> List[HardwareToken]:
        with self._lock:
            tokens = list(self._tokens.values())
        if username:
            tokens = [t for t in tokens if t.registered_by == username]
        return sorted(tokens, key=lambda t: (t.registered_by, t.token_id))

    def get_token(self, token_id: str) -> Optional[HardwareToken]:
        with self._lock:
            return self._tokens.get(token_id)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _compute_hmac(self, data: str, key_hex: str) -> str:
        """Deterministic HMAC-SHA256 using the token's public key as extra entropy."""
        combined_key = self._hmac_secret + bytes.fromhex(key_hex)
        return hmac.new(combined_key, data.encode("utf-8"), hashlib.sha256).hexdigest()

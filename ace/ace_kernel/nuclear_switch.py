"""Nuclear switch with passphrase activation and timeout-based auto-revoke."""

from __future__ import annotations

import hashlib
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from ace.ace_kernel.audit_trail import AuditTrail


@dataclass(frozen=True)
class NuclearStatus:
    """Current nuclear mode status."""

    active: bool
    expires_at: Optional[str]


class NuclearSwitch:
    """Controls privileged mode with passphrase and time-limited activation."""

    _PBKDF2_ITERATIONS = 600_000

    def __init__(
        self,
        audit_trail: AuditTrail,
        passphrase: str,
        timeout_minutes: int = 10,
        time_fn: Optional[Callable[[], datetime]] = None,
    ) -> None:
        if timeout_minutes <= 0:
            raise ValueError("timeout_minutes must be positive")
        self._audit = audit_trail
        self._salt = os.urandom(32)
        self._passphrase_hash = self._hash_passphrase(passphrase, self._salt)
        self._timeout = timedelta(minutes=timeout_minutes)
        self._time_fn = time_fn or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()
        self._active_until: Optional[datetime] = None

    def activate(self, passphrase: str) -> bool:
        """Attempt activation with passphrase; returns True on success."""
        with self._lock:
            if self._hash_passphrase(passphrase, self._salt) != self._passphrase_hash:
                self._audit.append({"type": "nuclear.activate.failed"})
                return False
            now = self._time_fn()
            self._active_until = now + self._timeout
            self._audit.append(
                {
                    "type": "nuclear.activate",
                    "expires_at": self._active_until.isoformat(),
                }
            )
            return True

    def is_active(self) -> bool:
        """Return True if nuclear mode is active, auto-revoking on timeout."""
        with self._lock:
            if self._active_until is None:
                return False
            now = self._time_fn()
            if now >= self._active_until:
                self._active_until = None
                self._audit.append({"type": "nuclear.auto_revoke"})
                return False
            return True

    def status(self) -> NuclearStatus:
        """Return current status for monitoring."""
        with self._lock:
            if self._active_until is None:
                return NuclearStatus(active=False, expires_at=None)
            now = self._time_fn()
            if now >= self._active_until:
                self._active_until = None
                self._audit.append({"type": "nuclear.auto_revoke"})
                return NuclearStatus(active=False, expires_at=None)
            return NuclearStatus(active=True, expires_at=self._active_until.isoformat())

    @staticmethod
    def _hash_passphrase(passphrase: str, salt: bytes) -> str:
        return hashlib.pbkdf2_hmac(
            "sha256", passphrase.encode("utf-8"), salt, NuclearSwitch._PBKDF2_ITERATIONS
        ).hex()

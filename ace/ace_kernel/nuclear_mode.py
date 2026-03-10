"""NuclearModeController: governed kernel modification orchestration for Phase 6."""

from __future__ import annotations

import copy
import hashlib
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Optional

from ace.ace_kernel.audit_trail import AuditTrail
from ace.ace_kernel.nuclear_switch import NuclearSwitch
from ace.ace_kernel.snapshot_engine import SnapshotEngine

__all__ = ["NuclearAuthorization", "NuclearModeController"]


@dataclass
class NuclearAuthorization:
    auth_id: str
    requested_by: str
    module_to_modify: str
    modification_diff: str
    reason: str
    risk_score: float
    status: str = "pending"
    snapshot_id_primary: Optional[str] = None
    snapshot_id_secondary: Optional[str] = None
    timestamp_utc: float = field(default_factory=time.time)
    authorized_by: Optional[str] = None


class NuclearModeController:
    """Enforces multi-gate policy for nuclear modifications."""

    IMMUTABLE_MODULES = {
        "ace/ace_kernel/audit_trail.py",
        "ace/ace_kernel/snapshot_engine.py",
        "ace/ace_kernel/nuclear_switch.py",
        "ace/distributed/consensus_engine.py",
        "ace/ace_memory/project_memory.py",
    }

    def __init__(
        self,
        audit_trail: AuditTrail,
        nuclear_switch: NuclearSwitch,
        snapshot_engine: SnapshotEngine,
        planning_validation_fn: Optional[Callable[[str], bool]] = None,
        experiment_validation_fn: Optional[Callable[[str], bool]] = None,
        extended_validation_fn: Optional[Callable[[str], bool]] = None,
        risk_weights: Optional[Dict[str, float]] = None,
    ) -> None:
        self._audit = audit_trail
        self._switch = nuclear_switch
        self._snapshot_engine = snapshot_engine
        self._planning_validation_fn = planning_validation_fn or (lambda _module: True)
        self._experiment_validation_fn = experiment_validation_fn or (lambda _module: True)
        self._extended_validation_fn = extended_validation_fn or (lambda _module: True)
        self._risk_weights = risk_weights or {
            "base": 0.2,
            "consensus": 0.4,
            "has_diff_changes": 0.2,
            "large_diff": 0.2,
        }
        self._lock = threading.RLock()
        self._auths: Dict[str, NuclearAuthorization] = {}

    def request_nuclear_modification(
        self,
        requested_by: str,
        module_to_modify: str,
        modification_diff: str,
        reason: str,
    ) -> NuclearAuthorization:
        self._enforce_module_guardrails(module_to_modify, modification_diff)
        risk = self._compute_modification_risk(module_to_modify, modification_diff)
        auth_id = hashlib.sha256(
            f"{requested_by}|{module_to_modify}|{time.time():.6f}".encode("utf-8")
        ).hexdigest()[:16]
        auth = NuclearAuthorization(
            auth_id=auth_id,
            requested_by=requested_by,
            module_to_modify=module_to_modify,
            modification_diff=modification_diff,
            reason=reason,
            risk_score=risk,
        )
        with self._lock:
            self._auths[auth_id] = auth
        self._audit.append(
            {
                "type": "nuclear.request",
                "auth_id": auth_id,
                "requested_by": requested_by,
                "module": module_to_modify,
                "risk_score": risk,
                "reason": reason,
            }
        )
        return auth

    def authorize_nuclear_modification(self, auth_id: str, authorized_by: str) -> bool:
        with self._lock:
            auth = self._auths.get(auth_id)
            if auth is None:
                return False
            if not self._switch.is_active():
                raise PermissionError("nuclear switch is not active")

            if not self._planning_validation_fn(auth.module_to_modify):
                raise PermissionError("planning-layer validation missing")
            if not self._experiment_validation_fn(auth.module_to_modify):
                raise PermissionError("experiment safety validation missing")

            primary = self._snapshot_engine.save_state({"auth_id": auth_id, "module": auth.module_to_modify})
            auth.snapshot_id_primary = primary.snapshot_id

            if self._requires_extended_checks(auth.module_to_modify):
                secondary = self._snapshot_engine.save_state(
                    {"auth_id": auth_id, "module": auth.module_to_modify, "phase": "secondary"}
                )
                auth.snapshot_id_secondary = secondary.snapshot_id

            auth.status = "approved"
            auth.authorized_by = authorized_by
            self._audit.append(
                {
                    "type": "nuclear.authorize",
                    "auth_id": auth_id,
                    "authorized_by": authorized_by,
                    "snapshot_primary": auth.snapshot_id_primary,
                    "snapshot_secondary": auth.snapshot_id_secondary,
                }
            )
            return True

    def apply_nuclear_modification(self, auth_id: str) -> bool:
        with self._lock:
            auth = self._auths.get(auth_id)
            if auth is None:
                return False
            if auth.status != "approved":
                raise PermissionError("authorization not approved")

            if self._requires_extended_checks(auth.module_to_modify):
                if auth.snapshot_id_secondary is None:
                    raise PermissionError("secondary snapshot required for distributed module modification")
                if not self._extended_validation_fn(auth.module_to_modify):
                    raise PermissionError("extended validation failed for distributed module modification")

            # Patch application is intentionally externalized; this controller
            # enforces policy gates and auditability around the operation.
            auth.status = "applied"
            self._audit.append(
                {
                    "type": "nuclear.apply",
                    "auth_id": auth_id,
                    "module": auth.module_to_modify,
                    "status": auth.status,
                }
            )
            return True

    def get_authorization(self, auth_id: str) -> Optional[NuclearAuthorization]:
        with self._lock:
            auth = self._auths.get(auth_id)
            return copy.copy(auth) if auth is not None else None

    def _enforce_module_guardrails(self, module: str, diff_text: str) -> None:
        normalized = module.replace("\\", "/")
        if normalized.endswith("/project_memory.py") and "schema_version" in diff_text.lower():
            self._audit.append(
                {"type": "nuclear.guardrail_blocked", "module": module, "reason": "schema_version_change"}
            )
            raise PermissionError("project memory schema changes are blocked in nuclear mode")
        if normalized.endswith("/consensus_engine.py") and "bypass" in diff_text.lower():
            self._audit.append(
                {"type": "nuclear.guardrail_blocked", "module": module, "reason": "consensus_bypass"}
            )
            raise PermissionError("consensus modifications cannot bypass extra verification")
        if not self._is_module_immutable(normalized):
            self._audit.append(
                {"type": "nuclear.guardrail_blocked", "module": module, "reason": "not_immutable"}
            )
            raise PermissionError("nuclear mode only applies to immutable governance modules")

    def _compute_modification_risk(self, module: str, diff_text: str) -> float:
        w = self._risk_weights
        risk = w.get("base", 0.2)
        if "consensus" in module:
            risk += w.get("consensus", 0.4)
        if "-" in diff_text and "+" in diff_text:
            risk += w.get("has_diff_changes", 0.2)
        if len(diff_text.splitlines()) > 200:
            risk += w.get("large_diff", 0.2)
        return min(1.0, max(0.0, risk))

    def _is_module_immutable(self, module: str) -> bool:
        return module in self.IMMUTABLE_MODULES

    def _requires_extended_checks(self, module: str) -> bool:
        """Only critical distributed modules require dual-snapshot extended checks."""
        normalized = module.replace("\\", "/")
        extended_modules = {
            "ace/distributed/consensus_engine.py",
            "ace/distributed/memory_sync.py",
            "ace/distributed/byzantine_detector.py",
        }
        return normalized in extended_modules

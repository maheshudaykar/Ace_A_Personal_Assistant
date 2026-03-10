"""PolicyConstraintEngine: constraint validation for nuclear modifications."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ace.ace_kernel.audit_trail import AuditTrail

__all__ = ["ModificationConstraint", "PolicyConstraintEngine"]

KERNEL_MODULE_GLOB = "ace/ace_kernel/*"
POLICY_DENIED_EVENT = "policy.denied"
API_DEF_TOKEN = "def "
API_CLASS_TOKEN = "class "


@dataclass
class ModificationConstraint:
    """A single constraint on allowed modifications."""

    constraint_id: str
    module_pattern: str  # glob-like: "ace/ace_kernel/*.py"
    change_type: str  # "bugfix", "constraint_relaxation", "constraint_tightening", "api_change", "removal"
    allowed: bool
    requires_snapshot: bool = True
    min_tests_required: int = 3
    requires_manual_review: bool = False
    max_times_per_week: Optional[int] = None


_DEFAULT_CONSTRAINTS: List[ModificationConstraint] = [
    ModificationConstraint(
        constraint_id="POL-001",
        module_pattern=KERNEL_MODULE_GLOB,
        change_type="bugfix",
        allowed=True,
        requires_snapshot=True,
        min_tests_required=3,
    ),
    ModificationConstraint(
        constraint_id="POL-002",
        module_pattern=KERNEL_MODULE_GLOB,
        change_type="constraint_relaxation",
        allowed=True,
        requires_snapshot=True,
        min_tests_required=5,
        max_times_per_week=2,
    ),
    ModificationConstraint(
        constraint_id="POL-003",
        module_pattern=KERNEL_MODULE_GLOB,
        change_type="constraint_tightening",
        allowed=True,
        requires_snapshot=True,
        min_tests_required=10,
        requires_manual_review=True,
        max_times_per_week=1,
    ),
    ModificationConstraint(
        constraint_id="POL-004",
        module_pattern="*",
        change_type="api_change",
        allowed=False,
    ),
    ModificationConstraint(
        constraint_id="POL-005",
        module_pattern="*",
        change_type="removal",
        allowed=False,
    ),
    ModificationConstraint(
        constraint_id="POL-006",
        module_pattern="*",
        change_type="governance_bypass",
        allowed=False,
    ),
    ModificationConstraint(
        constraint_id="POL-007",
        module_pattern="ace/distributed/*",
        change_type="bugfix",
        allowed=True,
        requires_snapshot=True,
        min_tests_required=5,
    ),
]


class PolicyConstraintEngine:
    """Enforce structured constraints on nuclear modifications.

    Each proposed change must pass:
    1. Module scope check (is it in the allowed modules list?).
    2. Change type classification and policy lookup.
    3. Rate-limit enforcement (max N changes of type T per week).
    4. Semantic diff validation (reject trivial / contradictory changes).
    """

    def __init__(
        self,
        audit_trail: AuditTrail,
        constraints: Optional[List[ModificationConstraint]] = None,
    ) -> None:
        self._audit = audit_trail
        self._lock = threading.RLock()
        self._constraints = list(constraints or _DEFAULT_CONSTRAINTS)
        # Track applied modifications: list of (module, change_type, timestamp)
        self._modification_history: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_nuclear_change(
        self,
        module: str,
        diff_text: str,
        declared_change_type: Optional[str] = None,
    ) -> bool:
        """Return True if the proposed change passes all policy gates."""
        change_type = declared_change_type or self._classify_change(module, diff_text)

        constraint = self._find_constraint(module, change_type)
        if constraint is None or not constraint.allowed:
            self._audit.append(
                {
                    "type": POLICY_DENIED_EVENT,
                    "module": module,
                    "change_type": change_type,
                    "reason": "no_matching_allowed_policy",
                }
            )
            return False

        if not self._check_rate_limit(change_type, constraint):
            self._audit.append(
                {
                    "type": POLICY_DENIED_EVENT,
                    "module": module,
                    "change_type": change_type,
                    "reason": "rate_limit_exceeded",
                }
            )
            return False

        if not self.validate_diff_semantic(diff_text):
            self._audit.append(
                {
                    "type": POLICY_DENIED_EVENT,
                    "module": module,
                    "change_type": change_type,
                    "reason": "trivial_or_invalid_diff",
                }
            )
            return False

        self._audit.append(
            {
                "type": "policy.approved",
                "module": module,
                "change_type": change_type,
                "constraint_id": constraint.constraint_id,
            }
        )
        return True

    def record_applied_modification(self, module: str, change_type: str) -> None:
        """Record that a nuclear modification was successfully applied (for rate tracking)."""
        with self._lock:
            self._modification_history.append(
                {"module": module, "change_type": change_type, "timestamp": time.time()}
            )

    def get_constraint_for(self, module: str, change_type: str) -> Optional[ModificationConstraint]:
        """Return the matching constraint, if any."""
        return self._find_constraint(module, change_type)

    def validate_diff_semantic(self, diff_text: str) -> bool:
        """Return False for trivial (whitespace-only) or empty diffs."""
        if not diff_text or not diff_text.strip():
            return False
        meaningful_lines = [
            line
            for line in diff_text.splitlines()
            if line.startswith(("+", "-"))
            and line.strip() not in {"+", "-", "+++", "---"}
            and line.strip().replace("+", "").replace("-", "").strip()
        ]
        return len(meaningful_lines) > 0

    def check_rate_limit(self, module: str, change_type: str) -> bool:
        """Public rate-limit check."""
        constraint = self._find_constraint(module, change_type)
        if constraint is None:
            return False
        return self._check_rate_limit(change_type, constraint)

    def list_constraints(self) -> List[ModificationConstraint]:
        return list(self._constraints)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _find_constraint(self, module: str, change_type: str) -> Optional[ModificationConstraint]:
        """Find most specific matching constraint (exact module > wildcard)."""
        normalized = module.replace("\\", "/")
        best: Optional[ModificationConstraint] = None
        best_specificity = -1
        for c in self._constraints:
            if c.change_type != change_type:
                continue
            specificity = self._match_pattern(c.module_pattern, normalized)
            if specificity > best_specificity:
                best = c
                best_specificity = specificity
        return best

    @staticmethod
    def _match_pattern(pattern: str, module: str) -> int:
        """Return specificity score (>0 match, -1 no match)."""
        if pattern == "*":
            return 0
        # Simple prefix glob: "ace/ace_kernel/*"
        if pattern.endswith("/*"):
            prefix = pattern[:-1]  # "ace/ace_kernel/"
            if module.startswith(prefix):
                return len(prefix)
        if pattern == module:
            return len(module) + 100  # exact match is most specific
        return -1

    def _check_rate_limit(self, change_type: str, constraint: ModificationConstraint) -> bool:
        if constraint.max_times_per_week is None:
            return True
        one_week_ago = time.time() - 7 * 86400
        with self._lock:
            count = sum(
                1
                for entry in self._modification_history
                if entry["change_type"] == change_type and entry["timestamp"] >= one_week_ago
            )
        return count < constraint.max_times_per_week

    def _classify_change(self, _module: str, diff_text: str) -> str:
        """Heuristic classification of a diff into a change type."""
        lines = diff_text.splitlines()
        removals = sum(1 for l in lines if l.startswith("-") and not l.startswith("---"))
        additions = sum(1 for l in lines if l.startswith("+") and not l.startswith("+++"))

        if removals > 0 and additions == 0:
            return "removal"

        if self._is_api_change(lines):
            return "api_change"

        if self._contains_governance_bypass(lines):
            return "governance_bypass"
        if additions > removals * 2:
            return "constraint_relaxation"
        if removals > additions * 2:
            return "constraint_tightening"
        return "bugfix"

    @staticmethod
    def _has_api_tokens(line: str) -> bool:
        return API_DEF_TOKEN in line or API_CLASS_TOKEN in line

    def _is_api_change(self, lines: List[str]) -> bool:
        changed_lines = [l for l in lines if l.startswith(("+", "-"))]
        if not any(self._has_api_tokens(l) for l in changed_lines):
            return False
        api_adds = [l for l in lines if l.startswith("+") and self._has_api_tokens(l)]
        api_dels = [l for l in lines if l.startswith("-") and self._has_api_tokens(l)]
        return bool(api_adds and api_dels)

    @staticmethod
    def _contains_governance_bypass(lines: List[str]) -> bool:
        return any("bypass" in l.lower() or "skip" in l.lower() for l in lines)

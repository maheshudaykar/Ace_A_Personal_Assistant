"""Security monitor for tool misuse detection and policy enforcement."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence
from urllib.parse import urlparse

from ace.ace_kernel.audit_trail import AuditTrail
from ace.ace_kernel.nuclear_switch import NuclearSwitch


@dataclass(frozen=True)
class SecurityDecision:
    """Security decision outcome."""

    allowed: bool
    reasons: List[str]
    risk_score: float


class SecurityMonitor:
    """Enforce security rules on tool execution requests."""

    def __init__(
        self,
        audit_trail: AuditTrail,
        nuclear_switch: NuclearSwitch,
        workspace_root: str | Path,
        allowed_hosts: Sequence[str] | None = None,
    ) -> None:
        self._audit = audit_trail
        self._nuclear = nuclear_switch
        self._root = Path(workspace_root).resolve()
        self._allowed_hosts = {
            normalized
            for host in (allowed_hosts or [])
            for normalized in [self._normalize_host(host)]
            if normalized is not None
        }

    def evaluate_tool_call(
        self,
        command: Sequence[str],
        write_paths: Iterable[str | Path] | None = None,
        network_hosts: Iterable[str] | None = None,
        requires_sudo: bool = False,
    ) -> SecurityDecision:
        """Evaluate a tool call and return enforcement decision."""
        reasons: List[str] = []
        risk = 0.0

        if requires_sudo and not self._nuclear.is_active():
            reasons.append("sudo_blocked_nuclear_inactive")
            risk += 0.7

        if write_paths:
            for path in write_paths:
                try:
                    resolved = Path(path).resolve()
                except (OSError, RuntimeError, ValueError):
                    reasons.append(f"write_path_invalid:{path}")
                    risk += 0.4
                    continue
                if not self._is_within_root(resolved):
                    reasons.append(f"write_outside_workspace:{resolved}")
                    risk += 0.4

        if network_hosts:
            for host in network_hosts:
                normalized = self._normalize_host(host)
                if normalized is None or normalized not in self._allowed_hosts:
                    reasons.append(f"network_host_blocked:{host}")
                    risk += 0.3

        allowed = len(reasons) == 0
        decision = SecurityDecision(allowed=allowed, reasons=reasons, risk_score=min(risk, 1.0))
        self._audit.append(
            {
                "type": "security.decision",
                "command": list(command),
                "allowed": decision.allowed,
                "reasons": decision.reasons,
                "risk_score": decision.risk_score,
            }
        )
        return decision

    @staticmethod
    def _normalize_host(host: str) -> Optional[str]:
        parsed = urlparse(host)
        candidate = parsed.hostname or host
        candidate = candidate.strip().lower().rstrip(".")
        return candidate or None

    def _is_within_root(self, path: Path) -> bool:
        try:
            path.relative_to(self._root)
        except ValueError:
            return False
        return True

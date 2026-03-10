"""NodeTrustManager: trust policy enforcement for cross-node operations."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Set

from ace.distributed.node_registry import NodeRegistry
from ace.distributed.types import TrustLevel

__all__ = ["CapabilityClass", "NodeCapabilityPolicy", "NodeTrustManager"]


class CapabilityClass(str, Enum):
    OS_CONTROL = "os_control"
    NETWORK = "network"
    MEMORY = "memory"
    EXECUTION = "execution"
    STRUCTURAL = "structural"
    NUCLEAR = "nuclear"


@dataclass
class NodeCapabilityPolicy:
    trust_level: str
    allowed_capabilities: List[str]
    blocked_capabilities: List[str]
    allowed_tools: List[str]
    blocked_tools: List[str]
    max_parallel_tasks: int
    max_memory_per_task_mb: int


class NodeTrustManager:
    """Governance guard for node trust, risk scoring, and data access."""

    def __init__(self, node_registry: NodeRegistry) -> None:
        self.node_registry = node_registry
        self._lock = threading.RLock()
        self._policies = self._load_default_policies()
        self._last_audit_days: Dict[str, int] = {}

    def _load_default_policies(self) -> Dict[str, NodeCapabilityPolicy]:
        return {
            "FULL": NodeCapabilityPolicy(
                trust_level="FULL",
                allowed_capabilities=["*"],
                blocked_capabilities=[],
                allowed_tools=["*"],
                blocked_tools=[],
                max_parallel_tasks=16,
                max_memory_per_task_mb=4096,
            ),
            "RESTRICTED": NodeCapabilityPolicy(
                trust_level="RESTRICTED",
                allowed_capabilities=["execution.*", "memory.read", "network.http"],
                blocked_capabilities=["nuclear.*", "structural.*"],
                allowed_tools=["file_read", "memory_query", "test_runner"],
                blocked_tools=["file_delete", "code_generator"],
                max_parallel_tasks=8,
                max_memory_per_task_mb=2048,
            ),
            "EXPERIMENTAL": NodeCapabilityPolicy(
                trust_level="EXPERIMENTAL",
                allowed_capabilities=["execution.sandbox", "memory.read"],
                blocked_capabilities=["nuclear.*", "structural.*", "os_control.*"],
                allowed_tools=["memory_query"],
                blocked_tools=["file_delete", "terminal"],
                max_parallel_tasks=4,
                max_memory_per_task_mb=1024,
            ),
            "QUARANTINE": NodeCapabilityPolicy(
                trust_level="QUARANTINE",
                allowed_capabilities=[],
                blocked_capabilities=["*"],
                allowed_tools=[],
                blocked_tools=["*"],
                max_parallel_tasks=0,
                max_memory_per_task_mb=0,
            ),
        }

    def can_node_execute(self, node_id: str, action: str) -> bool:
        with self._lock:
            node = self.node_registry.get_node(node_id)
            if node is None:
                return False
            policy = self._policies[node.trust_level.value]
            if "*" in policy.blocked_capabilities:
                return False
            if "*" in policy.allowed_capabilities:
                return True
            if action in policy.blocked_capabilities:
                return False
            return any(action.startswith(prefix.rstrip("*")) for prefix in policy.allowed_capabilities)

    def update_node_trust(self, node_id: str, new_trust_level: str) -> bool:
        level = TrustLevel[new_trust_level]
        return self.node_registry.update_node_trust(node_id, level, reason="trust manager update")

    def compute_node_risk_score(self, node_id: str) -> float:
        with self._lock:
            node = self.node_registry.get_node(node_id)
            if node is None:
                return 1.0
            trust_factor = {
                TrustLevel.FULL: 0.1,
                TrustLevel.RESTRICTED: 0.4,
                TrustLevel.EXPERIMENTAL: 0.7,
                TrustLevel.QUARANTINE: 0.95,
            }[node.trust_level]
            suspicion = max(0.0, min(node.suspicion_score, 1.0))
            failures = 0.3 if node.status.value in {"FAILED", "QUARANTINED"} else 0.0
            audit_age = min(self._last_audit_days.get(node_id, 0) / 30.0, 1.0)
            return min(1.0, 0.4 * trust_factor + 0.3 * suspicion + 0.2 * failures + 0.1 * audit_age)

    def enforce_cross_node_delegation(self, source_node_id: str, target_node_id: str) -> bool:
        src = self.node_registry.get_node(source_node_id)
        tgt = self.node_registry.get_node(target_node_id)
        if not src or not tgt:
            return False
        order = {
            TrustLevel.QUARANTINE: 0,
            TrustLevel.EXPERIMENTAL: 1,
            TrustLevel.RESTRICTED: 2,
            TrustLevel.FULL: 3,
        }
        return order[src.trust_level] >= order[tgt.trust_level]

    def check_data_access(self, node_id: str, data_tag: str) -> bool:
        node = self.node_registry.get_node(node_id)
        if node is None:
            return False
        allowed: Dict[TrustLevel, Set[str]] = {
            TrustLevel.FULL: {"public", "internal", "confidential", "sensitive", "secret"},
            TrustLevel.RESTRICTED: {"public", "internal", "confidential"},
            TrustLevel.EXPERIMENTAL: {"public", "internal"},
            TrustLevel.QUARANTINE: set(),
        }
        return data_tag in allowed[node.trust_level]

    def set_last_audit_age_days(self, node_id: str, days: int) -> None:
        with self._lock:
            self._last_audit_days[node_id] = max(0, days)

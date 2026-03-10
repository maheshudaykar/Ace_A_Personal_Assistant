"""DistributedPlanner: deterministic placement of workflow tasks across cluster."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, cast

from ace.ace_cognitive.coordinator_agent import WorkflowPlan, WorkflowStep
from ace.distributed.node_registry import NodeRegistry
from ace.distributed.task_delegator import TaskDelegator

logger = logging.getLogger(__name__)

__all__ = ["PlacementDecision", "DistributedPlan", "DistributedPlanner"]


def _str_any_dict_default() -> Dict[str, Any]:
    return {}


@dataclass
class PlacementDecision:
    step_id: str
    execution_target: str  # "local" or node_id
    reason: str
    required_capabilities: Dict[str, Any] = field(default_factory=_str_any_dict_default)


@dataclass
class DistributedPlan:
    workflow_id: str
    placements: List[PlacementDecision]
    metadata: Dict[str, Any] = field(default_factory=_str_any_dict_default)


class DistributedPlanner:
    """Create reproducible distributed placements with capability matching."""

    def __init__(
        self,
        local_node_id: str,
        node_registry: NodeRegistry,
        task_delegator: TaskDelegator,
        max_distributed_tasks_per_node: int = 8,
    ) -> None:
        self.local_node_id = local_node_id
        self.node_registry = node_registry
        self.task_delegator = task_delegator
        self.max_distributed_tasks_per_node = max_distributed_tasks_per_node
        self._assigned_counts: Dict[str, int] = {}

    def plan_workflow(self, workflow: WorkflowPlan) -> DistributedPlan:
        """Plan local vs remote execution for each step deterministically."""
        placements: List[PlacementDecision] = []
        for step in sorted(workflow.steps, key=lambda s: s.step_id):
            required = self._extract_requirements(step)
            target = self._select_target(step, required)
            reason = "local_default" if target == "local" else f"capability_match:{target}"
            placements.append(
                PlacementDecision(
                    step_id=step.step_id,
                    execution_target=target,
                    reason=reason,
                    required_capabilities=required,
                )
            )

        return DistributedPlan(
            workflow_id=workflow.plan_id,
            placements=placements,
            metadata={"placement_count": len(placements)},
        )

    def _select_target(self, step: WorkflowStep, required: Dict[str, Any]) -> str:
        if self._should_prefer_local(required):
            return "local"

        candidates = self.node_registry.find_capable_nodes(required)
        if not candidates:
            return "local"

        ordered = sorted(
            candidates,
            key=lambda m: (
                -m.match_score,
                self._assigned_counts.get(m.node_id, 0),
                self._stable_hash(m.node_id + step.step_id),
            ),
        )
        for candidate in ordered:
            assigned = self._assigned_counts.get(candidate.node_id, 0)
            if assigned >= self.max_distributed_tasks_per_node:
                continue
            self._assigned_counts[candidate.node_id] = assigned + 1
            return candidate.node_id

        logger.warning(
            "All %d candidate nodes saturated (max %d tasks each); falling back to local execution",
            len(ordered),
            self.max_distributed_tasks_per_node,
        )
        return "local"

    @staticmethod
    def _extract_requirements(step: WorkflowStep) -> Dict[str, Any]:
        req_obj = step.inputs.get("required_capabilities", {})
        if not isinstance(req_obj, dict):
            return {}
        req = cast(Dict[str, Any], req_obj)
        return dict(req)

    def _should_prefer_local(self, required: Dict[str, Any]) -> bool:
        if required.get("requires_gpu", False):
            return False
        if int(required.get("min_cpu_cores", 1)) <= 2 and float(required.get("min_ram_gb", 1.0)) <= 4.0:
            return True
        return False

    @staticmethod
    def _stable_hash(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

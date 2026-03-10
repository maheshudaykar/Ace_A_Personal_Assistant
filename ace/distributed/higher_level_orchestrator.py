"""HigherLevelOrchestrator: execute workflow plans with distributed placements."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set, cast

from ace.ace_cognitive.coordinator_agent import CoordinatorAgent, WorkflowPlan, WorkflowStep
from ace.distributed.distributed_planner import DistributedPlan, DistributedPlanner
from ace.distributed.memory_federation import MemoryFederation
from ace.distributed.task_delegator import DelegatedTask, TaskDelegator
from ace.runtime.golden_trace import GoldenTrace

logger = logging.getLogger(__name__)

__all__ = ["DistributedWorkflowResult", "HigherLevelOrchestrator"]


def _str_any_dict_default() -> Dict[str, Any]:
    return {}


def _str_list_default() -> List[str]:
    return []


@dataclass
class DistributedWorkflowResult:
    workflow_id: str
    status: str
    step_results: Dict[str, Any] = field(default_factory=_str_any_dict_default)
    remote_steps: List[str] = field(default_factory=_str_list_default)
    local_steps: List[str] = field(default_factory=_str_list_default)
    consistency_ok: bool = True


class HigherLevelOrchestrator:
    """Coordinates local and remote execution using DistributedPlanner."""

    def __init__(
        self,
        coordinator: CoordinatorAgent,
        distributed_planner: DistributedPlanner,
        task_delegator: TaskDelegator,
        memory_federation: MemoryFederation,
        max_task_retries: int = 3,
    ) -> None:
        self.coordinator = coordinator
        self.distributed_planner = distributed_planner
        self.task_delegator = task_delegator
        self.memory_federation = memory_federation
        self.max_task_retries = max_task_retries
        self._trace = GoldenTrace.get_instance()

    def plan_distributed_execution(self, workflow: WorkflowPlan) -> DistributedPlan:
        return self.distributed_planner.plan_workflow(workflow)

    def execute_distributed_workflow(self, workflow: WorkflowPlan) -> DistributedWorkflowResult:
        placements = self.plan_distributed_execution(workflow)
        step_map: Dict[str, WorkflowStep] = {}
        for step in workflow.steps:
            if step.step_id in step_map:
                raise ValueError(f"Duplicate step_id in workflow: {step.step_id}")
            step_map[step.step_id] = step

        result = DistributedWorkflowResult(workflow_id=workflow.plan_id, status="running")

        for placement in placements.placements:
            step = step_map.get(placement.step_id)
            if step is None:
                logger.error("Placement references unknown step_id: %s", placement.step_id)
                continue

            if placement.execution_target == "local":
                self._run_local_step(step)
                result.local_steps.append(step.step_id)
            else:
                self._run_remote_step(step, placement.execution_target)
                result.remote_steps.append(step.step_id)

            result.step_results[step.step_id] = {
                "status": step.status,
                "result": step.result,
                "error": step.error,
            }

        result.consistency_ok = self.validate_consistency(result.step_results)
        result.status = "failed" if any(v["status"] == "failed" for v in result.step_results.values()) else "done"
        self._trace.log_event(
            "orchestrator.workflow_complete",
            {
                "workflow_id": workflow.plan_id,
                "status": result.status,
                "local_steps": len(result.local_steps),
                "remote_steps": len(result.remote_steps),
                "consistency_ok": result.consistency_ok,
            },
        )
        return result

    def aggregate_results(self, step_results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        ordered = sorted(step_results.items(), key=lambda item: item[0])
        merged: Dict[str, Any] = {"steps": []}
        for step_id, payload in ordered:
            merged["steps"].append({"step_id": step_id, **payload})
        return merged

    def validate_consistency(self, step_results: Dict[str, Dict[str, Any]]) -> bool:
        # Deterministic consistency check: no duplicate non-null result IDs and no silent failures.
        seen_keys: Set[str] = set()
        for step_id in sorted(step_results.keys()):
            payload = step_results[step_id]
            if payload["status"] == "failed" and not payload.get("error"):
                return False
            result = payload.get("result")
            if isinstance(result, dict) and "id" in result:
                result_map = cast(Dict[str, Any], result)
                result_id = result_map.get("id")
                if result_id is None:
                    continue
                key = str(result_id)
                if key in seen_keys:
                    return False
                seen_keys.add(key)
        return True

    def _run_local_step(self, step: WorkflowStep) -> None:
        # Reuse coordinator execution path for single-step local execution.
        one_step_plan = WorkflowPlan(plan_id=f"local-{step.step_id}", workflow_type="distributed_local", steps=[step])
        self.coordinator.execute_plan(one_step_plan)

    def _run_remote_step(self, step: WorkflowStep, node_id: str) -> None:
        task = DelegatedTask(
            task_id=step.step_id,
            agent_id=step.agent_id,
            target_node=node_id,
            fn_name=step.action,
            args=dict(step.inputs),
            timeout_ms=30_000,
        )

        attempts = 0
        while attempts < self.max_task_retries:
            attempts += 1
            self.task_delegator.delegate_task(task)
            remote = self.task_delegator.await_remote_result(step.step_id, timeout_ms=task.timeout_ms)
            if remote and remote.success:
                step.status = "done"
                step.result = {
                    "node_id": node_id,
                    "stdout": remote.stdout,
                    "duration_ms": remote.duration_ms,
                }
                self.memory_federation.synchronize_to_cluster("episodic")
                return
            if attempts >= self.max_task_retries:
                step.status = "failed"
                step.error = "remote execution failed"
                return
            time.sleep(0.01)

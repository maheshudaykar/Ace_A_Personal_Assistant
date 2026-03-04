"""CoordinatorAgent: Task decomposition and workflow orchestration for Phase 4."""
from __future__ import annotations

import logging
import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ace.runtime.agent_bus import AgentBus, AgentMessage
from ace.runtime.golden_trace import GoldenTrace

__all__ = ["WorkflowStep", "WorkflowPlan", "CoordinatorAgent"]

logger = logging.getLogger(__name__)


@dataclass
class WorkflowStep:
    """Single step inside a workflow plan."""

    step_id: str
    agent_id: str
    action: str
    inputs: Dict[str, Any]
    dependencies: List[str]  # step_ids this step depends on
    status: str = "pending"  # pending / running / done / failed
    result: Any = None
    error: Optional[str] = None


@dataclass
class WorkflowPlan:
    """Ordered set of steps representing one workflow execution."""

    plan_id: str
    workflow_type: str  # "proactive" or "code_analysis"
    steps: List[WorkflowStep]
    created_at: float = field(default_factory=time.time)
    status: str = "pending"  # pending / running / done / failed / aborted


class CoordinatorAgent:
    """
    Plans and orchestrates multi-step workflows.

    The CoordinatorAgent decomposes high-level tasks into ordered workflow
    steps and routes execution through AgentBus → ValidatorAgent →
    ExecutorAgent.  It never executes actions directly.

    Memory note: Completed workflows should be persisted via EpisodicMemory
    (ace.ace_memory.episodic_memory); this agent holds them only in memory.
    """

    AGENT_ID = "coordinator"
    MAX_RETRIES = 3

    def __init__(
        self,
        bus: AgentBus,
        audit_trail=None,
        seed: int = 42,
    ) -> None:
        self._random = random.Random(seed)
        self._bus = bus
        self._audit = audit_trail
        self._trace = GoldenTrace.get_instance()
        self._lock = threading.Lock()
        self._plans: Dict[str, WorkflowPlan] = {}
        self._bus.subscribe(self.AGENT_ID, self._handle_message)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_plan(
        self, workflow_type: str, steps: List[WorkflowStep]
    ) -> WorkflowPlan:
        """Create and register a new workflow plan."""
        plan = WorkflowPlan(
            plan_id=str(uuid.uuid4()),
            workflow_type=workflow_type,
            steps=steps,
        )
        with self._lock:
            self._plans[plan.plan_id] = plan
        self._log("plan_created", {"plan_id": plan.plan_id, "workflow_type": workflow_type})
        logger.info("CoordinatorAgent: plan %s created (%d steps)", plan.plan_id, len(steps))
        return plan

    def execute_plan(self, plan: WorkflowPlan) -> WorkflowPlan:
        """
        Drive the plan to completion, respecting step dependencies.

        Routes each step to the appropriate agent via AgentBus.
        Applies retry logic on failure (up to MAX_RETRIES).
        """
        plan.status = "running"
        self._log("plan_started", {"plan_id": plan.plan_id})

        for step in plan.steps:
            if not self._deps_satisfied(step, plan):
                step.status = "failed"
                step.error = "dependency failed"
                logger.warning(
                    "CoordinatorAgent: step %s skipped (dep failed)", step.step_id
                )
                continue

            self._execute_step_with_retry(step, plan)

        failed = any(s.status == "failed" for s in plan.steps)
        plan.status = "failed" if failed else "done"
        self._log("plan_finished", {"plan_id": plan.plan_id, "status": plan.status})
        return plan

    def get_plan(self, plan_id: str) -> Optional[WorkflowPlan]:
        with self._lock:
            return self._plans.get(plan_id)

    def list_plans(self) -> List[WorkflowPlan]:
        with self._lock:
            return list(self._plans.values())

    # ------------------------------------------------------------------
    # Internal execution
    # ------------------------------------------------------------------

    def _execute_step_with_retry(self, step: WorkflowStep, plan: WorkflowPlan) -> None:
        for attempt in range(1, self.MAX_RETRIES + 1):
            step.status = "running"
            try:
                self._dispatch_step(step, plan)
                if step.status == "done":
                    return
            except Exception as exc:
                step.error = str(exc)
                logger.warning(
                    "CoordinatorAgent: step %s attempt %d failed: %s",
                    step.step_id, attempt, exc,
                )
            if attempt < self.MAX_RETRIES:
                logger.info(
                    "CoordinatorAgent: retrying step %s (attempt %d)", step.step_id, attempt + 1
                )
        step.status = "failed"
        self._log(
            "step_failed",
            {"plan_id": plan.plan_id, "step_id": step.step_id, "error": step.error},
        )

    def _dispatch_step(self, step: WorkflowStep, plan: WorkflowPlan) -> None:
        """Send step to target agent via AgentBus and wait for response."""
        corr_id = str(uuid.uuid4())
        response_holder: Dict[str, Any] = {}
        event = threading.Event()

        def _on_response(msg: AgentMessage) -> None:
            if msg.correlation_id == corr_id and msg.message_type in ("response", "error"):
                response_holder["msg"] = msg
                event.set()

        self._bus.subscribe(self.AGENT_ID, _on_response)
        try:
            self._bus.send(
                sender=self.AGENT_ID,
                recipient=step.agent_id,
                message_type="request",
                payload={"action": step.action, "inputs": step.inputs, "step_id": step.step_id},
                correlation_id=corr_id,
            )
            # Wait up to 30s for response
            if event.wait(timeout=30):
                response = response_holder["msg"]
                if response.message_type == "error":
                    step.status = "failed"
                    step.error = response.payload.get("error", "unknown")
                else:
                    step.status = "done"
                    step.result = response.payload.get("result")
            else:
                step.status = "failed"
                step.error = "timeout"
        finally:
            self._bus.unsubscribe(self.AGENT_ID, _on_response)

    @staticmethod
    def _deps_satisfied(step: WorkflowStep, plan: WorkflowPlan) -> bool:
        step_map = {s.step_id: s for s in plan.steps}
        return all(
            step_map.get(dep_id, None) is not None
            and step_map[dep_id].status == "done"
            for dep_id in step.dependencies
        )

    # ------------------------------------------------------------------
    # Bus handler
    # ------------------------------------------------------------------

    def _handle_message(self, msg: AgentMessage) -> None:
        logger.debug("CoordinatorAgent: received %s from %s", msg.message_type, msg.sender)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _log(self, action: str, data: Dict[str, Any]) -> None:
        if self._audit is not None:
            try:
                self._audit.append({"component": "CoordinatorAgent", "action": action, **data})
            except Exception:
                logger.exception("CoordinatorAgent: audit write failed")
        try:
            self._trace.log_event(f"coordinator.{action}", data)
        except Exception:
            pass

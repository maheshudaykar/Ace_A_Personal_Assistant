"""ReflectionAgent: Post-workflow analysis and heuristic improvement."""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ace.runtime.agent_bus import AgentBus, AgentMessage
from ace.runtime.golden_trace import GoldenTrace
from ace.runtime.experiment_engine import ExperimentEngine
from ace.ace_cognitive.coordinator_agent import WorkflowPlan

__all__ = ["ReflectionResult", "ReflectionAgent"]

logger = logging.getLogger(__name__)


@dataclass
class ReflectionResult:
    """Outcome of reflecting on one workflow execution."""

    reflection_id: str
    workflow_id: str
    failures_detected: List[str]
    improvements_proposed: List[str]
    pattern_adjustments: Dict[str, Any]
    heuristic_updates: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)


class ReflectionAgent:
    """
    Reflects on completed workflows and proposes improvements.

    Reflection loop:
        action → result → evaluation → reflection → improvement

    Memory note: ReflectionResults should be persisted via EpisodicMemory
    (ace.ace_memory.episodic_memory) so that improvements accumulate across
    sessions.
    """

    AGENT_ID = "reflector"

    def __init__(
        self,
        bus: AgentBus,
        audit_trail: Any = None,
        experiment_engine: ExperimentEngine | None = None,
    ) -> None:
        self._bus = bus
        self._audit = audit_trail
        self._experiment_engine = experiment_engine
        self._trace = GoldenTrace.get_instance()
        self._reflections: Dict[str, ReflectionResult] = {}
        self._bus.subscribe(self.AGENT_ID, self._handle_message)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reflect(self, plan: WorkflowPlan) -> ReflectionResult:
        """Analyse a completed WorkflowPlan and produce a ReflectionResult."""
        failures_detected: List[str] = []
        improvements_proposed: List[str] = []
        pattern_adjustments: Dict[str, Any] = {}
        heuristic_updates: Dict[str, Any] = {}

        failed_steps = [s for s in plan.steps if s.status == "failed"]
        done_steps = [s for s in plan.steps if s.status == "done"]

        for step in failed_steps:
            failures_detected.append(
                f"Step '{step.step_id}' ({step.action} on {step.agent_id}) failed: {step.error}"
            )
            improvements_proposed.append(
                f"Add fallback handler for action '{step.action}' on agent '{step.agent_id}'"
            )
            pattern_adjustments[step.step_id] = {
                "action": step.action,
                "agent_id": step.agent_id,
                "suggested_retry_policy": "exponential_backoff",
            }

        if len(done_steps) > 0 and len(failed_steps) == 0:
            heuristic_updates["success_rate"] = 1.0
            improvements_proposed.append("Workflow completed without failures; consider reducing retry count.")
        elif failed_steps:
            failure_rate = len(failed_steps) / max(len(plan.steps), 1)
            heuristic_updates["failure_rate"] = failure_rate
            if failure_rate > 0.5:
                improvements_proposed.append(
                    "More than 50% of steps failed; review agent availability and input schemas."
                )

        result = ReflectionResult(
            reflection_id=str(uuid.uuid4()),
            workflow_id=plan.plan_id,
            failures_detected=failures_detected,
            improvements_proposed=improvements_proposed,
            pattern_adjustments=pattern_adjustments,
            heuristic_updates=heuristic_updates,
        )
        self._reflections[result.reflection_id] = result
        if failed_steps and self._experiment_engine is not None:
            experiment = self._experiment_engine.create_experiment(
                statement="Retry policy update reduces workflow failure rate",
                baseline={"retry_policy": "fixed", "backoff": "none"},
                experimental={"retry_policy": "exponential", "backoff": "jitterless"},
                metric="throughput",
                trials=3,
            )
            try:
                exp_result = self._experiment_engine.run_experiment(experiment)
                heuristic_updates["experiment_outcome"] = exp_result.insight
            except Exception as exc:
                heuristic_updates["experiment_error"] = str(exc)

        self._log(
            "reflection_complete",
            {
                "reflection_id": result.reflection_id,
                "workflow_id": plan.plan_id,
                "failures": len(failures_detected),
            },
        )
        return result

    def get_all_reflections(self) -> List[ReflectionResult]:
        return list(self._reflections.values())

    # ------------------------------------------------------------------
    # Bus handler
    # ------------------------------------------------------------------

    def _handle_message(self, msg: AgentMessage) -> None:
        if msg.message_type != "request":
            return
        self._bus.send(
            sender=self.AGENT_ID,
            recipient=msg.sender,
            message_type="response",
            payload={"result": "reflection handled"},
            correlation_id=msg.correlation_id,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _log(self, action: str, data: Dict[str, Any]) -> None:
        if self._audit is not None:
            try:
                self._audit.append({"component": "ReflectionAgent", "action": action, **data})
            except Exception:
                logger.exception("ReflectionAgent: audit write failed")
        try:
            self._trace.log_event(f"reflector.{action}", data)
        except Exception:
            pass

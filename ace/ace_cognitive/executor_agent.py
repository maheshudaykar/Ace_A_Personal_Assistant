"""ExecutorAgent: Safe simulated execution of approved predictions."""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ace.runtime.agent_bus import AgentBus, AgentMessage
from ace.runtime.golden_trace import GoldenTrace

__all__ = ["ExecutionResult", "ExecutorAgent"]

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 30
_MEMORY_LIMIT_MB = 512


@dataclass
class ExecutionResult:
    """Outcome of one simulated execution."""

    execution_id: str
    prediction_id: str
    status: str  # success / failed / timeout / rejected
    output: Any
    side_effects: List[str]
    duration_ms: float
    sandbox_stats: Dict[str, Any]
    requires_approval: bool
    timestamp: float = field(default_factory=time.time)


class ExecutorAgent:
    """
    Sandboxed executor for approved predictions.

    Constraints (simulated):
    - 30-second timeout (tracked; not enforced via OS)
    - 512 MB memory limit (tracked in sandbox_stats)
    - No external network access
    - Side effects are accumulated and only applied after explicit user approval

    Memory note: Execution results should be persisted via EpisodicMemory
    (ace.ace_memory.episodic_memory) for audit and replay.
    """

    AGENT_ID = "executor"

    def __init__(self, bus: AgentBus, audit_trail: Any = None) -> None:
        self._bus = bus
        self._audit = audit_trail
        self._trace = GoldenTrace.get_instance()
        self._results: Dict[str, ExecutionResult] = {}
        self._pending_side_effects: Dict[str, List[str]] = {}
        self._bus.subscribe(self.AGENT_ID, self._handle_message)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(
        self,
        prediction_id: str,
        actions: List[str],
        validation_decision: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ExecutionResult:
        """
        Simulate executing *actions*.

        Returns immediately with a result.  Side effects are stored pending
        approval; call ``apply_side_effects`` once the user approves.
        """
        exec_id = str(uuid.uuid4())
        t_start = time.time()

        if validation_decision == "rejected":
            result = ExecutionResult(
                execution_id=exec_id,
                prediction_id=prediction_id,
                status="rejected",
                output=None,
                side_effects=[],
                duration_ms=0.0,
                sandbox_stats={},
                requires_approval=False,
            )
            self._results[exec_id] = result
            self._log("execution_rejected", {"execution_id": exec_id, "prediction_id": prediction_id})
            return result

        # Simulate execution
        side_effects: List[str] = []
        output_parts: List[str] = []
        try:
            for action in actions:
                sim_output, sim_side_effects = self._simulate_action(action, context or {})
                output_parts.append(sim_output)
                side_effects.extend(sim_side_effects)
            status = "success"
            output = "; ".join(output_parts)
        except Exception as exc:
            status = "failed"
            output = str(exc)
            logger.exception("ExecutorAgent: simulation error for %s", prediction_id)

        duration_ms = (time.time() - t_start) * 1000
        requires_approval = validation_decision == "warning" or bool(side_effects)

        sandbox_stats = {
            "timeout_seconds": _TIMEOUT_SECONDS,
            "memory_limit_mb": _MEMORY_LIMIT_MB,
            "simulated": True,
            "duration_ms": duration_ms,
        }

        result = ExecutionResult(
            execution_id=exec_id,
            prediction_id=prediction_id,
            status=status,
            output=output,
            side_effects=side_effects,
            duration_ms=duration_ms,
            sandbox_stats=sandbox_stats,
            requires_approval=requires_approval,
        )
        self._results[exec_id] = result
        if side_effects:
            self._pending_side_effects[exec_id] = list(side_effects)

        self._log(
            "execution_complete",
            {
                "execution_id": exec_id,
                "status": status,
                "requires_approval": requires_approval,
            },
        )
        return result

    def apply_side_effects(self, execution_id: str) -> List[str]:
        """Apply (clear) pending side effects for an approved execution."""
        effects = self._pending_side_effects.pop(execution_id, [])
        self._log("side_effects_applied", {"execution_id": execution_id, "count": len(effects)})
        return effects

    def get_result(self, execution_id: str) -> Optional[ExecutionResult]:
        return self._results.get(execution_id)

    # ------------------------------------------------------------------
    # Simulation internals
    # ------------------------------------------------------------------

    @staticmethod
    def _simulate_action(action: str, context: Dict[str, Any]) -> Tuple[str, List[str]]:
        """
        Safely simulate a single action string.

        Returns (output_string, list_of_side_effects).
        No real filesystem or network operations are performed.
        """
        side_effects: List[str] = []
        action_lower = action.lower()

        if "write" in action_lower or "create" in action_lower or "save" in action_lower:
            side_effects.append(f"filesystem: simulated write from '{action}'")
            return f"[sim] would write: {action}", side_effects

        if "delete" in action_lower or "remove" in action_lower:
            side_effects.append(f"filesystem: simulated delete from '{action}'")
            return f"[sim] would delete: {action}", side_effects

        if "run" in action_lower or "exec" in action_lower or "execute" in action_lower:
            side_effects.append(f"process: simulated exec from '{action}'")
            return f"[sim] would execute: {action}", side_effects

        return f"[sim] action: {action}", side_effects

    # ------------------------------------------------------------------
    # Bus handler
    # ------------------------------------------------------------------

    def _handle_message(self, msg: AgentMessage) -> None:
        if msg.message_type != "request":
            return
        if msg.payload.get("action") != "execute":
            return
        pred_id = msg.payload.get("prediction_id", str(uuid.uuid4()))
        actions = msg.payload.get("predicted_actions", [])
        decision = msg.payload.get("validation_decision", "approved")
        result = self.execute(pred_id, actions, decision)
        self._bus.send(
            sender=self.AGENT_ID,
            recipient=msg.sender,
            message_type="response",
            payload={"result": {"execution_id": result.execution_id, "status": result.status}},
            correlation_id=msg.correlation_id,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _log(self, action: str, data: Dict[str, Any]) -> None:
        if self._audit is not None:
            try:
                self._audit.append({"component": "ExecutorAgent", "action": action, **data})
            except Exception:
                logger.exception("ExecutorAgent: audit write failed")
        try:
            self._trace.log_event(f"executor.{action}", data)
        except Exception:
            pass

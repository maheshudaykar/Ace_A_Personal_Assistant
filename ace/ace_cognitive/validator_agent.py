"""ValidatorAgent: Risk-based validation gate for predicted actions."""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ace.runtime.agent_bus import AgentBus, AgentMessage
from ace.runtime.golden_trace import GoldenTrace

__all__ = ["ValidationResult", "ValidatorAgent"]

logger = logging.getLogger(__name__)

# Risk decision thresholds
_REJECT_THRESHOLD = 0.8
_WARN_THRESHOLD = 0.5

# High-risk action keywords (simple static policy)
_HIGH_RISK_KEYWORDS = {
    "delete", "drop", "rm", "format", "overwrite", "shutdown", "kill",
    "exec", "eval", "sudo", "chmod", "chown",
}


@dataclass
class ValidationResult:
    """Outcome of validating a predicted action set."""

    prediction_id: str
    risk_score: float  # 0.0 – 1.0
    decision: str  # approved / rejected / warning
    reason: str
    policy_violations: List[str]
    timestamp: float = field(default_factory=time.time)


class ValidatorAgent:
    """
    Validates predictions before forwarding them to ExecutorAgent.

    Decision thresholds:
    - risk > 0.8 → reject
    - risk > 0.5 → warning (requires human approval)
    - else       → approved
    """

    AGENT_ID = "validator"

    def __init__(self, bus: AgentBus, audit_trail: Any = None) -> None:
        self._bus = bus
        self._audit = audit_trail
        self._trace = GoldenTrace.get_instance()
        self._results: Dict[str, ValidationResult] = {}
        self._bus.subscribe(self.AGENT_ID, self._handle_message)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(self, prediction_id: str, predicted_actions: List[str]) -> ValidationResult:
        """Compute risk and decide whether to allow the prediction to execute."""
        risk, violations = self._compute_risk(predicted_actions)

        if risk > _REJECT_THRESHOLD:
            decision = "rejected"
            reason = f"Risk score {risk:.2f} exceeds rejection threshold {_REJECT_THRESHOLD}"
        elif risk > _WARN_THRESHOLD:
            decision = "warning"
            reason = f"Risk score {risk:.2f} exceeds warning threshold {_WARN_THRESHOLD}"
        else:
            decision = "approved"
            reason = f"Risk score {risk:.2f} is within safe bounds"

        result = ValidationResult(
            prediction_id=prediction_id,
            risk_score=risk,
            decision=decision,
            reason=reason,
            policy_violations=violations,
        )
        self._results[prediction_id] = result
        self._log(
            "validation_complete",
            {
                "prediction_id": prediction_id,
                "decision": decision,
                "risk_score": risk,
            },
        )
        return result

    def get_result(self, prediction_id: str) -> Optional[ValidationResult]:
        return self._results.get(prediction_id)

    # ------------------------------------------------------------------
    # Risk computation
    # ------------------------------------------------------------------

    def _compute_risk(self, actions: List[str]) -> Tuple[float, List[str]]:
        violations: List[str] = []
        risk = 0.0

        for action in actions:
            action_lower = action.lower()
            for keyword in _HIGH_RISK_KEYWORDS:
                if keyword in action_lower:
                    risk += 0.3
                    violations.append(f"high-risk keyword '{keyword}' in action '{action}'")

        # Normalise to [0, 1]
        risk = min(1.0, risk)
        return risk, violations

    # ------------------------------------------------------------------
    # Bus handler
    # ------------------------------------------------------------------

    def _handle_message(self, msg: AgentMessage) -> None:
        if msg.message_type != "request":
            return
        if msg.payload.get("action") != "validate":
            return
        pred_id = msg.payload.get("prediction_id", str(uuid.uuid4()))
        actions = msg.payload.get("predicted_actions", [])
        result = self.validate(pred_id, actions)
        self._bus.send(
            sender=self.AGENT_ID,
            recipient=msg.sender,
            message_type="response",
            payload={"result": {"decision": result.decision, "risk_score": result.risk_score}},
            correlation_id=msg.correlation_id,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _log(self, action: str, data: Dict[str, Any]) -> None:
        if self._audit is not None:
            try:
                self._audit.append({"component": "ValidatorAgent", "action": action, **data})
            except Exception:
                logger.exception("ValidatorAgent: audit write failed")
        try:
            self._trace.log_event(f"validator.{action}", data)
        except Exception:
            pass

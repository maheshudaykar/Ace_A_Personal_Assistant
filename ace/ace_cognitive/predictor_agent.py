"""PredictorAgent: Observes action sequences and generates proactive predictions."""
from __future__ import annotations

import hashlib
import logging
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ace.runtime.agent_bus import AgentBus, AgentMessage
from ace.runtime.golden_trace import GoldenTrace

__all__ = ["ActionSequence", "PredictionPattern", "Prediction", "PredictorAgent"]

logger = logging.getLogger(__name__)

_CONFIDENCE_THRESHOLD = 0.6
_SEED = 42


@dataclass
class ActionSequence:
    """A recorded sequence of user/system actions."""

    sequence_id: str
    actions: List[str]
    timestamp: float
    project_context: Dict[str, Any]
    outcome: str  # success / failure
    duration_ms: float


@dataclass
class PredictionPattern:
    """A learned pattern derived from multiple action sequences."""

    pattern_id: str
    sequence_prefix: List[str]
    predicted_next_actions: List[str]
    confidence_score: float  # 0.0 – 1.0
    frequency: int
    last_observed: float
    feedback_positive: int = 0
    feedback_negative: int = 0


@dataclass
class Prediction:
    """A concrete prediction generated from a pattern."""

    prediction_id: str
    predicted_actions: List[str]
    confidence_score: float
    pattern_id: str
    timestamp: float = field(default_factory=time.time)
    status: str = "pending"  # pending / approved / rejected / executed


class PredictorAgent:
    """
    Observes action sequences, clusters them deterministically, and generates
    predictions for upcoming actions.

    Predictions below ``_CONFIDENCE_THRESHOLD`` are silently discarded.

    Memory note: Patterns and predictions should be persisted through
    EpisodicMemory (ace.ace_memory.episodic_memory) for cross-session retention.
    """

    AGENT_ID = "predictor"

    def __init__(
        self,
        bus: AgentBus,
        audit_trail: Any = None,
        seed: int = _SEED,
    ) -> None:
        self._random = random.Random(seed)
        self._bus = bus
        self._audit = audit_trail
        self._trace = GoldenTrace.get_instance()
        self._sequences: List[ActionSequence] = []
        self._patterns: Dict[str, PredictionPattern] = {}
        self._predictions: Dict[str, Prediction] = {}
        self._bus.subscribe(self.AGENT_ID, self._handle_message)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def observe(self, sequence: ActionSequence) -> None:
        """Record an action sequence and update internal patterns."""
        self._sequences.append(sequence)
        self._update_patterns(sequence)
        self._log("sequence_observed", {"sequence_id": sequence.sequence_id})

    def predict(self, recent_actions: List[str]) -> List[Prediction]:
        """
        Generate predictions given a list of recently observed actions.

        Returns only predictions at or above the confidence threshold.
        """
        results: List[Prediction] = []
        for pattern in self._patterns.values():
            prefix = pattern.sequence_prefix
            if len(recent_actions) < len(prefix):
                continue
            window = recent_actions[-len(prefix):]
            if window == prefix and pattern.confidence_score >= _CONFIDENCE_THRESHOLD:
                pred = Prediction(
                    prediction_id=str(uuid.uuid4()),
                    predicted_actions=list(pattern.predicted_next_actions),
                    confidence_score=pattern.confidence_score,
                    pattern_id=pattern.pattern_id,
                )
                self._predictions[pred.prediction_id] = pred
                results.append(pred)
                self._log("prediction_generated", {"prediction_id": pred.prediction_id})
        return sorted(results, key=lambda p: p.confidence_score, reverse=True)

    def apply_feedback(self, prediction_id: str, positive: bool) -> None:
        """Update pattern confidence based on user feedback.

        Uses a weighted blend (60 % frequency-based, 40 % feedback-based) so
        that a small number of negative feedback events does not catastrophically
        zero out a pattern that has been observed many times.
        """
        pred = self._predictions.get(prediction_id)
        if pred is None:
            return
        pattern = self._patterns.get(pred.pattern_id)
        if pattern is None:
            return
        if positive:
            pattern.feedback_positive += 1
        else:
            pattern.feedback_negative += 1
        total = pattern.feedback_positive + pattern.feedback_negative
        if total > 0:
            freq_confidence = min(1.0, pattern.frequency / (pattern.frequency + 1))
            feedback_confidence = pattern.feedback_positive / total
            # Weighted blend: frequency signal carries 60 %, feedback 40 %
            pattern.confidence_score = round(
                0.6 * freq_confidence + 0.4 * feedback_confidence, 6
            )
        self._log(
            "feedback_applied",
            {"prediction_id": prediction_id, "positive": positive, "new_confidence": pattern.confidence_score},
        )

    def get_patterns(self) -> List[PredictionPattern]:
        return list(self._patterns.values())

    def get_predictions(self) -> List[Prediction]:
        return list(self._predictions.values())

    # ------------------------------------------------------------------
    # Pattern update (deterministic)
    # ------------------------------------------------------------------

    def _update_patterns(self, sequence: ActionSequence) -> None:
        actions = sequence.actions
        if len(actions) < 2:
            return

        # Generate n-gram prefixes deterministically using hashlib-keyed sort
        for prefix_len in range(1, min(len(actions), 4)):
            prefix = actions[:prefix_len]
            next_actions = actions[prefix_len:]
            if not next_actions:
                continue

            # Deterministic pattern_id from prefix content
            key = hashlib.sha256("|".join(prefix).encode()).hexdigest()[:16]
            pattern_id = f"pat-{key}"

            if pattern_id in self._patterns:
                pat = self._patterns[pattern_id]
                pat.frequency += 1
                pat.last_observed = sequence.timestamp
                # Update predicted actions: merge and re-sort deterministically
                existing = set(pat.predicted_next_actions)
                for a in next_actions:
                    existing.add(a)
                pat.predicted_next_actions = sorted(
                    existing, key=lambda x: hashlib.sha256(x.encode()).hexdigest()
                )
                # Confidence grows with frequency (capped at 1.0)
                pat.confidence_score = min(1.0, pat.frequency / (pat.frequency + 1))
            else:
                self._patterns[pattern_id] = PredictionPattern(
                    pattern_id=pattern_id,
                    sequence_prefix=prefix,
                    predicted_next_actions=sorted(
                        next_actions, key=lambda x: hashlib.sha256(x.encode()).hexdigest()
                    ),
                    confidence_score=0.5,
                    frequency=1,
                    last_observed=sequence.timestamp,
                )

    # ------------------------------------------------------------------
    # Bus handler
    # ------------------------------------------------------------------

    def _handle_message(self, msg: AgentMessage) -> None:
        if msg.message_type == "request" and msg.payload.get("action") == "predict":
            recent = msg.payload.get("recent_actions", [])
            preds = self.predict(recent)
            self._bus.send(
                sender=self.AGENT_ID,
                recipient=msg.sender,
                message_type="response",
                payload={"result": [p.prediction_id for p in preds]},
                correlation_id=msg.correlation_id,
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _log(self, action: str, data: Dict[str, Any]) -> None:
        if self._audit is not None:
            try:
                self._audit.append({"component": "PredictorAgent", "action": action, **data})
            except Exception:
                logger.exception("PredictorAgent: audit write failed")
        try:
            self._trace.log_event(f"predictor.{action}", data)
        except Exception:
            pass

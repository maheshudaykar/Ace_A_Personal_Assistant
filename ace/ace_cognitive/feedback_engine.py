"""FeedbackEngine: Collect user feedback and propagate model updates."""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ace.runtime.golden_trace import GoldenTrace

__all__ = ["FeedbackEntry", "ModelUpdate", "FeedbackEngine"]

logger = logging.getLogger(__name__)


@dataclass
class FeedbackEntry:
    """Single unit of human or system feedback."""

    feedback_id: str
    target_id: str   # prediction_id or proposal_id
    feedback_type: str   # prediction_accepted / prediction_rejected / refactor_useful / refactor_harmful
    notes: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class ModelUpdate:
    """Aggregated adjustments derived from a batch of feedback entries."""

    update_id: str
    feedback_ids: List[str]
    model_type: str   # prediction or analysis
    adjustments: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)


class FeedbackEngine:
    """
    Collects feedback entries and periodically computes model updates.

    Memory note: Feedback and updates should be persisted via EpisodicMemory
    (ace.ace_memory.episodic_memory) to drive cross-session learning.
    """

    def __init__(self, audit_trail=None) -> None:
        self._audit = audit_trail
        self._trace = GoldenTrace.get_instance()
        self._entries: Dict[str, FeedbackEntry] = {}
        self._updates: Dict[str, ModelUpdate] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(
        self,
        target_id: str,
        feedback_type: str,
        notes: str = "",
    ) -> FeedbackEntry:
        """Record a feedback entry and return it."""
        entry = FeedbackEntry(
            feedback_id=str(uuid.uuid4()),
            target_id=target_id,
            feedback_type=feedback_type,
            notes=notes,
        )
        self._entries[entry.feedback_id] = entry
        self._log(
            "feedback_recorded",
            {"feedback_id": entry.feedback_id, "target_id": target_id, "type": feedback_type},
        )
        return entry

    def compute_update(
        self,
        model_type: str,
        feedback_ids: Optional[List[str]] = None,
    ) -> ModelUpdate:
        """
        Compute a ModelUpdate from the specified (or all) feedback entries.

        *model_type* must be 'prediction' or 'analysis'.
        """
        if feedback_ids is None:
            relevant = [
                e
                for e in self._entries.values()
                if (model_type == "prediction" and e.feedback_type.startswith("prediction"))
                or (model_type == "analysis" and e.feedback_type.startswith("refactor"))
            ]
            feedback_ids = [e.feedback_id for e in relevant]
        else:
            relevant = [self._entries[fid] for fid in feedback_ids if fid in self._entries]

        positive = sum(
            1
            for e in relevant
            if e.feedback_type in ("prediction_accepted", "refactor_useful")
        )
        negative = len(relevant) - positive
        acceptance_rate = positive / max(len(relevant), 1)

        adjustments: Dict[str, Any] = {
            "acceptance_rate": acceptance_rate,
            "positive_count": positive,
            "negative_count": negative,
            "total_feedback": len(relevant),
        }

        if model_type == "prediction" and acceptance_rate < 0.5:
            adjustments["confidence_delta"] = -0.05
            adjustments["suggestion"] = "Lower prediction confidence threshold"
        elif model_type == "analysis" and acceptance_rate > 0.8:
            adjustments["priority_boost"] = 0.1
            adjustments["suggestion"] = "Increase priority weight for high-acceptance proposals"

        update = ModelUpdate(
            update_id=str(uuid.uuid4()),
            feedback_ids=feedback_ids,
            model_type=model_type,
            adjustments=adjustments,
        )
        self._updates[update.update_id] = update
        self._log(
            "model_updated",
            {
                "update_id": update.update_id,
                "model_type": model_type,
                "feedback_count": len(feedback_ids),
            },
        )
        return update

    def get_entries(self) -> List[FeedbackEntry]:
        return list(self._entries.values())

    def get_updates(self) -> List[ModelUpdate]:
        return list(self._updates.values())

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _log(self, action: str, data: Dict[str, Any]) -> None:
        if self._audit is not None:
            try:
                self._audit.append({"component": "FeedbackEngine", "action": action, **data})
            except Exception:
                logger.exception("FeedbackEngine: audit write failed")
        try:
            self._trace.log_event(f"feedback.{action}", data)
        except Exception:
            pass

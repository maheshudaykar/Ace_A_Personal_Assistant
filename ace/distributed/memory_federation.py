"""MemoryFederation: deterministic memory convergence across cluster nodes."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ace.distributed.memory_sync import DistributedMemorySync

logger = logging.getLogger(__name__)

__all__ = ["FederatedRecord", "ConflictResolution", "MemoryFederation"]


@dataclass
class FederatedRecord:
    record_id: str
    memory_type: str  # semantic, episodic, knowledge_graph, project_memory
    payload: Dict[str, Any]
    timestamp: float
    confidence: float = 0.5
    embedding: Optional[List[float]] = None
    source_node: str = ""


@dataclass
class ConflictResolution:
    record_id: str
    winner_node: str
    resolution_reason: str
    score: float
    timestamp: float = field(default_factory=time.time)


class MemoryFederation:
    """Federates memory by deterministic conflict resolution and sync hooks."""

    def __init__(
        self,
        memory_sync: DistributedMemorySync,
        max_records_per_type: int = 50_000,
        similarity_threshold: float = 0.95,
    ) -> None:
        self.memory_sync = memory_sync
        self.max_records_per_type = max_records_per_type
        self.similarity_threshold = similarity_threshold
        self._records: Dict[str, Dict[str, FederatedRecord]] = {
            "semantic": {},
            "episodic": {},
            "knowledge_graph": {},
            "project_memory": {},
        }
        self._lock = threading.RLock()
        self._resolutions: List[ConflictResolution] = []

    def upsert_record(self, record: FederatedRecord) -> FederatedRecord:
        with self._lock:
            if record.memory_type not in self._records:
                raise ValueError(f"Unsupported memory_type: {record.memory_type}")
            bucket = self._records[record.memory_type]
            if len(bucket) >= self.max_records_per_type and record.record_id not in bucket:
                logger.warning(
                    "Federation budget exceeded for %s (%d records); rejecting record %s",
                    record.memory_type,
                    len(bucket),
                    record.record_id,
                )
                raise RuntimeError("federation memory budget exceeded")

            existing = bucket.get(record.record_id)
            if existing is None:
                bucket[record.record_id] = record
                return record

            winner, reason, score = self._resolve_conflict(existing, record)
            bucket[record.record_id] = winner
            self._resolutions.append(
                ConflictResolution(
                    record_id=record.record_id,
                    winner_node=winner.source_node,
                    resolution_reason=reason,
                    score=score,
                )
            )
            return winner

    def synchronize_to_cluster(self, memory_type: str) -> int:
        """Submit current records to DistributedMemorySync through leader proposal flow."""
        with self._lock:
            records = self._records.get(memory_type, {}).values()

        accepted = 0
        for record in sorted(records, key=lambda r: (r.timestamp, r.record_id, r.source_node)):
            response = self.memory_sync.submit_write_proposal(
                entry_data={
                    "record_id": record.record_id,
                    "memory_type": record.memory_type,
                    "payload": record.payload,
                    "confidence": record.confidence,
                    "timestamp": record.timestamp,
                },
                task_id=f"federation:{memory_type}",
            )
            if response.accepted:
                accepted += 1
        return accepted

    def list_records(self, memory_type: str) -> List[FederatedRecord]:
        with self._lock:
            records = self._records.get(memory_type, {}).values()
        return sorted(records, key=lambda r: (r.timestamp, r.record_id, r.source_node))

    def get_conflict_history(self) -> List[ConflictResolution]:
        with self._lock:
            return list(self._resolutions)

    def _resolve_conflict(self, left: FederatedRecord, right: FederatedRecord) -> tuple[FederatedRecord, str, float]:
        if not math.isclose(left.timestamp, right.timestamp, abs_tol=1e-9):
            winner = left if left.timestamp > right.timestamp else right
            score = abs(left.timestamp - right.timestamp)
            return winner, "timestamp_ordering", score

        if not math.isclose(left.confidence, right.confidence, abs_tol=1e-9):
            winner = left if left.confidence > right.confidence else right
            score = abs(left.confidence - right.confidence)
            return winner, "confidence_scoring", score

        similarity = self._vector_similarity(left.embedding, right.embedding)
        if similarity < self.similarity_threshold:
            winner = left if self._stable_rank(left) >= self._stable_rank(right) else right
            return winner, "vector_similarity_voting", similarity

        winner = left if self._stable_rank(left) >= self._stable_rank(right) else right
        return winner, "deterministic_tie_break", similarity

    @staticmethod
    def _vector_similarity(a: Optional[List[float]], b: Optional[List[float]]) -> float:
        if not a or not b:
            return 0.0
        if len(a) != len(b):
            logger.warning(
                "Embedding dimension mismatch: %d vs %d; treating as dissimilar",
                len(a),
                len(b),
            )
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        a_norm = math.sqrt(sum(x * x for x in a))
        b_norm = math.sqrt(sum(y * y for y in b))
        if math.isclose(a_norm, 0.0, abs_tol=1e-12) or math.isclose(b_norm, 0.0, abs_tol=1e-12):
            return 0.0
        return dot / (a_norm * b_norm)

    @staticmethod
    def _stable_rank(record: FederatedRecord) -> int:
        payload: Dict[str, Any] = {
            "record_id": record.record_id,
            "payload": record.payload,
            "source_node": record.source_node,
            "timestamp": record.timestamp,
            "confidence": record.confidence,
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
        return int(digest[:12], 16)

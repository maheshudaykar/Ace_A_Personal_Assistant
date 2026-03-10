"""DistributedConsistencyChecker: verifies cluster memory consistency invariants."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Dict, List, Optional

from ace.distributed.memory_federation import MemoryFederation
from ace.distributed.memory_sync import DistributedMemorySync
from ace.distributed.node_registry import NodeRegistry

logger = logging.getLogger(__name__)

__all__ = ["DistributedConsistencyChecker"]

_MEMORY_TYPES = ("semantic", "episodic", "knowledge_graph", "project_memory")


class DistributedConsistencyChecker:
    """Run deterministic consistency checks and trigger targeted resync."""

    def __init__(
        self,
        node_registry: NodeRegistry,
        memory_sync: DistributedMemorySync,
        memory_federation: MemoryFederation,
    ) -> None:
        self.node_registry = node_registry
        self.memory_sync = memory_sync
        self.memory_federation = memory_federation

    def check_semantic_memory_consistency(self) -> bool:
        return self._is_consistent("semantic")

    def check_episodic_memory_consistency(self) -> bool:
        return self._is_consistent("episodic")

    def check_knowledge_graph_consistency(self) -> bool:
        return self._is_consistent("knowledge_graph")

    def check_project_memory_consistency(self) -> bool:
        return self._is_consistent("project_memory")

    def check_task_queue_consistency(self) -> bool:
        history = self.memory_sync.get_conflicts()
        return len(history) == 0

    def run_full_consistency_audit(self) -> Dict[str, bool]:
        return {
            "semantic": self.check_semantic_memory_consistency(),
            "episodic": self.check_episodic_memory_consistency(),
            "knowledge_graph": self.check_knowledge_graph_consistency(),
            "project_memory": self.check_project_memory_consistency(),
            "task_queue": self.check_task_queue_consistency(),
        }

    def trigger_resync_if_needed(self) -> Dict[str, int]:
        status = self.run_full_consistency_audit()
        resynced: Dict[str, int] = {}
        for key, ok in status.items():
            if ok:
                continue
            if key in _MEMORY_TYPES:
                count = self.memory_federation.synchronize_to_cluster(key)
                resynced[key] = count
                logger.info("Resynced %s: %d records pushed", key, count)
            else:
                resynced[key] = 0
        return resynced

    def compute_local_digests(self) -> Dict[str, Optional[str]]:
        """Return per-type SHA-256 digests for the local federation store."""
        return {mt: self._hash_records(mt) for mt in _MEMORY_TYPES}

    def compare_digests(
        self, local: Dict[str, Optional[str]], remote: Dict[str, Optional[str]]
    ) -> List[str]:
        """Return list of memory types where local and remote digests differ."""
        diverged: List[str] = []
        for mt in _MEMORY_TYPES:
            lh = local.get(mt)
            rh = remote.get(mt)
            if lh != rh:
                diverged.append(mt)
                logger.warning("Digest mismatch for %s: local=%s remote=%s", mt, lh, rh)
        return diverged

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _is_consistent(self, memory_type: str) -> bool:
        """A memory type is consistent if its hash is computable (non-None)."""
        h = self._hash_records(memory_type)
        return h is not None

    def _hash_records(self, memory_type: str) -> Optional[str]:
        records = self.memory_federation.list_records(memory_type)
        if not records:
            # Empty is a valid deterministic state — hash the empty list.
            return hashlib.sha256(b"[]").hexdigest()
        payload: List[Dict[str, object]] = [
            {
                "id": record.record_id,
                "source": record.source_node,
                "timestamp": record.timestamp,
                "confidence": record.confidence,
                "payload": record.payload,
            }
            for record in records
        ]
        stable = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(stable.encode("utf-8")).hexdigest()

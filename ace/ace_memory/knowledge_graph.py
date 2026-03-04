"""KnowledgeGraph: In-memory semantic relationship store for system entities."""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

__all__ = ["KGNode", "KGEdge", "KnowledgeGraph"]

logger = logging.getLogger(__name__)

# Supported node types
NODE_TYPES = {"concept", "file", "function", "user_action", "prediction_pattern", "analysis_artifact"}
# Supported edge types
EDGE_TYPES = {"depends_on", "calls", "predicts", "related_to", "modifies"}


@dataclass
class KGNode:
    """A node in the knowledge graph."""

    node_id: str
    node_type: str  # concept, file, function, user_action, prediction_pattern, analysis_artifact
    properties: Dict[str, Any]
    created_at: float = field(default_factory=time.time)


@dataclass
class KGEdge:
    """A directed edge in the knowledge graph."""

    edge_id: str
    source_id: str
    target_id: str
    edge_type: str  # depends_on, calls, predicts, related_to, modifies
    properties: Dict[str, Any]
    created_at: float = field(default_factory=time.time)


class KnowledgeGraph:
    """
    Thread-safe in-memory knowledge graph.

    Persistence note: For durable storage, agents should persist KGNode/KGEdge
    data through EpisodicMemory (ace.ace_memory.episodic_memory) rather than
    writing to this in-memory store directly.
    """

    def __init__(self, audit_trail=None) -> None:
        self._audit = audit_trail
        self._lock = threading.RLock()
        self._nodes: Dict[str, KGNode] = {}
        self._edges: Dict[str, KGEdge] = {}
        # adjacency index: source_id → list of edge_ids
        self._out_edges: Dict[str, List[str]] = {}
        # reverse adjacency: target_id → list of edge_ids
        self._in_edges: Dict[str, List[str]] = {}

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------

    def add_node(self, node: KGNode) -> KGNode:
        """Add or overwrite a node. Logs to AuditTrail if configured."""
        with self._lock:
            self._nodes[node.node_id] = node
            self._out_edges.setdefault(node.node_id, [])
            self._in_edges.setdefault(node.node_id, [])
        self._audit_write("add_node", {"node_id": node.node_id, "node_type": node.node_type})
        logger.debug("KnowledgeGraph: node added %s (%s)", node.node_id, node.node_type)
        return node

    def get_node(self, node_id: str) -> Optional[KGNode]:
        with self._lock:
            return self._nodes.get(node_id)

    def remove_node(self, node_id: str) -> bool:
        with self._lock:
            if node_id not in self._nodes:
                return False
            del self._nodes[node_id]
            for eid in list(self._out_edges.pop(node_id, [])):
                self._edges.pop(eid, None)
            for eid in list(self._in_edges.pop(node_id, [])):
                self._edges.pop(eid, None)
        self._audit_write("remove_node", {"node_id": node_id})
        return True

    # ------------------------------------------------------------------
    # Edges
    # ------------------------------------------------------------------

    def add_edge(self, edge: KGEdge) -> KGEdge:
        """Add a directed edge. Both source and target nodes must exist."""
        with self._lock:
            if edge.source_id not in self._nodes:
                raise ValueError(f"KnowledgeGraph: source node {edge.source_id!r} not found")
            if edge.target_id not in self._nodes:
                raise ValueError(f"KnowledgeGraph: target node {edge.target_id!r} not found")
            self._edges[edge.edge_id] = edge
            self._out_edges[edge.source_id].append(edge.edge_id)
            self._in_edges[edge.target_id].append(edge.edge_id)
        self._audit_write(
            "add_edge",
            {
                "edge_id": edge.edge_id,
                "source_id": edge.source_id,
                "target_id": edge.target_id,
                "edge_type": edge.edge_type,
            },
        )
        logger.debug(
            "KnowledgeGraph: edge %s %s→%s", edge.edge_type, edge.source_id, edge.target_id
        )
        return edge

    def get_edge(self, edge_id: str) -> Optional[KGEdge]:
        with self._lock:
            return self._edges.get(edge_id)

    # ------------------------------------------------------------------
    # Traversal
    # ------------------------------------------------------------------

    def get_neighbors(self, node_id: str, direction: str = "out") -> List[KGNode]:
        """
        Return neighboring nodes.

        direction='out'  → nodes this node points to
        direction='in'   → nodes that point to this node
        direction='both' → union
        """
        with self._lock:
            results: List[KGNode] = []
            if direction in ("out", "both"):
                for eid in self._out_edges.get(node_id, []):
                    edge = self._edges[eid]
                    if edge.target_id in self._nodes:
                        results.append(self._nodes[edge.target_id])
            if direction in ("in", "both"):
                for eid in self._in_edges.get(node_id, []):
                    edge = self._edges[eid]
                    if edge.source_id in self._nodes:
                        results.append(self._nodes[edge.source_id])
            return results

    def find_path(self, start_id: str, end_id: str) -> Optional[List[str]]:
        """BFS shortest path from start_id to end_id. Returns list of node_ids or None."""
        with self._lock:
            if start_id not in self._nodes or end_id not in self._nodes:
                return None
            if start_id == end_id:
                return [start_id]
            visited = {start_id}
            queue = [[start_id]]
            while queue:
                path = queue.pop(0)
                current = path[-1]
                for eid in self._out_edges.get(current, []):
                    nxt = self._edges[eid].target_id
                    if nxt == end_id:
                        return path + [nxt]
                    if nxt not in visited:
                        visited.add(nxt)
                        queue.append(path + [nxt])
            return None

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def all_nodes(self) -> List[KGNode]:
        with self._lock:
            return list(self._nodes.values())

    def all_edges(self) -> List[KGEdge]:
        with self._lock:
            return list(self._edges.values())

    def node_count(self) -> int:
        with self._lock:
            return len(self._nodes)

    def edge_count(self) -> int:
        with self._lock:
            return len(self._edges)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _audit_write(self, action: str, data: Dict[str, Any]) -> None:
        if self._audit is not None:
            try:
                self._audit.append({"component": "KnowledgeGraph", "action": action, **data})
            except Exception:
                logger.exception("KnowledgeGraph: audit write failed")

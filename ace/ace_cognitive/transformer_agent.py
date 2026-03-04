"""TransformerAgent: AST-based code analysis and dependency graph construction."""
from __future__ import annotations

import ast
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from ace.runtime.agent_bus import AgentBus, AgentMessage
from ace.runtime.golden_trace import GoldenTrace

__all__ = ["CodeArtifact", "DependencyGraph", "TransformerAgent"]

logger = logging.getLogger(__name__)


@dataclass
class CodeArtifact:
    """A parsed code element extracted from a Python source file."""

    artifact_id: str
    file_path: str
    artifact_type: str  # module, class, function, import
    name: str
    dependencies: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DependencyGraph:
    """Dependency graph built from a set of CodeArtifacts."""

    graph_id: str
    artifacts: List[CodeArtifact]
    edges: List[Tuple[str, str]]  # (from_artifact_id, to_artifact_id)
    cycles: List[List[str]]       # detected cycles
    total_files: int
    total_functions: int
    created_at: float = field(default_factory=time.time)


class _ASTVisitor(ast.NodeVisitor):
    """Extract classes, functions, and imports from a single Python module."""

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.artifacts: List[CodeArtifact] = []
        self._imports: List[str] = []

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            self._imports.append(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        if node.module:
            self._imports.append(node.module)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        artifact_id = f"{self.file_path}::{node.name}"
        self.artifacts.append(
            CodeArtifact(
                artifact_id=artifact_id,
                file_path=self.file_path,
                artifact_type="class",
                name=node.name,
                dependencies=list(self._imports),
                metadata={"lineno": node.lineno},
            )
        )
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        artifact_id = f"{self.file_path}::{node.name}"
        self.artifacts.append(
            CodeArtifact(
                artifact_id=artifact_id,
                file_path=self.file_path,
                artifact_type="function",
                name=node.name,
                dependencies=list(self._imports),
                metadata={"lineno": node.lineno},
            )
        )
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def finalize(self) -> None:
        """Add a module-level artifact capturing top-level imports."""
        artifact_id = f"{self.file_path}::__module__"
        self.artifacts.insert(
            0,
            CodeArtifact(
                artifact_id=artifact_id,
                file_path=self.file_path,
                artifact_type="module",
                name=os.path.basename(self.file_path),
                dependencies=list(self._imports),
            ),
        )


class TransformerAgent:
    """
    Parses Python source files and builds a dependency graph.

    Large-repo note: For repositories with many files, consider routing
    the scan task through TaskDelegator (ace.distributed.task_delegator)
    to distribute the work across nodes.
    """

    AGENT_ID = "transformer"

    def __init__(self, bus: AgentBus, audit_trail=None) -> None:
        self._bus = bus
        self._audit = audit_trail
        self._trace = GoldenTrace.get_instance()
        self._bus.subscribe(self.AGENT_ID, self._handle_message)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse_source(self, file_path: str, source: str) -> List[CodeArtifact]:
        """Parse *source* (Python code string) and return extracted artifacts."""
        try:
            tree = ast.parse(source, filename=file_path)
        except SyntaxError as exc:
            logger.warning("TransformerAgent: syntax error in %s: %s", file_path, exc)
            return []

        visitor = _ASTVisitor(file_path)
        visitor.visit(tree)
        visitor.finalize()
        self._log("source_parsed", {"file_path": file_path, "artifact_count": len(visitor.artifacts)})
        return visitor.artifacts

    def build_dependency_graph(self, artifacts: List[CodeArtifact]) -> DependencyGraph:
        """Build a DependencyGraph from a list of artifacts."""
        # Build edges: artifact A → artifact B if A.dependencies contains B's name
        artifact_map = {a.artifact_id: a for a in artifacts}
        name_to_ids: Dict[str, List[str]] = {}
        for a in artifacts:
            name_to_ids.setdefault(a.name, []).append(a.artifact_id)

        edges: List[Tuple[str, str]] = []
        for a in artifacts:
            for dep in a.dependencies:
                for dep_id in name_to_ids.get(dep, []):
                    if dep_id != a.artifact_id:
                        edges.append((a.artifact_id, dep_id))

        cycles = self._detect_cycles(artifacts, edges)
        total_functions = sum(1 for a in artifacts if a.artifact_type == "function")
        total_files = len({a.file_path for a in artifacts})

        graph = DependencyGraph(
            graph_id=str(uuid.uuid4()),
            artifacts=artifacts,
            edges=edges,
            cycles=cycles,
            total_files=total_files,
            total_functions=total_functions,
        )
        self._log(
            "graph_built",
            {
                "graph_id": graph.graph_id,
                "total_files": total_files,
                "total_functions": total_functions,
                "cycles": len(cycles),
            },
        )
        return graph

    # ------------------------------------------------------------------
    # Cycle detection (DFS)
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_cycles(
        artifacts: List[CodeArtifact], edges: List[Tuple[str, str]]
    ) -> List[List[str]]:
        adj: Dict[str, List[str]] = {a.artifact_id: [] for a in artifacts}
        for src, dst in edges:
            adj.setdefault(src, []).append(dst)

        visited: Set[str] = set()
        rec_stack: Set[str] = set()
        cycles: List[List[str]] = []

        def dfs(node: str, path: List[str]) -> None:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)
            for neighbour in adj.get(node, []):
                if neighbour not in visited:
                    dfs(neighbour, path)
                elif neighbour in rec_stack:
                    # Found a cycle
                    cycle_start = path.index(neighbour)
                    cycles.append(list(path[cycle_start:]))
            path.pop()
            rec_stack.discard(node)

        for artifact in artifacts:
            if artifact.artifact_id not in visited:
                dfs(artifact.artifact_id, [])

        return cycles

    # ------------------------------------------------------------------
    # Bus handler
    # ------------------------------------------------------------------

    def _handle_message(self, msg: AgentMessage) -> None:
        if msg.message_type != "request":
            return
        action = msg.payload.get("action")
        if action == "parse_source":
            artifacts = self.parse_source(
                msg.payload.get("file_path", "<unknown>"),
                msg.payload.get("source", ""),
            )
            self._bus.send(
                sender=self.AGENT_ID,
                recipient=msg.sender,
                message_type="response",
                payload={"result": [a.artifact_id for a in artifacts]},
                correlation_id=msg.correlation_id,
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _log(self, action: str, data: Dict[str, Any]) -> None:
        if self._audit is not None:
            try:
                self._audit.append({"component": "TransformerAgent", "action": action, **data})
            except Exception:
                logger.exception("TransformerAgent: audit write failed")
        try:
            self._trace.log_event(f"transformer.{action}", data)
        except Exception:
            pass

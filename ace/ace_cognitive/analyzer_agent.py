"""AnalyzerAgent: Architecture metrics and refactoring proposal generation."""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set

from ace.runtime.agent_bus import AgentBus, AgentMessage
from ace.runtime.golden_trace import GoldenTrace
from ace.ace_cognitive.transformer_agent import DependencyGraph, CodeArtifact

__all__ = ["ArchitectureMetrics", "RefactoringProposal", "AnalyzerAgent"]

logger = logging.getLogger(__name__)


@dataclass
class ArchitectureMetrics:
    """Architecture quality metrics for a single artifact / file."""

    metrics_id: str
    file_path: str
    complexity_score: float      # 0–10
    coupling_score: float        # 0–10 (lower = better)
    cohesion_score: float        # 0–10 (higher = better)
    solid_violations: List[str]
    anti_patterns: List[str]
    created_at: float = field(default_factory=time.time)


@dataclass
class RefactoringProposal:
    """A ranked refactoring recommendation."""

    proposal_id: str
    target_artifact: str
    issue_type: str   # high_complexity, god_class, low_cohesion, high_coupling, etc.
    description: str
    impact_score: float   # 0–10
    effort_score: float   # 0–10 (lower = easier)
    priority: float = 0.0  # computed as impact / effort

    def __post_init__(self) -> None:
        if self.effort_score > 0:
            self.priority = self.impact_score / self.effort_score
        else:
            self.priority = self.impact_score


class AnalyzerAgent:
    """
    Computes architecture metrics from a DependencyGraph and generates
    ranked refactoring proposals.
    """

    AGENT_ID = "analyzer"

    # Thresholds
    _COMPLEXITY_HIGH = 7.0
    _COUPLING_HIGH = 7.0
    _COHESION_LOW = 3.0
    _GOD_CLASS_DEP_COUNT = 10

    def __init__(self, bus: AgentBus, audit_trail: Any = None) -> None:
        self._bus = bus
        self._audit = audit_trail
        self._trace = GoldenTrace.get_instance()
        self._metrics: Dict[str, ArchitectureMetrics] = {}
        self._proposals: Dict[str, RefactoringProposal] = {}
        self._bus.subscribe(self.AGENT_ID, self._handle_message)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, graph: DependencyGraph) -> List[ArchitectureMetrics]:
        """Compute metrics for every unique file in *graph*."""
        file_artifacts: Dict[str, List[CodeArtifact]] = {}
        for artifact in graph.artifacts:
            file_artifacts.setdefault(artifact.file_path, []).append(artifact)

        results: List[ArchitectureMetrics] = []
        for file_path, artifacts in file_artifacts.items():
            metrics = self._compute_metrics(file_path, artifacts, graph)
            self._metrics[metrics.metrics_id] = metrics
            results.append(metrics)

        self._log("analysis_complete", {"files_analyzed": len(results)})
        return results

    def propose_refactorings(
        self, metrics_list: List[ArchitectureMetrics]
    ) -> List[RefactoringProposal]:
        """Generate and rank refactoring proposals from *metrics_list*."""
        proposals: List[RefactoringProposal] = []

        for metrics in metrics_list:
            if metrics.complexity_score >= self._COMPLEXITY_HIGH:
                p = RefactoringProposal(
                    proposal_id=str(uuid.uuid4()),
                    target_artifact=metrics.file_path,
                    issue_type="high_complexity",
                    description=f"File {metrics.file_path} has high cyclomatic complexity ({metrics.complexity_score:.1f}/10). Consider splitting into smaller functions.",
                    impact_score=7.0,
                    effort_score=4.0,
                )
                proposals.append(p)

            if metrics.coupling_score >= self._COUPLING_HIGH:
                p = RefactoringProposal(
                    proposal_id=str(uuid.uuid4()),
                    target_artifact=metrics.file_path,
                    issue_type="high_coupling",
                    description=f"File {metrics.file_path} is tightly coupled to many modules ({metrics.coupling_score:.1f}/10). Apply Dependency Inversion.",
                    impact_score=8.0,
                    effort_score=6.0,
                )
                proposals.append(p)

            if metrics.cohesion_score <= self._COHESION_LOW:
                p = RefactoringProposal(
                    proposal_id=str(uuid.uuid4()),
                    target_artifact=metrics.file_path,
                    issue_type="low_cohesion",
                    description=f"File {metrics.file_path} has low cohesion ({metrics.cohesion_score:.1f}/10). Consider splitting by responsibility.",
                    impact_score=6.0,
                    effort_score=5.0,
                )
                proposals.append(p)

            for violation in metrics.solid_violations:
                p = RefactoringProposal(
                    proposal_id=str(uuid.uuid4()),
                    target_artifact=metrics.file_path,
                    issue_type="solid_violation",
                    description=f"SOLID violation in {metrics.file_path}: {violation}",
                    impact_score=5.0,
                    effort_score=3.0,
                )
                proposals.append(p)

        # Store and sort by priority descending
        proposals.sort(key=lambda p: p.priority, reverse=True)
        for p in proposals:
            self._proposals[p.proposal_id] = p

        self._log("proposals_generated", {"count": len(proposals)})
        return proposals

    # ------------------------------------------------------------------
    # Metric computation
    # ------------------------------------------------------------------

    def _compute_metrics(
        self,
        file_path: str,
        artifacts: List[CodeArtifact],
        graph: DependencyGraph,
    ) -> ArchitectureMetrics:
        functions = [a for a in artifacts if a.artifact_type == "function"]
        classes = [a for a in artifacts if a.artifact_type == "class"]

        # Complexity: based on function count (simple proxy)
        complexity = min(10.0, len(functions) * 1.5)

        # Coupling: unique external imports across all artifacts in file
        all_deps: Set[str] = set()
        for a in artifacts:
            all_deps.update(a.dependencies)
        coupling = min(10.0, len(all_deps) * 0.8)

        # Cohesion: inverse of number of classes (more focused files = higher cohesion)
        if len(classes) == 0:
            cohesion = 8.0
        elif len(classes) == 1:
            cohesion = 7.0
        else:
            cohesion = max(1.0, 10.0 - len(classes) * 1.5)

        # SOLID violation detection
        solid_violations: List[str] = []
        if len(classes) > 1:
            solid_violations.append("Single Responsibility: multiple classes in one file")
        if len(all_deps) > self._GOD_CLASS_DEP_COUNT:
            solid_violations.append("Open/Closed: high number of dependencies suggests mixed concerns")

        # Anti-patterns
        anti_patterns: List[str] = []
        if len(functions) > 15:
            anti_patterns.append("god_module")
        if len(classes) > 5:
            anti_patterns.append("god_class")

        return ArchitectureMetrics(
            metrics_id=str(uuid.uuid4()),
            file_path=file_path,
            complexity_score=round(complexity, 2),
            coupling_score=round(coupling, 2),
            cohesion_score=round(cohesion, 2),
            solid_violations=solid_violations,
            anti_patterns=anti_patterns,
        )

    # ------------------------------------------------------------------
    # Bus handler
    # ------------------------------------------------------------------

    def _handle_message(self, msg: AgentMessage) -> None:
        if msg.message_type != "request":
            return
        # Analysis requests are dispatched by CoordinatorAgent; respond via bus
        self._bus.send(
            sender=self.AGENT_ID,
            recipient=msg.sender,
            message_type="response",
            payload={"result": "analysis handled"},
            correlation_id=msg.correlation_id,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _log(self, action: str, data: Dict[str, Any]) -> None:
        if self._audit is not None:
            try:
                self._audit.append({"component": "AnalyzerAgent", "action": action, **data})
            except Exception:
                logger.exception("AnalyzerAgent: audit write failed")
        try:
            self._trace.log_event(f"analyzer.{action}", data)
        except Exception:
            pass

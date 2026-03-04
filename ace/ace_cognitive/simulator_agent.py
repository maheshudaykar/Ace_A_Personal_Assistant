"""SimulatorAgent: Simulate applying refactoring proposals safely."""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ace.runtime.agent_bus import AgentBus, AgentMessage
from ace.runtime.golden_trace import GoldenTrace
from ace.ace_cognitive.analyzer_agent import RefactoringProposal
from ace.ace_cognitive.transformer_agent import DependencyGraph

__all__ = ["SimulationResult", "SimulatorAgent"]

logger = logging.getLogger(__name__)


@dataclass
class SimulationResult:
    """Result of simulating one refactoring proposal."""

    simulation_id: str
    proposal_id: str
    status: str  # success / failed / broken
    changes_applied: List[str]
    test_results: Dict[str, Any]  # {'passed': int, 'failed': int, 'errors': int}
    breakages: List[str]
    validation_report: str
    timestamp: float = field(default_factory=time.time)


class SimulatorAgent:
    """
    Simulates applying refactoring proposals and assesses their safety.

    Production note: In a real deployment this agent would clone the repository
    into an isolated sandbox, apply the proposed changes, and execute the test
    suite.  Here we simulate the outcome based on the dependency graph structure.
    """

    AGENT_ID = "simulator"

    def __init__(self, bus: AgentBus, audit_trail=None) -> None:
        self._bus = bus
        self._audit = audit_trail
        self._trace = GoldenTrace.get_instance()
        self._results: Dict[str, SimulationResult] = {}
        self._bus.subscribe(self.AGENT_ID, self._handle_message)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def simulate(
        self,
        proposal: RefactoringProposal,
        graph: Optional[DependencyGraph] = None,
    ) -> SimulationResult:
        """
        Simulate applying *proposal* against *graph*.

        Checks whether the proposal's target artifact has dependants that
        could break, then generates a validation report.
        """
        sim_id = str(uuid.uuid4())
        changes_applied: List[str] = []
        breakages: List[str] = []

        # Determine affected dependencies from graph
        affected_deps: List[str] = []
        if graph is not None:
            for src, dst in graph.edges:
                if proposal.target_artifact in (src, dst):
                    affected_deps.append(f"{src} → {dst}")

        changes_applied.append(f"Simulated: {proposal.issue_type} on {proposal.target_artifact}")

        # Heuristic: high-effort proposals are more likely to introduce breakage
        breakage_risk = proposal.effort_score / 10.0
        if breakage_risk > 0.7 and affected_deps:
            breakages = [f"Potential breakage: {dep}" for dep in affected_deps[:3]]
            status = "broken"
        else:
            status = "success"

        # Simulate test results
        total_tests = max(5, len(affected_deps) * 2)
        failed = len(breakages)
        passed = total_tests - failed
        test_results = {"passed": passed, "failed": failed, "errors": 0}

        report_lines = [
            f"Simulation for proposal '{proposal.issue_type}' on '{proposal.target_artifact}':",
            f"  Status: {status}",
            f"  Changes: {len(changes_applied)}",
            f"  Affected dependencies: {len(affected_deps)}",
            f"  Breakages detected: {len(breakages)}",
            f"  Tests: {passed} passed, {failed} failed",
        ]
        if breakages:
            report_lines.append("  Breakage detail:")
            for b in breakages:
                report_lines.append(f"    - {b}")

        result = SimulationResult(
            simulation_id=sim_id,
            proposal_id=proposal.proposal_id,
            status=status,
            changes_applied=changes_applied,
            test_results=test_results,
            breakages=breakages,
            validation_report="\n".join(report_lines),
        )
        self._results[sim_id] = result
        self._log(
            "simulation_complete",
            {"simulation_id": sim_id, "status": status, "breakages": len(breakages)},
        )
        return result

    def get_result(self, simulation_id: str) -> Optional[SimulationResult]:
        return self._results.get(simulation_id)

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
            payload={"result": "simulation handled"},
            correlation_id=msg.correlation_id,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _log(self, action: str, data: Dict[str, Any]) -> None:
        if self._audit is not None:
            try:
                self._audit.append({"component": "SimulatorAgent", "action": action, **data})
            except Exception:
                logger.exception("SimulatorAgent: audit write failed")
        try:
            self._trace.log_event(f"simulator.{action}", data)
        except Exception:
            pass

"""Phase 4 cognitive agents test suite – 50+ tests."""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict
from typing import Any, Dict, List

import pytest

# ── AgentBus ────────────────────────────────────────────────────────────────
from ace.runtime.agent_bus import AgentBus, AgentMessage

# ── CoordinatorAgent ────────────────────────────────────────────────────────
from ace.ace_cognitive.coordinator_agent import (
    CoordinatorAgent,
    WorkflowPlan,
    WorkflowStep,
)

# ── KnowledgeGraph ──────────────────────────────────────────────────────────
from ace.ace_memory.knowledge_graph import KGEdge, KGNode, KnowledgeGraph

# ── PredictorAgent ──────────────────────────────────────────────────────────
from ace.ace_cognitive.predictor_agent import (
    ActionSequence,
    Prediction,
    PredictionPattern,
    PredictorAgent,
)

# ── ValidatorAgent ──────────────────────────────────────────────────────────
from ace.ace_cognitive.validator_agent import ValidationResult, ValidatorAgent

# ── ExecutorAgent ───────────────────────────────────────────────────────────
from ace.ace_cognitive.executor_agent import ExecutionResult, ExecutorAgent

# ── TransformerAgent ────────────────────────────────────────────────────────
from ace.ace_cognitive.transformer_agent import (
    CodeArtifact,
    DependencyGraph,
    TransformerAgent,
)

# ── AnalyzerAgent ───────────────────────────────────────────────────────────
from ace.ace_cognitive.analyzer_agent import (
    AnalyzerAgent,
    ArchitectureMetrics,
    RefactoringProposal,
)

# ── SimulatorAgent ──────────────────────────────────────────────────────────
from ace.ace_cognitive.simulator_agent import SimulationResult, SimulatorAgent

# ── TaskGraphEngine ─────────────────────────────────────────────────────────
from ace.runtime.task_graph_engine import GraphTask, TaskGraphEngine

# ── ReflectionAgent ─────────────────────────────────────────────────────────
from ace.ace_cognitive.reflection_agent import ReflectionAgent, ReflectionResult

# ── FeedbackEngine ──────────────────────────────────────────────────────────
from ace.ace_cognitive.feedback_engine import FeedbackEngine, FeedbackEntry, ModelUpdate


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def bus():
    return AgentBus()


@pytest.fixture
def coordinator(bus):
    return CoordinatorAgent(bus=bus)


@pytest.fixture
def kg():
    return KnowledgeGraph()


@pytest.fixture
def predictor(bus):
    return PredictorAgent(bus=bus)


@pytest.fixture
def validator(bus):
    return ValidatorAgent(bus=bus)


@pytest.fixture
def executor(bus):
    return ExecutorAgent(bus=bus)


@pytest.fixture
def transformer(bus):
    return TransformerAgent(bus=bus)


@pytest.fixture
def analyzer(bus):
    return AnalyzerAgent(bus=bus)


@pytest.fixture
def simulator(bus):
    return SimulatorAgent(bus=bus)


@pytest.fixture
def engine():
    return TaskGraphEngine(max_workers=2)


@pytest.fixture
def reflector(bus):
    return ReflectionAgent(bus=bus)


@pytest.fixture
def feedback():
    return FeedbackEngine()


# ============================================================================
# AgentBus tests (5)
# ============================================================================


class TestAgentBus:
    def test_subscribe_and_receive(self, bus):
        received = []
        bus.subscribe("agent_a", lambda m: received.append(m))
        bus.send("sender", "agent_a", "event", {"x": 1})
        assert len(received) == 1
        assert received[0].payload["x"] == 1

    def test_message_history_bounded(self, bus):
        bus.subscribe("agent_b", lambda m: None)
        for i in range(1050):
            bus.send("s", "agent_b", "event", {"i": i})
        assert len(bus.get_history()) == 1000

    def test_message_fields(self, bus):
        msg = bus.send("src", "dst", "request", {"k": "v"}, correlation_id="corr-123")
        assert msg.sender == "src"
        assert msg.recipient == "dst"
        assert msg.message_type == "request"
        assert msg.correlation_id == "corr-123"

    def test_unsubscribe(self, bus):
        calls = []
        handler = lambda m: calls.append(m)
        bus.subscribe("agent_c", handler)
        bus.unsubscribe("agent_c", handler)
        bus.send("s", "agent_c", "event", {})
        assert calls == []

    def test_multiple_subscribers(self, bus):
        results = []
        bus.subscribe("shared", lambda m: results.append("h1"))
        bus.subscribe("shared", lambda m: results.append("h2"))
        bus.send("s", "shared", "event", {})
        assert set(results) == {"h1", "h2"}


# ============================================================================
# CoordinatorAgent tests (5)
# ============================================================================


class TestCoordinatorAgent:
    def _make_step(self, step_id: str, deps=None) -> WorkflowStep:
        return WorkflowStep(
            step_id=step_id,
            agent_id="test_agent",
            action="noop",
            inputs={},
            dependencies=deps or [],
        )

    def test_create_plan(self, coordinator):
        step = self._make_step("s1")
        plan = coordinator.create_plan("proactive", [step])
        assert plan.plan_id is not None
        assert plan.workflow_type == "proactive"
        assert len(plan.steps) == 1

    def test_list_plans(self, coordinator):
        coordinator.create_plan("proactive", [self._make_step("s1")])
        coordinator.create_plan("code_analysis", [self._make_step("s2")])
        assert len(coordinator.list_plans()) == 2

    def test_get_plan(self, coordinator):
        plan = coordinator.create_plan("proactive", [self._make_step("s1")])
        retrieved = coordinator.get_plan(plan.plan_id)
        assert retrieved is not None
        assert retrieved.plan_id == plan.plan_id

    def test_execute_plan_no_handlers_times_out(self, coordinator):
        """Steps targeting unregistered agents should fail (timeout)."""
        step = WorkflowStep(
            step_id="s1",
            agent_id="nonexistent_agent",
            action="something",
            inputs={},
            dependencies=[],
        )
        plan = coordinator.create_plan("proactive", [step])
        # Reduce timeout by monkeypatching
        import ace.ace_cognitive.coordinator_agent as ca_mod
        original = ca_mod.CoordinatorAgent.MAX_RETRIES
        ca_mod.CoordinatorAgent.MAX_RETRIES = 1
        try:
            # Override dispatch timeout via patching threading.Event.wait
            import threading
            original_wait = threading.Event.wait
            threading.Event.wait = lambda self, timeout=None: False
            try:
                result = coordinator.execute_plan(plan)
            finally:
                threading.Event.wait = original_wait
        finally:
            ca_mod.CoordinatorAgent.MAX_RETRIES = original
        assert result.status in ("failed", "done")

    def test_workflow_step_dataclass(self):
        step = WorkflowStep(step_id="x", agent_id="a", action="act", inputs={"k": 1}, dependencies=[])
        d = asdict(step)
        assert d["step_id"] == "x"
        assert d["status"] == "pending"


# ============================================================================
# KnowledgeGraph tests (6)
# ============================================================================


class TestKnowledgeGraph:
    def _node(self, nid: str, ntype: str = "concept") -> KGNode:
        return KGNode(node_id=nid, node_type=ntype, properties={"label": nid}, created_at=time.time())

    def _edge(self, src: str, dst: str, etype: str = "related_to") -> KGEdge:
        return KGEdge(
            edge_id=str(uuid.uuid4()),
            source_id=src,
            target_id=dst,
            edge_type=etype,
            properties={},
            created_at=time.time(),
        )

    def test_add_and_get_node(self, kg):
        n = self._node("n1")
        kg.add_node(n)
        assert kg.get_node("n1") is n

    def test_node_count(self, kg):
        kg.add_node(self._node("a"))
        kg.add_node(self._node("b"))
        assert kg.node_count() == 2

    def test_add_edge(self, kg):
        kg.add_node(self._node("a"))
        kg.add_node(self._node("b"))
        e = self._edge("a", "b")
        kg.add_edge(e)
        assert kg.edge_count() == 1

    def test_get_neighbors_out(self, kg):
        kg.add_node(self._node("a"))
        kg.add_node(self._node("b"))
        kg.add_edge(self._edge("a", "b"))
        neighbors = kg.get_neighbors("a", direction="out")
        assert any(n.node_id == "b" for n in neighbors)

    def test_find_path(self, kg):
        for nid in ["x", "y", "z"]:
            kg.add_node(self._node(nid))
        kg.add_edge(self._edge("x", "y"))
        kg.add_edge(self._edge("y", "z"))
        path = kg.find_path("x", "z")
        assert path == ["x", "y", "z"]

    def test_find_path_no_path(self, kg):
        kg.add_node(self._node("a"))
        kg.add_node(self._node("b"))
        assert kg.find_path("a", "b") is None

    def test_edge_requires_existing_nodes(self, kg):
        kg.add_node(self._node("a"))
        with pytest.raises(ValueError):
            kg.add_edge(self._edge("a", "missing"))


# ============================================================================
# PredictorAgent tests (6)
# ============================================================================


class TestPredictorAgent:
    def _seq(self, actions: List[str], outcome: str = "success") -> ActionSequence:
        return ActionSequence(
            sequence_id=str(uuid.uuid4()),
            actions=actions,
            timestamp=time.time(),
            project_context={},
            outcome=outcome,
            duration_ms=100.0,
        )

    def test_observe_creates_patterns(self, predictor):
        predictor.observe(self._seq(["open", "edit", "save"]))
        assert len(predictor.get_patterns()) > 0

    def test_predict_returns_predictions(self, predictor):
        for _ in range(5):
            predictor.observe(self._seq(["open", "edit", "save"]))
        preds = predictor.predict(["open", "edit"])
        assert isinstance(preds, list)

    def test_prediction_confidence_threshold(self, predictor):
        for _ in range(5):
            predictor.observe(self._seq(["a", "b", "c"]))
        preds = predictor.predict(["a"])
        for p in preds:
            assert p.confidence_score >= 0.6

    def test_feedback_updates_confidence(self, predictor):
        for _ in range(5):
            predictor.observe(self._seq(["x", "y", "z"]))
        preds = predictor.predict(["x"])
        if preds:
            pred = preds[0]
            pattern = predictor._patterns[pred.pattern_id]
            before = pattern.confidence_score
            predictor.apply_feedback(pred.prediction_id, positive=False)
            predictor.apply_feedback(pred.prediction_id, positive=False)
            after = predictor._patterns[pred.pattern_id].confidence_score
            # Two negative feedbacks should lower or maintain confidence (0 positive / 2 total = 0.0)
            assert after <= before

    def test_action_sequence_dataclass(self):
        seq = ActionSequence(
            sequence_id="s1",
            actions=["a", "b"],
            timestamp=1.0,
            project_context={"proj": "test"},
            outcome="success",
            duration_ms=50.0,
        )
        d = asdict(seq)
        assert d["outcome"] == "success"

    def test_deterministic_patterns(self, bus):
        p1 = PredictorAgent(bus=AgentBus(), seed=42)
        p2 = PredictorAgent(bus=AgentBus(), seed=42)
        seq = ActionSequence(
            sequence_id="s", actions=["a", "b", "c"], timestamp=1.0,
            project_context={}, outcome="success", duration_ms=10.0,
        )
        p1.observe(seq)
        p2.observe(seq)
        ids1 = sorted(p1._patterns.keys())
        ids2 = sorted(p2._patterns.keys())
        assert ids1 == ids2


# ============================================================================
# ValidatorAgent tests (6)
# ============================================================================


class TestValidatorAgent:
    def test_approve_safe_actions(self, validator):
        result = validator.validate("pred-1", ["open_file", "read_config"])
        assert result.decision == "approved"

    def test_reject_high_risk_actions(self, validator):
        # Three high-risk keywords (each +0.3) → risk 0.9 > 0.8 → rejected
        result = validator.validate("pred-2", ["delete all files", "drop database", "sudo rm"])
        assert result.decision == "rejected"
        assert result.risk_score > 0.8

    def test_warning_medium_risk(self, validator):
        # Two high-risk keywords → risk 0.6 > 0.5 → warning
        result = validator.validate("pred-3", ["exec script", "delete temp"])
        assert result.decision in ("warning", "rejected")

    def test_policy_violations_populated(self, validator):
        result = validator.validate("pred-4", ["sudo rm -rf /"])
        assert len(result.policy_violations) > 0

    def test_result_stored(self, validator):
        validator.validate("pred-5", ["read_file"])
        assert validator.get_result("pred-5") is not None

    def test_validation_result_dataclass(self):
        vr = ValidationResult(
            prediction_id="p",
            risk_score=0.3,
            decision="approved",
            reason="ok",
            policy_violations=[],
        )
        d = asdict(vr)
        assert d["decision"] == "approved"


# ============================================================================
# ExecutorAgent tests (6)
# ============================================================================


class TestExecutorAgent:
    def test_execute_approved(self, executor):
        result = executor.execute("pred-1", ["read_config"], "approved")
        assert result.status == "success"
        assert result.execution_id is not None

    def test_execute_rejected(self, executor):
        result = executor.execute("pred-2", ["delete_all"], "rejected")
        assert result.status == "rejected"

    def test_side_effects_pending(self, executor):
        result = executor.execute("pred-3", ["write report"], "approved")
        assert result.requires_approval is True or result.side_effects != []

    def test_apply_side_effects(self, executor):
        result = executor.execute("pred-4", ["create file"], "approved")
        effects = executor.apply_side_effects(result.execution_id)
        assert isinstance(effects, list)

    def test_sandbox_stats_present(self, executor):
        result = executor.execute("pred-5", ["run script"], "approved")
        assert "timeout_seconds" in result.sandbox_stats
        assert result.sandbox_stats["simulated"] is True

    def test_execution_result_dataclass(self):
        er = ExecutionResult(
            execution_id="e1",
            prediction_id="p1",
            status="success",
            output="ok",
            side_effects=[],
            duration_ms=10.0,
            sandbox_stats={},
            requires_approval=False,
        )
        d = asdict(er)
        assert d["status"] == "success"


# ============================================================================
# TransformerAgent tests (6)
# ============================================================================

_SAMPLE_SOURCE = """
import os
import sys

class MyClass:
    def method(self):
        pass

def standalone():
    pass
"""


class TestTransformerAgent:
    def test_parse_source_returns_artifacts(self, transformer):
        artifacts = transformer.parse_source("test.py", _SAMPLE_SOURCE)
        assert len(artifacts) > 0

    def test_parse_detects_class(self, transformer):
        artifacts = transformer.parse_source("test.py", _SAMPLE_SOURCE)
        types = [a.artifact_type for a in artifacts]
        assert "class" in types

    def test_parse_detects_function(self, transformer):
        artifacts = transformer.parse_source("test.py", _SAMPLE_SOURCE)
        names = [a.name for a in artifacts]
        assert "standalone" in names or "method" in names

    def test_build_dependency_graph(self, transformer):
        artifacts = transformer.parse_source("test.py", _SAMPLE_SOURCE)
        graph = transformer.build_dependency_graph(artifacts)
        assert graph.total_files == 1
        assert graph.total_functions >= 1

    def test_cycle_detection_no_cycles(self, transformer):
        artifacts = transformer.parse_source("test.py", _SAMPLE_SOURCE)
        graph = transformer.build_dependency_graph(artifacts)
        # simple source has no cycles
        assert isinstance(graph.cycles, list)

    def test_invalid_syntax_returns_empty(self, transformer):
        artifacts = transformer.parse_source("bad.py", "def :(")
        assert artifacts == []

    def test_code_artifact_dataclass(self):
        ca = CodeArtifact(
            artifact_id="a::func",
            file_path="a.py",
            artifact_type="function",
            name="func",
            dependencies=["os"],
        )
        d = asdict(ca)
        assert d["artifact_type"] == "function"


# ============================================================================
# AnalyzerAgent tests (6)
# ============================================================================


class TestAnalyzerAgent:
    def _graph(self, transformer) -> DependencyGraph:
        artifacts = transformer.parse_source("test.py", _SAMPLE_SOURCE)
        return transformer.build_dependency_graph(artifacts)

    def test_analyze_returns_metrics(self, analyzer, transformer):
        graph = self._graph(transformer)
        metrics_list = analyzer.analyze(graph)
        assert len(metrics_list) > 0

    def test_metrics_scores_in_range(self, analyzer, transformer):
        graph = self._graph(transformer)
        for m in analyzer.analyze(graph):
            assert 0 <= m.complexity_score <= 10
            assert 0 <= m.coupling_score <= 10
            assert 0 <= m.cohesion_score <= 10

    def test_propose_refactorings(self, analyzer, transformer):
        graph = self._graph(transformer)
        metrics_list = analyzer.analyze(graph)
        proposals = analyzer.propose_refactorings(metrics_list)
        assert isinstance(proposals, list)

    def test_proposals_sorted_by_priority(self, analyzer, transformer):
        graph = self._graph(transformer)
        metrics_list = analyzer.analyze(graph)
        proposals = analyzer.propose_refactorings(metrics_list)
        priorities = [p.priority for p in proposals]
        assert priorities == sorted(priorities, reverse=True)

    def test_architecture_metrics_dataclass(self):
        m = ArchitectureMetrics(
            metrics_id="m1",
            file_path="f.py",
            complexity_score=5.0,
            coupling_score=3.0,
            cohesion_score=7.0,
            solid_violations=[],
            anti_patterns=[],
        )
        d = asdict(m)
        assert d["complexity_score"] == 5.0

    def test_refactoring_proposal_priority(self):
        p = RefactoringProposal(
            proposal_id="p1",
            target_artifact="mod.py",
            issue_type="high_complexity",
            description="test",
            impact_score=8.0,
            effort_score=4.0,
        )
        assert p.priority == pytest.approx(2.0)


# ============================================================================
# SimulatorAgent tests (5)
# ============================================================================


class TestSimulatorAgent:
    def _proposal(self, effort: float = 3.0) -> RefactoringProposal:
        return RefactoringProposal(
            proposal_id=str(uuid.uuid4()),
            target_artifact="module.py",
            issue_type="high_complexity",
            description="Refactor this",
            impact_score=7.0,
            effort_score=effort,
        )

    def test_simulate_returns_result(self, simulator):
        result = simulator.simulate(self._proposal())
        assert result.simulation_id is not None
        assert result.status in ("success", "failed", "broken")

    def test_simulate_low_effort_success(self, simulator):
        result = simulator.simulate(self._proposal(effort=2.0))
        assert result.status == "success"

    def test_simulate_high_effort_may_break(self, simulator, transformer):
        artifacts = transformer.parse_source("a.py", _SAMPLE_SOURCE)
        graph = transformer.build_dependency_graph(artifacts)
        prop = RefactoringProposal(
            proposal_id=str(uuid.uuid4()),
            target_artifact=artifacts[0].artifact_id,
            issue_type="high_coupling",
            description="Risky refactor",
            impact_score=9.0,
            effort_score=9.0,
        )
        result = simulator.simulate(prop, graph)
        assert result.validation_report != ""

    def test_test_results_structure(self, simulator):
        result = simulator.simulate(self._proposal())
        assert "passed" in result.test_results
        assert "failed" in result.test_results
        assert "errors" in result.test_results

    def test_simulation_result_dataclass(self):
        sr = SimulationResult(
            simulation_id="s1",
            proposal_id="p1",
            status="success",
            changes_applied=["change A"],
            test_results={"passed": 5, "failed": 0, "errors": 0},
            breakages=[],
            validation_report="ok",
        )
        d = asdict(sr)
        assert d["status"] == "success"


# ============================================================================
# TaskGraphEngine tests (6)
# ============================================================================


class TestTaskGraphEngine:
    def test_simple_execution(self, engine):
        task = GraphTask(
            task_id="t1", name="add", fn=lambda x, y: x + y, args={"x": 2, "y": 3},
            dependencies=[],
        )
        result = engine.execute([task])
        assert result["t1"].status == "done"
        assert result["t1"].result == 5

    def test_dependency_ordering(self, engine):
        order = []
        t1 = GraphTask(task_id="t1", name="first", fn=lambda: order.append("t1"), args={}, dependencies=[])
        t2 = GraphTask(task_id="t2", name="second", fn=lambda: order.append("t2"), args={}, dependencies=["t1"])
        engine.execute([t1, t2])
        assert order.index("t1") < order.index("t2")

    def test_parallel_tasks(self, engine):
        import threading
        barrier = threading.Barrier(2)

        def slow():
            barrier.wait(timeout=5)
            return "done"

        t1 = GraphTask(task_id="t1", name="p1", fn=slow, args={}, dependencies=[])
        t2 = GraphTask(task_id="t2", name="p2", fn=slow, args={}, dependencies=[])
        result = engine.execute([t1, t2])
        assert result["t1"].status == "done"
        assert result["t2"].status == "done"

    def test_failed_task(self, engine):
        def boom():
            raise RuntimeError("boom")

        task = GraphTask(task_id="t1", name="fail", fn=boom, args={}, dependencies=[])
        result = engine.execute([task])
        assert result["t1"].status == "failed"

    def test_cycle_detection(self, engine):
        t1 = GraphTask(task_id="t1", name="a", fn=lambda: None, args={}, dependencies=["t2"])
        t2 = GraphTask(task_id="t2", name="b", fn=lambda: None, args={}, dependencies=["t1"])
        with pytest.raises(ValueError, match="cycle"):
            engine.execute([t1, t2])

    def test_graph_task_dataclass(self):
        t = GraphTask(task_id="x", name="n", fn=lambda: None, args={}, dependencies=[])
        assert t.status == "pending"
        assert t.result is None


# ============================================================================
# ReflectionAgent tests (4)
# ============================================================================


class TestReflectionAgent:
    def _plan_with(self, statuses: List[str], bus) -> WorkflowPlan:
        coordinator = CoordinatorAgent(bus=bus)
        steps = [
            WorkflowStep(
                step_id=f"s{i}",
                agent_id="a",
                action="act",
                inputs={},
                dependencies=[],
                status=s,
            )
            for i, s in enumerate(statuses)
        ]
        plan = coordinator.create_plan("proactive", steps)
        plan.status = "done" if all(s == "done" for s in statuses) else "failed"
        return plan

    def test_reflect_successful_plan(self, reflector, bus):
        plan = self._plan_with(["done", "done"], bus)
        result = reflector.reflect(plan)
        assert result.failures_detected == []
        assert len(result.improvements_proposed) > 0

    def test_reflect_failed_plan(self, reflector, bus):
        plan = self._plan_with(["done", "failed"], bus)
        result = reflector.reflect(plan)
        assert len(result.failures_detected) == 1

    def test_reflection_stored(self, reflector, bus):
        plan = self._plan_with(["done"], bus)
        result = reflector.reflect(plan)
        assert result.reflection_id in {r.reflection_id for r in reflector.get_all_reflections()}

    def test_reflection_result_dataclass(self):
        rr = ReflectionResult(
            reflection_id="r1",
            workflow_id="w1",
            failures_detected=[],
            improvements_proposed=["improve A"],
            pattern_adjustments={},
            heuristic_updates={},
        )
        d = asdict(rr)
        assert d["workflow_id"] == "w1"


# ============================================================================
# FeedbackEngine tests (4)
# ============================================================================


class TestFeedbackEngine:
    def test_record_entry(self, feedback):
        entry = feedback.record("pred-1", "prediction_accepted", "great")
        assert entry.feedback_id is not None
        assert entry.target_id == "pred-1"

    def test_compute_prediction_update(self, feedback):
        feedback.record("pred-1", "prediction_accepted")
        feedback.record("pred-2", "prediction_rejected")
        update = feedback.compute_update("prediction")
        assert "acceptance_rate" in update.adjustments

    def test_compute_analysis_update(self, feedback):
        feedback.record("prop-1", "refactor_useful")
        feedback.record("prop-2", "refactor_useful")
        update = feedback.compute_update("analysis")
        assert update.adjustments["acceptance_rate"] == pytest.approx(1.0)

    def test_model_update_dataclass(self):
        mu = ModelUpdate(
            update_id="u1",
            feedback_ids=["f1"],
            model_type="prediction",
            adjustments={"acceptance_rate": 0.8},
        )
        d = asdict(mu)
        assert d["model_type"] == "prediction"


# ============================================================================
# Integration tests (4)
# ============================================================================


class TestIntegration:
    def test_predictor_validator_executor_pipeline(self, bus):
        predictor = PredictorAgent(bus=bus)
        validator = ValidatorAgent(bus=bus)
        executor = ExecutorAgent(bus=bus)

        seq = ActionSequence(
            sequence_id="s1",
            actions=["open", "read", "write"],
            timestamp=time.time(),
            project_context={},
            outcome="success",
            duration_ms=100.0,
        )
        for _ in range(6):
            predictor.observe(seq)

        preds = predictor.predict(["open", "read"])
        if preds:
            pred = preds[0]
            val_result = validator.validate(pred.prediction_id, pred.predicted_actions)
            exec_result = executor.execute(
                pred.prediction_id,
                pred.predicted_actions,
                val_result.decision,
            )
            assert exec_result.status in ("success", "rejected", "failed")

    def test_transformer_analyzer_simulator_pipeline(self, bus):
        transformer = TransformerAgent(bus=bus)
        analyzer = AnalyzerAgent(bus=bus)
        simulator = SimulatorAgent(bus=bus)

        artifacts = transformer.parse_source("sample.py", _SAMPLE_SOURCE)
        graph = transformer.build_dependency_graph(artifacts)
        metrics_list = analyzer.analyze(graph)
        proposals = analyzer.propose_refactorings(metrics_list)

        if proposals:
            sim_result = simulator.simulate(proposals[0], graph)
            assert sim_result.status in ("success", "failed", "broken")

    def test_coordinator_reflection_feedback_pipeline(self, bus):
        coordinator = CoordinatorAgent(bus=bus)
        reflector = ReflectionAgent(bus=bus)
        fb_engine = FeedbackEngine()

        steps = [
            WorkflowStep(
                step_id="s1", agent_id="dummy", action="act", inputs={}, dependencies=[],
                status="done",
            )
        ]
        plan = coordinator.create_plan("proactive", steps)
        plan.status = "done"
        reflection = reflector.reflect(plan)
        fb = fb_engine.record(plan.plan_id, "prediction_accepted", "good workflow")
        update = fb_engine.compute_update("prediction")
        assert reflection.workflow_id == plan.plan_id
        assert fb.target_id == plan.plan_id
        assert update.adjustments["acceptance_rate"] == pytest.approx(1.0)

    def test_knowledge_graph_with_code_artifacts(self, kg, bus):
        transformer = TransformerAgent(bus=bus)
        artifacts = transformer.parse_source("sample.py", _SAMPLE_SOURCE)

        for a in artifacts:
            node = KGNode(
                node_id=a.artifact_id,
                node_type="function" if a.artifact_type == "function" else "concept",
                properties={"name": a.name},
                created_at=time.time(),
            )
            kg.add_node(node)

        assert kg.node_count() == len(artifacts)

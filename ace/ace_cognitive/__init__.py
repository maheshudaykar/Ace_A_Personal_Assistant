"""ace_cognitive — Phase 4 multi-agent cognitive reasoning components."""

from ace.ace_cognitive.coordinator_agent import CoordinatorAgent, WorkflowPlan, WorkflowStep
from ace.ace_cognitive.predictor_agent import PredictorAgent, ActionSequence, Prediction, PredictionPattern
from ace.ace_cognitive.validator_agent import ValidatorAgent, ValidationResult
from ace.ace_cognitive.executor_agent import ExecutorAgent, ExecutionResult
from ace.ace_cognitive.transformer_agent import TransformerAgent, CodeArtifact, DependencyGraph
from ace.ace_cognitive.analyzer_agent import AnalyzerAgent, ArchitectureMetrics, RefactoringProposal
from ace.ace_cognitive.simulator_agent import SimulatorAgent, SimulationResult
from ace.ace_cognitive.reflection_agent import ReflectionAgent, ReflectionResult
from ace.ace_cognitive.feedback_engine import FeedbackEngine, FeedbackEntry, ModelUpdate
from ace.ace_cognitive.planning_engine import (
    GoalSpecification,
    HierarchicalPlan,
    PlanningEngine,
    PlanningStrategy,
    TaskNode,
)

__all__ = [
    # Coordinator
    "CoordinatorAgent", "WorkflowPlan", "WorkflowStep",
    # Proactive intelligence
    "PredictorAgent", "ActionSequence", "Prediction", "PredictionPattern",
    "ValidatorAgent", "ValidationResult",
    "ExecutorAgent", "ExecutionResult",
    # Code analysis
    "TransformerAgent", "CodeArtifact", "DependencyGraph",
    "AnalyzerAgent", "ArchitectureMetrics", "RefactoringProposal",
    "SimulatorAgent", "SimulationResult",
    # Reflection & learning
    "ReflectionAgent", "ReflectionResult",
    "FeedbackEngine", "FeedbackEntry", "ModelUpdate",
    # Planning layer
    "PlanningEngine", "PlanningStrategy", "GoalSpecification", "TaskNode", "HierarchicalPlan",
]

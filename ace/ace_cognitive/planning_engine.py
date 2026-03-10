"""PlanningEngine: deterministic goal decomposition for workflow execution.

This module separates planning from execution. CoordinatorAgent executes
`WorkflowPlan` objects while PlanningEngine owns goal parsing and task
construction.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


def _str_list_default() -> List[str]:
    return []


def _str_any_dict_default() -> Dict[str, Any]:
    return {}


def _task_node_dict_default() -> Dict[str, "TaskNode"]:
    return {}


def _dep_graph_default() -> Dict[str, List[str]]:
    return {}

from ace.ace_cognitive.coordinator_agent import WorkflowPlan, WorkflowStep

__all__ = [
    "PlanningStrategy",
    "GoalSpecification",
    "TaskNode",
    "HierarchicalPlan",
    "PlanningEngine",
]


class PlanningStrategy(str, Enum):
    """Planning algorithm selection."""

    HIERARCHICAL_TASK_NETWORK = "HTN"
    REACTIVE = "REACTIVE"


@dataclass
class GoalSpecification:
    """Parsed user goal with execution constraints."""

    goal_id: str
    goal_text: str
    intent_type: str
    constraints: List[str] = field(default_factory=_str_list_default)
    context: Dict[str, Any] = field(default_factory=_str_any_dict_default)
    priority: int = 5
    deadline: Optional[float] = None


@dataclass
class TaskNode:
    """Node in a deterministic hierarchical task graph."""

    task_id: str
    task_type: str
    description: str
    estimated_duration_s: float = 60.0
    required_capabilities: Dict[str, Any] = field(default_factory=_str_any_dict_default)
    parent_task: Optional[str] = None
    subtasks: List[str] = field(default_factory=_str_list_default)
    dependencies: List[str] = field(default_factory=_str_list_default)
    constraints: List[str] = field(default_factory=_str_list_default)


@dataclass
class HierarchicalPlan:
    """Deterministic decomposition of a goal into tasks."""

    plan_id: str
    goal: GoalSpecification
    root_task: TaskNode
    all_tasks: Dict[str, TaskNode] = field(default_factory=_task_node_dict_default)
    dependency_graph: Dict[str, List[str]] = field(default_factory=_dep_graph_default)
    estimated_total_time_s: float = 0.0
    created_at: float = field(default_factory=time.time)
    strategy_used: str = PlanningStrategy.HIERARCHICAL_TASK_NETWORK.value


class PlanningEngine:
    """Deterministic planning layer above CoordinatorAgent."""

    def __init__(
        self,
        strategy: PlanningStrategy = PlanningStrategy.HIERARCHICAL_TASK_NETWORK,
    ) -> None:
        self.strategy = strategy

    def create_plan(self, goal_text: str, context: Optional[Dict[str, Any]] = None) -> HierarchicalPlan:
        """Create deterministic hierarchical plan from a natural-language goal."""
        goal = self.parse_goal(goal_text, context or {})
        root_task, all_tasks = self.decompose_goal(goal)
        graph = self.build_dependency_graph(all_tasks)
        if not self._validate_plan(graph):
            raise ValueError("Invalid plan: cycle detected")

        total_time = sum(task.estimated_duration_s for task in all_tasks.values())
        return HierarchicalPlan(
            plan_id=goal.goal_id,
            goal=goal,
            root_task=root_task,
            all_tasks=all_tasks,
            dependency_graph=graph,
            estimated_total_time_s=total_time,
            strategy_used=self.strategy.value,
        )

    def parse_goal(self, goal_text: str, context: Dict[str, Any]) -> GoalSpecification:
        """Parse goal text into a normalized GoalSpecification."""
        normalized = goal_text.strip().lower()
        intent = "analysis"
        if "refactor" in normalized:
            intent = "refactoring"
        elif "generate" in normalized or "create" in normalized:
            intent = "code_generation"
        elif "test" in normalized or "validate" in normalized:
            intent = "validation"

        stable_payload = json.dumps({"goal": normalized, "context": context}, sort_keys=True)
        goal_id = hashlib.sha256(stable_payload.encode("utf-8")).hexdigest()[:16]

        constraints = list(context.get("constraints", [])) if isinstance(context.get("constraints", []), list) else []
        return GoalSpecification(
            goal_id=goal_id,
            goal_text=goal_text,
            intent_type=intent,
            constraints=constraints,
            context=context,
        )

    def decompose_goal(self, goal: GoalSpecification) -> Tuple[TaskNode, Dict[str, TaskNode]]:
        """Decompose goal into deterministic task set."""
        root_id = f"{goal.goal_id}:root"
        root = TaskNode(
            task_id=root_id,
            task_type="composite",
            description=goal.goal_text,
            constraints=list(goal.constraints),
        )

        labels: List[Tuple[str, str, float, Dict[str, Any]]]
        if goal.intent_type == "refactoring":
            labels = [
                ("analyze", "Analyze current architecture", 45.0, {"min_cpu_cores": 1}),
                ("propose", "Generate refactoring proposal", 60.0, {"min_cpu_cores": 2}),
                ("simulate", "Simulate refactoring impact", 75.0, {"min_cpu_cores": 2, "min_ram_gb": 2.0}),
                ("execute", "Execute approved changes", 90.0, {"min_cpu_cores": 2}),
                ("validate", "Run validation tests", 120.0, {"min_cpu_cores": 2, "requires_tools": ["test_runner"]}),
            ]
        elif goal.intent_type == "code_generation":
            labels = [
                ("spec", "Extract implementation specification", 30.0, {"min_cpu_cores": 1}),
                ("generate", "Generate code artifacts", 80.0, {"min_cpu_cores": 2}),
                ("lint", "Run lint checks", 45.0, {"min_cpu_cores": 1, "requires_tools": ["linter"]}),
                ("validate", "Run tests", 90.0, {"min_cpu_cores": 2, "requires_tools": ["test_runner"]}),
            ]
        else:
            labels = [
                ("collect", "Collect context and inputs", 20.0, {"min_cpu_cores": 1}),
                ("analyze", "Analyze evidence", 50.0, {"min_cpu_cores": 1}),
                ("report", "Produce structured output", 25.0, {"min_cpu_cores": 1}),
            ]

        all_tasks: Dict[str, TaskNode] = {root.task_id: root}
        prev_id: Optional[str] = None
        for index, (suffix, desc, duration, caps) in enumerate(labels):
            task_id = f"{goal.goal_id}:{index:02d}:{suffix}"
            deps = [prev_id] if prev_id else []
            task = TaskNode(
                task_id=task_id,
                task_type="atomic",
                description=desc,
                estimated_duration_s=duration,
                required_capabilities=caps,
                parent_task=root.task_id,
                dependencies=[dep for dep in deps if dep],
                constraints=list(goal.constraints),
            )
            root.subtasks.append(task_id)
            all_tasks[task_id] = task
            prev_id = task_id

        return root, all_tasks

    def build_dependency_graph(self, tasks: Dict[str, TaskNode]) -> Dict[str, List[str]]:
        """Create dependency graph with deterministic node ordering."""
        graph: Dict[str, List[str]] = {}
        for task_id in sorted(tasks.keys()):
            graph[task_id] = sorted(tasks[task_id].dependencies)
        return graph

    def _validate_plan(self, dep_graph: Dict[str, List[str]]) -> bool:
        """Detect cycles using deterministic DFS traversal order."""
        visiting: set[str] = set()
        visited: set[str] = set()

        def dfs(node: str) -> bool:
            if node in visiting:
                return False
            if node in visited:
                return True
            visiting.add(node)
            for dep in sorted(dep_graph.get(node, [])):
                if not dfs(dep):
                    return False
            visiting.remove(node)
            visited.add(node)
            return True

        for node in sorted(dep_graph.keys()):
            if not dfs(node):
                return False
        return True

    def convert_to_workflow_plan(self, hierarchical_plan: HierarchicalPlan) -> WorkflowPlan:
        """Convert hierarchical tasks into CoordinatorAgent WorkflowPlan."""
        steps: List[WorkflowStep] = []
        for task_id in sorted(hierarchical_plan.all_tasks.keys()):
            task = hierarchical_plan.all_tasks[task_id]
            if task.task_type != "atomic":
                continue
            steps.append(
                WorkflowStep(
                    step_id=task.task_id,
                    agent_id="executor",
                    action=task.description,
                    inputs={
                        "task_id": task.task_id,
                        "required_capabilities": dict(task.required_capabilities),
                        "constraints": list(task.constraints),
                    },
                    dependencies=list(task.dependencies),
                )
            )

        return WorkflowPlan(
            plan_id=hierarchical_plan.plan_id,
            workflow_type=hierarchical_plan.goal.intent_type,
            steps=steps,
        )

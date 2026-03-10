from ace.ace_cognitive.planning_engine import PlanningEngine


def test_planning_engine_refactor_decomposition_is_deterministic() -> None:
    engine = PlanningEngine()
    plan1 = engine.create_plan("Refactor payment module")
    plan2 = engine.create_plan("Refactor payment module")

    assert plan1.plan_id == plan2.plan_id
    assert sorted(plan1.all_tasks.keys()) == sorted(plan2.all_tasks.keys())
    assert plan1.estimated_total_time_s == plan2.estimated_total_time_s


def test_planning_engine_converts_to_workflow() -> None:
    engine = PlanningEngine()
    hierarchical = engine.create_plan("Generate API client")
    workflow = engine.convert_to_workflow_plan(hierarchical)

    assert workflow.plan_id == hierarchical.plan_id
    assert len(workflow.steps) > 0
    assert all(step.inputs.get("required_capabilities") is not None for step in workflow.steps)

from ace.ace_cognitive.coordinator_agent import WorkflowPlan, WorkflowStep
from ace.distributed.data_structures import NodeCapabilities, NodeRecord
from ace.distributed.distributed_planner import DistributedPlanner
from ace.distributed.node_registry import NodeRegistry
from ace.distributed.task_delegator import TaskDelegator
from ace.distributed.types import NodeRole, NodeStatus, TrustLevel


def _make_node(node_id: str, cpu: int, ram: float) -> NodeRecord:
    return NodeRecord(
        node_id=node_id,
        hostname=node_id,
        ip_address="127.0.0.1",
        role=NodeRole.FOLLOWER,
        status=NodeStatus.ACTIVE,
        trust_level=TrustLevel.FULL,
        capabilities=NodeCapabilities(cpu_cores=cpu, ram_gb=ram, supported_tools=["test_runner"]),
    )


def test_distributed_planner_prefers_capable_remote_nodes() -> None:
    registry = NodeRegistry(cluster_size=2)
    registry.register_node(_make_node("node-a", cpu=8, ram=16.0))
    delegator = TaskDelegator(node_id="local", node_registry=registry)
    planner = DistributedPlanner("local", registry, delegator)

    plan = WorkflowPlan(
        plan_id="wf-1",
        workflow_type="refactoring",
        steps=[
            WorkflowStep(
                step_id="s1",
                agent_id="executor",
                action="simulate",
                inputs={"required_capabilities": {"min_cpu_cores": 4, "min_ram_gb": 8.0}},
                dependencies=[],
            )
        ],
    )

    distributed = planner.plan_workflow(plan)
    assert distributed.placements[0].execution_target == "node-a"

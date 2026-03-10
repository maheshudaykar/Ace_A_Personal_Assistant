"""
ACE Phase 3B Distributed Runtime Layer

Deterministic multi-node coordination system with crash-fault tolerant consensus (Raft),
anomaly detection, distributed memory synchronization, and task delegation.

Key Modules:
- consensus_engine: Raft-style consensus for leader election and state replication
- byzantine_detector: Anomaly detection and node quarantine
- distributed_memory_sync: Memory synchronization with leader-enforced quotas
- node_registry: Cluster node tracking and capability matching
- ssh_orchestrator: Secure remote task execution
- task_delegator: Task distribution and load balancing
- health_monitor: Node health monitoring and failure recovery
- remote_logging: Distributed audit trail with Raft-based ordering

Design Principles:
- Determinism via Raft log index (total ordering)
- Crash-fault tolerance (Raft consensus model)
- Leader-enforced governance (memory quotas, quota validation)
- Local RWLock only (no distributed locks)
- Defense-in-depth security (anomaly detection + quarantine)
"""

from .consensus_engine import ConsensusEngine
from .byzantine_detector import ByzantineDetector
from .memory_sync import DistributedMemorySync
from .node_registry import NodeRegistry
from .task_delegator import TaskDelegator
from .health_monitor import HealthMonitor
from .remote_logging import RemoteLogging
from .ssh_orchestrator import SSHOrchestrator
from .distributed_planner import DistributedPlanner, DistributedPlan, PlacementDecision
from .higher_level_orchestrator import HigherLevelOrchestrator, DistributedWorkflowResult
from .memory_federation import MemoryFederation, FederatedRecord, ConflictResolution
from .node_trust_manager import NodeTrustManager, CapabilityClass, NodeCapabilityPolicy
from .failover_orchestrator import FailoverOrchestrator, FailoverEvent
from .consistency_checker import DistributedConsistencyChecker

__version__ = "3.0.0"
__all__ = [
    "ConsensusEngine",
    "ByzantineDetector",
    "DistributedMemorySync",
    "NodeRegistry",
    "TaskDelegator",
    "HealthMonitor",
    "RemoteLogging",
    "SSHOrchestrator",
    "DistributedPlanner",
    "DistributedPlan",
    "PlacementDecision",
    "HigherLevelOrchestrator",
    "DistributedWorkflowResult",
    "MemoryFederation",
    "FederatedRecord",
    "ConflictResolution",
    "NodeTrustManager",
    "CapabilityClass",
    "NodeCapabilityPolicy",
    "FailoverOrchestrator",
    "FailoverEvent",
    "DistributedConsistencyChecker",
]

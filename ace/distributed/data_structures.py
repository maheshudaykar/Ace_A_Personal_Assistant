"""
Dataclasses for Phase 3B distributed system.

These define the core data structures used across consensus, memory sync,
task delegation, and monitoring.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple
import hashlib
from datetime import datetime

from .types import NodeRole, LogEntryType, MessageType, NodeStatus, TrustLevel

__all__ = [
    "LogEntry",
    "RaftState",
    "ClusterMessage",
    "NodeCapabilities",
    "NodeRecord",
    "NodeHealthMetrics",
    "ClusterHealth",
    "MemoryWriteProposal",
    "WriteProposalResponse",
    "MemorySyncPacket",
    "RemoteCommand",
    "RemoteResult",
    "DistributedEvent",
    "AuditSyncPacket",
    "AnomalyAlert",
    "NodeSuspicionRecord",
    "VoteRecord",
]


@dataclass
class LogEntry:
    """Entry in Raft distributed log with deterministic ordering."""
    term: int                           # Raft term when entry was created
    index: int                          # Raft log index (PRIMARY ORDERING KEY)
    entry_type: LogEntryType           # Type of entry (TASK, MEMORY_WRITE, etc.)
    payload: Dict[str, Any]            # Entry data payload
    timestamp: float                   # Monotonic timestamp (metadata only)
    checksum: str                      # SHA-256 checksum for integrity
    node_id: str = ""                  # Secondary tie-break (deterministic)
    
    @staticmethod
    def compute_checksum(payload: Dict[str, Any]) -> str:
        """Compute SHA-256 checksum of payload (deterministic)."""
        import json
        payload_str = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(payload_str.encode()).hexdigest()
    
    def verify_checksum(self) -> bool:
        """Verify entry checksum integrity."""
        computed = self.compute_checksum(self.payload)
        return computed == self.checksum


@dataclass
class RaftState:
    """Raft consensus state per node."""
    node_id: str
    role: NodeRole = NodeRole.FOLLOWER
    current_term: int = 0               # Latest term node has seen
    voted_for: Optional[str] = None     # Candidate received vote in current_term
    log: List[LogEntry] = field(default_factory=list)  # Replicated log entries
    commit_index: int = 0               # Index of highest committed entry
    last_applied: int = 0               # Index of highest applied entry
    
    # Leader state (reinitialized after election)
    next_index: Dict[str, int] = field(default_factory=dict)      # Per-follower next log index
    match_index: Dict[str, int] = field(default_factory=dict)     # Per-follower highest replicated index
    
    def get_last_log_index(self) -> int:
        """Get index of last log entry."""
        return self.log[-1].index if self.log else 0
    
    def get_last_log_term(self) -> int:
        """Get term of last log entry."""
        return self.log[-1].term if self.log else 0
    
    def snapshot(self) -> Dict[str, Any]:
        """Create read-only snapshot for GoldenTrace."""
        return {
            "node_id": self.node_id,
            "role": self.role.value,
            "current_term": self.current_term,
            "voted_for": self.voted_for,
            "log_length": len(self.log),
            "commit_index": self.commit_index,
            "last_applied": self.last_applied,
            "last_log_index": self.get_last_log_index(),
            "last_log_term": self.get_last_log_term(),
        }


@dataclass
class ClusterEventID:
    """Globally unique, totally ordered event ID for distributed events."""
    raft_log_index: int                 # PRIMARY ORDERING KEY (total order)
    node_id: str                        # Secondary tie-break (deterministic)
    lamport_time: Tuple[int, str, int] = (0, "", 0)  # (term, node_id, seq) - METADATA ONLY
    
    def __lt__(self, other: 'ClusterEventID') -> bool:
        """Total ordering using Raft log index as primary key."""
        return (self.raft_log_index, self.node_id) < (other.raft_log_index, other.node_id)
    
    def __le__(self, other: 'ClusterEventID') -> bool:
        return (self.raft_log_index, self.node_id) <= (other.raft_log_index, other.node_id)
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ClusterEventID):
            return NotImplemented
        return (self.raft_log_index, self.node_id) == (other.raft_log_index, other.node_id)


@dataclass
class ClusterMessage:
    """Base message for all distributed cluster communication."""
    msg_id: str                        # UUID of this message
    msg_type: MessageType              # Type of message
    source_node: str                   # Originating node_id
    target_node: str                   # Destination node_id
    term: int                          # Raft term
    timestamp: float                   # Monotonic timestamp
    payload: Dict[str, Any]            # Message data
    signature: str = ""                # HMAC-SHA256 (if security enabled)
    
    def serialize(self) -> str:
        """Deterministic serialization (for signing and comparison)."""
        import json
        # Sort keys for deterministic output
        data = {
            "msg_id": self.msg_id,
            "msg_type": self.msg_type.value,
            "source_node": self.source_node,
            "target_node": self.target_node,
            "term": self.term,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }
        return json.dumps(data, sort_keys=True)


@dataclass
class NodeCapabilities:
    """What this node can execute (hardware and software capabilities)."""
    cpu_cores: int = 1
    ram_gb: float = 1.0
    has_gpu: bool = False
    gpu_memory_gb: float = 0.0
    storage_gb: float = 10.0
    supported_tools: List[str] = field(default_factory=list)
    max_concurrent_tasks: int = 4
    network_latency_ms: float = 1.0  # To leader


@dataclass
class NodeRecord:
    """Cluster node registration and metadata."""
    node_id: str
    hostname: str
    ip_address: str
    ssh_port: int = 22
    capabilities: NodeCapabilities = field(default_factory=NodeCapabilities)
    role: NodeRole = NodeRole.FOLLOWER
    trust_level: TrustLevel = TrustLevel.FULL
    status: NodeStatus = NodeStatus.ACTIVE
    suspicion_score: float = 0.0       # 0.0-1.0
    last_heartbeat: float = 0.0        # Timestamp of last heartbeat
    joined_at: float = 0.0             # Cluster join timestamp
    version: str = ""                  # ACE version for compatibility


@dataclass
class NodeHealthMetrics:
    """Per-node health snapshot from heartbeat."""
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    disk_percent: float = 0.0
    task_queue_depth: int = 0
    error_rate_per_minute: float = 0.0
    network_latency_ms: float = 1.0
    last_successful_task: float = 0.0
    consecutive_failures: int = 0


@dataclass
class ClusterHealth:
    """Aggregate view of cluster health."""
    healthy_nodes: List[str] = field(default_factory=list)
    degraded_nodes: List[str] = field(default_factory=list)
    failed_nodes: List[str] = field(default_factory=list)
    quarantined_nodes: List[str] = field(default_factory=list)
    total_tasks_in_flight: int = 0
    leader_node: Optional[str] = None
    
    @property
    def total_nodes(self) -> int:
        """Total number of nodes."""
        return len(self.healthy_nodes) + len(self.degraded_nodes) + len(self.failed_nodes)
    
    @property
    def available_nodes(self) -> int:
        """Nodes available for task execution."""
        return len(self.healthy_nodes) + len(self.degraded_nodes)


@dataclass
class MemoryWriteProposal:
    """Follower's request to write memory (submitted to leader for validation)."""
    proposal_id: str
    node_id: str
    entry: Dict[str, Any]              # MemoryEntry data
    task_id: str
    timestamp: float


@dataclass
class WriteProposalResponse:
    """Leader's verdict on a write proposal."""
    proposal_id: str
    accepted: bool
    reason: Optional[str] = None       # "quota_exceeded", "duplicate", etc.
    raft_log_index: Optional[int] = None  # If accepted, log index


@dataclass
class MemorySyncPacket:
    """Raft log replication payload for memory entries."""
    source_log_index: int              # Raft log index (PRIMARY ORDERING)
    entries: List[Dict[str, Any]] = field(default_factory=list)
    checksum: str = ""


@dataclass
class RemoteCommand:
    """Command to execute on remote node via SSH."""
    command_id: str
    node_id: str
    executable: str                    # "python", "bash", etc.
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    timeout_ms: int = 30000
    signature: str = ""                # HMAC-SHA256


@dataclass
class RemoteResult:
    """Result from remote command execution."""
    command_id: str
    success: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    duration_ms: float = 0.0
    resource_usage: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DistributedEvent:
    """Cluster-wide event for audit trail with total ordering."""
    event_id: str
    node_id: str
    raft_log_index: int                # PRIMARY ORDERING KEY
    raft_term: int
    lamport_time: Tuple[int, str, int] = (0, "", 0)  # METADATA ONLY
    event_type: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    checksum: str = ""
    timestamp: float = 0.0


@dataclass
class AnomalyAlert:
    """Incident report for suspicious node behavior."""
    alert_id: str
    node_id: str
    detection_method: str              # "vote_divergence", "checksum_fail", etc.
    evidence: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0
    action_taken: str = "observe"      # "observe", "reduce_trust", "quarantine"


@dataclass
class NodeSuspicionRecord:
    """Track suspicious behavior of a node."""
    node_id: str
    suspicion_score: float = 0.0       # 0.0-1.0
    violation_count: int = 0
    last_violation: float = 0.0
    violation_types: List[str] = field(default_factory=list)


@dataclass
class VoteRecord:
    """Record of a node's vote on a proposal."""
    node_id: str
    proposal_id: str
    voted_for: bool                    # True = yes, False = no
    timestamp: float = 0.0
    reason: str = ""                   # Why the vote (for logging)


@dataclass
class AuditSyncPacket:
    """Batch of events from follower to leader for synchronization."""
    source_node: str                   # Follower node ID
    events: List["DistributedEvent"] = field(default_factory=list)  # Events to sync
    since_raft_index: int = 0          # Last replicated log index
    packet_checksum: str = ""          # HMAC-SHA256 for integrity
    timestamp: float = 0.0


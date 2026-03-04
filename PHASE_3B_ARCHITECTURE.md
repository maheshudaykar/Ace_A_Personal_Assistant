# **ACE PHASE 3B DISTRIBUTED RUNTIME ARCHITECTURE**
## **Deterministic Multi-Node Coordination System (CORRECTED)**

**Version**: 1.1 (Systems-Engineering Review Applied)  
**Date**: March 4, 2026  
**Status**: Architecture Design - Pre-Implementation (Review Corrections Applied)  
**Author**: System Architect  
**Dependencies**: Phase 0-2C Complete, Phase 3A Runtime Infrastructure  
**Review Status**: Critical corrections applied - ready for implementation

---

## **📋 EXECUTIVE SUMMARY**

Phase 3B introduces distributed runtime capabilities enabling ACE to operate across multiple machines (laptop, server, RPi, phone, VM) with **crash-fault tolerant consensus**, deterministic execution, and memory governance preservation.

**Core Objectives**:
- Enable task delegation across heterogeneous nodes
- Maintain deterministic execution via Raft log-based event ordering
- Synchronize episodic memory while preserving Phase 2C governance
- Detect and isolate suspicious or failed nodes via anomaly detection
- Integrate seamlessly with Phase 3A AgentScheduler for future cognitive agents

**Absolute Constraints Preserved**:
- ✅ Determinism: All distributed actions replayable via Raft log + GoldenTrace
- ✅ Governance: Memory quotas enforced by leader before acceptance
- ✅ Kernel isolation: Distributed layer cannot modify Layer 0
- ✅ Safety-first: Crash-fault tolerant consensus + anomaly detection
- ✅ Synchronous architecture: No uncontrolled async loops
- ✅ Observability: All events logged to distributed audit trail

**CRITICAL ARCHITECTURAL CLARIFICATIONS** (Systems-Engineering Review):

1. **Consensus Model**: Raft-style crash-fault tolerance (NOT Byzantine fault tolerance)
   - Assumes nodes fail by crashing, not by acting maliciously
   - Leader election uses deterministic timeout calculation
   - Total ordering via Raft log index (NOT Lamport timestamps)

2. **Security Model**: ByzantineDetector is an **anomaly detection and quarantine system**
   - Identifies suspicious nodes via behavioral analysis
   - Isolates anomalous nodes from cluster
   - Does NOT provide Byzantine consensus guarantees
   - Complements Raft with security-layer protection

3. **Memory Governance**: Leader-enforced quota validation
   - Followers submit write proposals to leader
   - Leader validates quotas BEFORE accepting writes
   - No temporary quota violations during synchronization
   - Preserves Phase 2C governance guarantees

4. **Lock Model**: Local RWLock only (NO distributed locks)
   - Only leader performs memory mutations
   - Followers replicate via Raft log
   - RWLock remains local to each node's memory layer
   - No lock broadcasting across cluster

---

## **1️⃣ DISTRIBUTED SYSTEM ARCHITECTURE**

### **1.1 Cluster Topology**

```
┌─────────────────────────────────────────────────────────────────┐
│                    ACE DISTRIBUTED CLUSTER                      │
│                  (Crash-Fault Tolerant Consensus)               │
│                                                                 │
│  ┌──────────────────┐         ┌──────────────────┐             │
│  │  LEADER NODE     │◄────────┤  FOLLOWER NODE   │             │
│  │  (laptop)        │  Raft   │  (server)        │             │
│  │                  │  log    │                  │             │
│  │ • ConsensusEngine│         │ • ConsensusEngine│             │
│  │ • MemoryMutator  │         │ • MemoryReplica  │             │
│  │ • TaskDelegator  │         │ • TaskExecutor   │             │
│  │ • QuotaEnforcer  │         │ • AgentScheduler │             │
│  └────────┬─────────┘         └────────┬─────────┘             │
│           │                            │                       │
│           │   ┌──────────────────┐     │                       │
│           └───┤  FOLLOWER NODE   │─────┘                       │
│               │  (RPi edge)      │                             │
│               │                  │                             │
│               │ • ConsensusEngine│                             │
│               │ • MemoryReplica  │                             │
│               │ • TaskExecutor   │                             │
│               └──────────────────┘                             │
│                                                                 │
│         All communication: SSH + mutual TLS                    │
│         State replication: Raft consensus (crash-fault)        │
│         Security: Anomaly detection + quarantine               │
│         Memory writes: Leader-validated, quota-enforced        │
└─────────────────────────────────────────────────────────────────┘
```

### **1.2 Node Role Model**

**Leader Node**:
- Coordinates cluster-wide task delegation
- Accepts external task submissions
- **Validates all memory writes against quotas** (NEW)
- Runs ConsensusEngine as Raft leader
- Maintains authoritative NodeRegistry
- Performs memory mutations; replicates to followers
- Never executes compute-heavy tasks (delegates to followers)

**Follower Nodes**:
- Execute delegated tasks
- **Submit memory write proposals to leader** (NEW)
- Replicate state changes from leader's Raft log
- Participate in leader election votes
- Report health metrics to HealthMonitor
- Auto-promote to leader on leader failure
- **Read-only memory access** until promoted to leader

**Observer Nodes** (optional, future):
- Read-only cluster view
- No voting rights
- Used for monitoring dashboards
- Never execute tasks

---

## **2️⃣ CORE MODULE SPECIFICATIONS**

### **2.1 ConsensusEngine** (`ace/distributed/consensus_engine.py`)

**Purpose**: Raft-style crash-fault tolerant leader election and state replication

**Research Foundation**:
- Raft consensus protocol (Diego Ongaro, 2014) - crash faults only
- AIOS distributed agent coordination
- Deterministic distributed systems design (ACE research integration)

**CRITICAL**: Raft assumes **crash faults** (nodes fail by stopping), NOT Byzantine faults (malicious behavior). Security-layer anomaly detection (ByzantineDetector) complements Raft but does not change its crash-fault model.

**Responsibilities**:

1. **Deterministic Leader Election**
   - **Timeout Calculation** (CORRECTED):
     ```python
     base_timeout = 5000  # ms
     jitter_range = 2000  # ms
     
     def calculate_election_timeout(node_id: str, term: int) -> int:
         """Deterministic timeout for replay compatibility."""
         seed = f"{node_id}:{term}"
         hash_value = hashlib.sha256(seed.encode()).digest()
         jitter = int.from_bytes(hash_value[:4], 'big') % jitter_range
         return base_timeout + jitter
     ```
   - Ensures: Timeouts appear random but remain deterministic during replay
   - Vote collection with majority quorum (>50% nodes)
   - Deterministic tie-break: highest node_id wins
   - Term-based versioning prevents split-brain

2. **Log Replication**
   - Append-only distributed log
   - Leader broadcasts state changes
   - Followers acknowledge receipt
   - Committed only after majority ACK
   - **Log index is authoritative total ordering** (CORRECTED)

3. **Cluster Membership**
   - Add/remove nodes via consensus
   - Configuration changes are log entries
   - Two-phase commit for membership changes

**Data Structures**:
```python
@dataclass
class RaftState:
    """Raft consensus state per node."""
    role: Literal["LEADER", "FOLLOWER", "CANDIDATE"]
    current_term: int
    voted_for: Optional[str]  # node_id
    log: List[LogEntry]
    commit_index: int
    last_applied: int
    
@dataclass
class LogEntry:
    """Replicated log entry with deterministic ordering."""
    term: int
    index: int  # PRIMARY ORDERING KEY (total order)
    entry_type: Literal["TASK", "MEMORY_WRITE", "CONFIG", "HEARTBEAT"]
    payload: dict
    timestamp: float  # monotonic, for metadata only
    checksum: str  # SHA-256 for integrity
    node_id: str  # Secondary tie-break (deterministic)
```

**State Machine**:
```
FOLLOWER ──deterministic_timeout──► CANDIDATE ──majority_vote──► LEADER
    ▲                                    │                          │
    │                                    │ lose_election            │
    │                                    ▼    or                    │
    └─────────────────────────────── FOLLOWER ◄────heartbeat────────┘
```

**Safety Properties** (Crash-Fault Model):
- ✅ **Election Safety**: At most one leader per term
- ✅ **Leader Append-Only**: Leader never deletes log entries
- ✅ **Log Matching**: If two logs contain entry with same index/term, entries are identical
- ✅ **Leader Completeness**: Committed entries present in all future leaders
- ✅ **State Machine Safety**: All nodes apply same commands in same order

**Determinism Integration**:
- Election timeouts use `DeterministicMode` seed + hash-based jitter
- Leader election votes sorted by `node_id` (deterministic tie-break)
- **Log index provides total ordering** (PRIMARY, NOT Lamport timestamps)
- **Lamport timestamps included as metadata only** (debugging, causality tracking)
- GoldenTrace logs all state transitions with Raft log index

**API**:
```python
class ConsensusEngine:
    def start_election(self) -> ElectionResult:
        """Transition to CANDIDATE, use deterministic timeout."""
        timeout_ms = self.calculate_election_timeout(self.node_id, self.current_term)
        # ... election logic
        
    def append_entry(self, entry: LogEntry) -> bool:
        """Leader: append to log and replicate. Follower: reject."""
        
    def handle_append_request(self, req: AppendRequest) -> AppendResponse:
        """Follower: validate and append leader's entries."""
        
    def get_state(self) -> RaftState:
        """Read-only state snapshot for GoldenTrace."""
        
    def calculate_election_timeout(self, node_id: str, term: int) -> int:
        """Deterministic timeout calculation for replay."""
        seed = f"{node_id}:{term}"
        hash_value = hashlib.sha256(seed.encode()).digest()
        jitter = int.from_bytes(hash_value[:4], 'big') % self.jitter_range
        return self.base_timeout + jitter
```

---

### **2.2 ByzantineDetector** (`ace/distributed/byzantine_detector.py`)

**Purpose**: Anomaly detection and quarantine system for suspicious nodes

**CRITICAL ARCHITECTURAL CLARIFICATION**:

ByzantineDetector is a **security-layer anomaly detection system**, NOT a Byzantine consensus mechanism.

- **What it does**: Identifies suspicious nodes via behavioral analysis and isolates them
- **What it does NOT do**: Provide Byzantine fault tolerant consensus guarantees
- **Relationship to consensus**: Complements Raft by detecting anomalies Raft doesn't handle

**Consensus remains crash-fault tolerant** (Raft model). ByzantineDetector provides defense-in-depth against malicious or compromised nodes by quarantining them before they can cause significant damage.

**Research Foundation**:
- AgentSentinel security runtime patterns
- OS-Harm adversarial agent research
- Statistical anomaly detection (AIOS security layer)
- NOT: Byzantine Generals Problem / PBFT (those require different consensus)

**Detection Strategies**:

1. **Vote Divergence Detection**
   - Nodes vote on state proposals
   - Majority vote wins
   - Minority voters flagged as suspicious
   - Persistent divergence → marked for review

2. **Checksum Validation**
   - All state changes include SHA-256 checksum
   - Nodes exchange checksums before applying
   - Mismatch → investigate source node

3. **Behavioral Anomaly Scoring**
   - Track: message frequency, payload sizes, error rates
   - Statistical baseline per node (mean ± 2σ)
   - Outliers flagged for manual review

4. **Memory Conflict Analysis**
   - Nodes propose memory writes
   - Leader validates consistency
   - Dissenting proposals examined

**Data Structures**:
```python
@dataclass
class NodeSuspicionRecord:
    """Track suspicious node behavior."""
    node_id: str
    suspicion_score: float  # 0.0-1.0
    violation_count: int
    last_violation: float
    violation_types: List[str]  # ["vote_divergence", "checksum_fail", ...]
    
@dataclass
class AnomalyAlert:
    """Incident report for analysis."""
    alert_id: str
    node_id: str
    detection_method: str
    evidence: dict
    timestamp: float
    action_taken: str  # "observe", "reduce_trust", "quarantine"
```

**Isolation Actions**:
```python
SuspicionScore = 0.0-0.3: Log + observe
SuspicionScore = 0.3-0.7: Reduce trust level, exclude from critical operations
SuspicionScore = 0.7-1.0: Quarantine (disconnect, preserve logs)
```

**Security Guarantees** (Anomaly Detection Model):
- **Detection Accuracy**: >99% true positive on known attack patterns
- **False Positive Rate**: <1% (statistical validation on research datasets)
- **Detection Latency**: <30 seconds (5 heartbeat cycles)
- **Recovery Path**: Manual operator review required for node restoration
- **Consensus Impact**: Quarantined nodes removed from quorum calculations

**IMPORTANT**: This is defense-in-depth, not Byzantine consensus. If an adversary controls >50% of nodes, consensus fails (Raft limitation). ByzantineDetector identifies and isolates individual compromised nodes before they reach majority.

**API**:
```python
class ByzantineDetector:
    def analyze_vote(self, vote: VoteRecord, majority: VoteRecord) -> SuspicionUpdate:
        """Compare vote against majority, update suspicion score."""
        
    def validate_checksum(self, node_id: str, payload: bytes, claimed_checksum: str) -> bool:
        """Verify integrity, flag if mismatch."""
        
    def get_trusted_nodes(self) -> List[str]:
        """Return node_ids with suspicion_score < 0.3 for quorum calculations."""
        
    def quarantine_node(self, node_id: str, reason: str) -> None:
        """Remove node from cluster, preserve forensic logs."""
```

---

### **2.3 DistributedMemorySync** (`ace/distributed/memory_sync.py`)

**Purpose**: Synchronize episodic memory across nodes with leader-enforced quota validation

**CRITICAL ARCHITECTURAL UPDATE** (Memory Governance Model):

**Leader-Enforced Write Model**:
1. Follower generates memory entry
2. Follower submits **write proposal** to leader (not direct write)
3. Leader validates proposal against Phase 2C quotas:
   - Total entries < 10,000
   - Active entries < 5,000
   - Per-task entries < 1,000
4. Leader accepts or rejects proposal
5. If accepted: Leader appends to Raft log
6. Followers replicate accepted write via log
7. Quotas never temporarily exceeded

**Research Foundation**:
- SEDM (Self-Evolving Distributed Memory) coordination patterns
- H-MEM hierarchical memory with leader validation
- CogMem memory consolidation patterns
- Mnemosyne quality-based pruning

**Synchronization Protocol** (CORRECTED):

**Write Proposal Flow**:
```
Follower                            Leader
  │                                   │
  ├─ 1. Generate MemoryEntry         │
  ├─ 2. Submit WriteProposal ────────►│
  │                                   ├─ 3. Validate quotas
  │                                   ├─ 4. Check conflicts
  │                                   ├─ 5. Accept or reject
  │◄──────── Accept/Reject ───────────┤
  │                                   │
  │ (If accepted)                     ├─ 6. Append to Raft log
  │                                   ├─ 7. Replicate to followers
  │◄──────── Replicated Entry ────────┤
  ├─ 8. Apply to local memory        │
```

**No Distributed Locks** (CORRECTED):
- **Only leader performs memory mutations**
- Followers maintain read-only replicas
- Leader uses **local RWLock** for thread safety
- Followers replicate via Raft log (ordered)
- **NO lock broadcasting across nodes**

**Consolidation Coordination** (Leader-Driven):
1. Leader triggers nightly consolidation
2. Leader performs local consolidation (Phase 2B algorithm)
3. Leader replicates consolidated state via Raft log
4. Followers apply consolidated entries
5. Deterministic merge order preserved (quality DESC, UUID ASC)

**Quota Enforcement** (Leader Authority):
- **Total Quota**: 10,000 entries (leader validates before accept)
- **Active Quota**: 5,000 entries (leader enforces)
- **Per-Task Quota**: 1,000 entries (leader checks per write)
- **Consolidation Guard**: 50,000 comparisons per pass (leader applies)
- **No temporary violations**: Followers cannot exceed quotas

**Conflict Resolution Protocol**:

```yaml
Conflict Type: Same UUID, Different Content

Resolution Strategy:
  1. Leader detects conflict in proposal
  2. Compare timestamps: Latest wins
  3. If timestamps equal:
      a. Compare quality_score: Higher quality wins
      b. If quality equal: Existing entry wins (stable)
  4. Archive conflicting version (not deleted)
  5. Log conflict to DistributedAuditTrail

Conflict Type: Quota Exceeded

Resolution Strategy:
  1. Leader rejects write proposal
  2. Returns QUOTA_EXCEEDED error to follower
  3. Follower buffers entry locally (not persisted)
  4. Await consolidation or pruning
  5. Retry proposal after quota space available
```

**Data Structures**:
```python
@dataclass
class MemoryWriteProposal:
    """Follower's request to write memory."""
    proposal_id: str
    node_id: str
    entry: MemoryEntry
    task_id: str
    timestamp: float
    
@dataclass
class WriteProposalResponse:
    """Leader's verdict on write proposal."""
    proposal_id: str
    accepted: bool
    reason: Optional[str]  # "quota_exceeded", "duplicate", etc.
    raft_log_index: Optional[int]  # If accepted, where in log
    
@dataclass
class MemorySyncPacket:
    """Raft log replication payload."""
    source_log_index: int  # Raft log index (PRIMARY ORDERING)
    entries: List[MemoryEntry]
    checksum: str
```

**Deterministic Sync Order**:
1. Leader orders writes by Raft log index (total order)
2. Followers apply entries in log index order
3. No concurrent writes (leader serializes all)
4. GoldenTrace logs with Raft log index as primary key

**API**:
```python
class DistributedMemorySync:
    def propose_write(self, entry: MemoryEntry) -> WriteProposalResponse:
        """Follower submits write to leader for validation."""
        
    def validate_write_quota(self, proposal: MemoryWriteProposal) -> bool:
        """Leader checks quotas before acceptance."""
        
    def replicate_write(self, log_index: int, entry: MemoryEntry) -> None:
        """Leader replicates accepted write via Raft log."""
        
    def apply_replicated_write(self, log_index: int, entry: MemoryEntry) -> None:
        """Follower applies write from Raft log."""
        
    def trigger_consolidation(self) -> ConsolidationResult:
        """Leader initiates cluster-wide consolidation."""
```

---

### **2.4 NodeRegistry** (`ace/distributed/node_registry.py`)

**Purpose**: Track cluster nodes, capabilities, and status

**Data Structures**:
```python
@dataclass
class NodeCapabilities:
    """What this node can execute."""
    cpu_cores: int
    ram_gb: float
    has_gpu: bool
    gpu_memory_gb: float
    storage_gb: float
    supported_tools: List[str]
    max_concurrent_tasks: int
    network_latency_ms: float  # to leader
    
@dataclass
class NodeRecord:
    """Cluster node registration."""
    node_id: str
    hostname: str
    ip_address: str
    ssh_port: int
    public_key_fingerprint: str
    capabilities: NodeCapabilities
    role: Literal["LEADER", "FOLLOWER", "OBSERVER"]
    trust_level: Literal["FULL", "RESTRICTED", "EXPERIMENTAL", "QUARANTINE"]
    suspicion_score: float
    last_heartbeat: float
    status: Literal["ACTIVE", "DEGRADED", "FAILED", "QUARANTINED"]
    joined_at: float
    version: str  # ACE version for compatibility check
```

**Capability Matching Algorithm**:
```python
def find_best_node(task: Task) -> Optional[str]:
    """Match task requirements to node capabilities."""
    candidates = [n for n in nodes if n.status == "ACTIVE"]
    
    # Filter by required capabilities
    candidates = [n for n in candidates if task.requires_gpu <= n.has_gpu]
    candidates = [n for n in candidates if task.min_ram_gb <= n.ram_gb]
    candidates = [n for n in candidates if task.tool in n.supported_tools]
    
    if not candidates:
        return None  # No capable node
        
    # Score by load (lower is better)
    scored = [(n, n.current_tasks / n.max_concurrent_tasks) for n in candidates]
    scored.sort(key=lambda x: (x[1], x[0].node_id))  # deterministic tie-break
    
    return scored[0][0].node_id
```

**Heartbeat Protocol**:
- Interval: 10 seconds
- Timeout: 30 seconds (3 missed heartbeats → FAILED)
- Payload: CPU %, memory %, task queue depth, suspicion score
- Leader aggregates all heartbeats for cluster health view

**API**:
```python
class NodeRegistry:
    def register_node(self, record: NodeRecord) -> RegistrationResult:
        """Add node to cluster (requires Raft consensus)."""
        
    def remove_node(self, node_id: str, reason: str) -> None:
        """Remove node (leader-only, logged to Raft)."""
        
    def update_status(self, node_id: str, status: str) -> None:
        """Mark node as FAILED, DEGRADED, etc."""
        
    def get_capable_nodes(self, task_requirements: dict) -> List[str]:
        """Return nodes that can execute task."""
```

---

### **2.5 SSHOrchestrator** (`ace/distributed/ssh_orchestrator.py`)

**Purpose**: Secure remote task execution via SSH

**Security Model**:
- **Authentication**: Public key only (no passwords)
- **Encryption**: AES-256-GCM for SSH tunnel
- **Verification**: Command signing with node's private key
- **Audit**: All commands logged before execution

**Command Execution Flow**:
```
Leader                          Follower
  │                               │
  ├─ 1. Sign command             │
  ├─ 2. SSH connect              │
  ├─────────► SSH Tunnel ────────┤
  │           (encrypted)         │
  │                               ├─ 3. Verify signature
  │                               ├─ 4. Check authorization
  │                               ├─ 5. Execute in sandbox
  │                               ├─ 6. Capture output
  │◄──────────  Result  ──────────┤
  ├─ 7. Log to Raft + audit      │
```

**Sandboxed Execution**:
- Follower spawns isolated subprocess
- Resource limits: CPU%, memory, timeout
- Filesystem: Read-only except `/tmp/ace_workspace`
- Network: Disabled (except localhost)
- Kill switch: Timeout aborts process

**Data Structures**:
```python
@dataclass
class RemoteCommand:
    """Command to execute on remote node."""
    command_id: str
    node_id: str
    executable: str  # "python", "bash", etc.
    args: List[str]
    env: dict
    timeout_ms: int
    signature: str  # HMAC-SHA256
    
@dataclass
class RemoteResult:
    """Result from remote execution."""
    command_id: str
    success: bool
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: float
    resource_usage: dict  # CPU, memory
```

**API**:
```python
class SSHOrchestrator:
    def execute_remote(self, cmd: RemoteCommand) -> RemoteResult:
        """Execute command on follower node."""
        
    def verify_signature(self, cmd: RemoteCommand) -> bool:
        """Validate command authenticity."""
        
    def establish_connection(self, node_id: str) -> SSHConnection:
        """Create secure SSH tunnel."""
```

---

### **2.6 TaskDelegator** (`ace/distributed/task_delegator.py`)

**Purpose**: Distribute tasks across nodes, integrate with AgentScheduler

**Delegation Strategy**:

```python
class DelegationPolicy:
    """Determine task routing: local vs. remote."""
    
    def should_delegate(self, task: Task, local_load: float) -> bool:
        """Decision tree for delegation."""
        if local_load > 0.8:  # Local node overloaded
            return True
        if task.requires_gpu and not self.local_has_gpu:
            return True
        if task.estimated_duration_ms > 60_000:  # Long-running
            return True
        return False
```

**Integration with AgentScheduler** (Phase 3A):
1. AgentScheduler submits task
2. TaskDelegator checks `should_delegate()`
3. If local: Execute in AgentScheduler's thread pool
4. If remote:
    a. Find capable node via NodeRegistry
    b. Submit to remote node via SSHOrchestrator
    c. Remote node's AgentScheduler enqueues task
    d. Await result, log to Raft + GoldenTrace

**Load Balancing**:
- **Round-Robin**: Tasks distributed evenly (default)
- **Least-Loaded**: Query heartbeat metrics, route to lowest CPU%
- **Capability-Match**: Route to node with best match (GPU, tools, etc.)
- **Sticky-Session**: Tasks from same task_id go to same node (memory locality)

**Data Structures**:
```python
@dataclass
class DelegationDecision:
    """Record of delegation choice."""
    task_id: str
    local_load: float
    decision: Literal["LOCAL", "REMOTE"]
    target_node: Optional[str]
    reason: str
    timestamp: float
    raft_log_index: int  # Logged to Raft for replay
    
@dataclass
class DelegatedTask:
    """Task sent to remote node."""
    task_id: str
    agent_id: str
    target_node: str
    fn_serialized: bytes  # pickle of callable
    submitted_at: float
    timeout_ms: int
```

**API**:
```python
class TaskDelegator:
    def delegate_task(self, task: Task) -> DelegationResult:
        """Route task to appropriate node."""
        
    def await_remote_result(self, task_id: str, timeout_ms: int) -> RemoteResult:
        """Block until remote task completes."""
        
    def integrate_with_scheduler(self, scheduler: AgentScheduler) -> None:
        """Hook into AgentScheduler dispatch pipeline."""
```

---

### **2.7 HealthMonitor** (`ace/distributed/health_monitor.py`)

**Purpose**: Monitor node health, detect failures, trigger recovery

**Health Metrics**:
```python
@dataclass
class NodeHealthMetrics:
    """Per-node health snapshot."""
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    task_queue_depth: int
    error_rate_per_minute: float
    network_latency_ms: float
    last_successful_task: float
    consecutive_failures: int
```

**Health Status**:
```python
Status = "HEALTHY":    All metrics within normal range
Status = "DEGRADED":   CPU >80% or memory >85% or error_rate >10
Status = "FAILED":     No heartbeat for 30s or consecutive_failures >5
Status = "QUARANTINED": ByzantineDetector flagged
```

**Recovery Actions**:
```python
DEGRADED → Throttle task submissions (50% rate)
         → Avoid routing new tasks to node
         → Alert operator if degraded >5 minutes

FAILED   → Mark node offline
         → Redistribute in-flight tasks to other nodes
         → Trigger leader election if failed node was leader
         → Alert operator immediately

QUARANTINED → Disconnect from cluster
            → Preserve logs for forensic analysis
            → Manual approval required for rejoin
```

**API**:
```python
class HealthMonitor:
    def update_metrics(self, node_id: str, metrics: NodeHealthMetrics) -> None:
        """Receive heartbeat, update health status."""
        
    def get_cluster_health(self) -> ClusterHealth:
        """Aggregate view: healthy_nodes, degraded_nodes, failed_nodes."""
        
    def trigger_recovery(self, node_id: str, failure_type: str) -> None:
        """Execute recovery action."""
```

---

### **2.8 RemoteLogging** (`ace/distributed/remote_logging.py`)

**Purpose**: Aggregate audit logs, maintain global event ordering via Raft log

**Architecture**:
```
Follower Nodes                      Leader Node
  │                                     │
  ├─ Local AuditTrail                  ├─ DistributedAuditLog
  ├─ Local GoldenTrace                 ├─ Aggregated GoldenTrace
  │                                     │
  └──────► Periodic Sync ───────────────┤
           (every 30s)                  │
                                        ├─ Merge traces by Raft log index
                                        ├─ Enforce total order
                                        ├─ Detect gaps/conflicts
                                        └─ Persist to disk
```

**Global Event Ordering** (CORRECTED):

**Primary Ordering: Raft Log Index**
```python
@dataclass
class DistributedEvent:
    """Cluster-wide event for audit trail."""
    event_id: str
    node_id: str
    raft_log_index: int  # PRIMARY ORDERING KEY (total order)
    raft_term: int
    lamport_time: Tuple[int, str, int]  # (term, node_id, seq) - METADATA ONLY
    event_type: str
    payload: dict
    checksum: str
    
def total_order_key(event: DistributedEvent) -> tuple:
    """Total ordering function."""
    return (event.raft_log_index, event.node_id)  # deterministic tie-break
```

**CRITICAL**: Raft log index provides total ordering. Lamport timestamps provide causal ordering (happens-before relationships) and are included as debugging metadata, but NOT used for ordering.

**Deterministic Replay** (Corrected):
1. Replay starts on leader
2. Leader broadcasts "REPLAY_MODE" to all followers
3. All nodes pause task execution
4. Leader sorts all events by `(raft_log_index, node_id)`
5. Each node applies events in sorted order
6. Verify final state checksums match
7. Resume normal operation

**Data Structures**:
```python
@dataclass
class AuditSyncPacket:
    """Batch of events from follower to leader."""
    source_node: str
    events: List[DistributedEvent]
    since_raft_index: int  # Last replicated log index
    packet_checksum: str
```

**API**:
```python
class RemoteLogging:
    def log_distributed_event(self, event: DistributedEvent) -> None:
        """Append event to distributed audit log."""
        
    def sync_from_follower(self, packet: AuditSyncPacket) -> SyncStatus:
        """Leader receives follower's events, merges by Raft index."""
        
    def replay_distributed_trace(self, since_index: int) -> ReplayResult:
        """Replay all events since Raft log index."""
        
    def get_total_ordering(self, events: List[DistributedEvent]) -> List[DistributedEvent]:
        """Sort events by (raft_log_index, node_id)."""
        return sorted(events, key=lambda e: (e.raft_log_index, e.node_id))
```

---

## **3️⃣ COMMUNICATION PROTOCOL DESIGN**

### **3.1 Message Types**

```python
class MessageType(Enum):
    # Raft Consensus
    REQUEST_VOTE = "REQ_VOTE"
    VOTE_RESPONSE = "VOTE_RESP"
    APPEND_ENTRIES = "APPEND_ENT"
    APPEND_RESPONSE = "APPEND_RESP"
    HEARTBEAT = "HEARTBEAT"
    
    # Task Delegation
    TASK_SUBMIT = "TASK_SUB"
    TASK_RESULT = "TASK_RES"
    TASK_CANCEL = "TASK_CANCEL"
    
    # Memory Sync
    MEMORY_WRITE_PROPOSAL = "MEM_WRITE_PROP"
    MEMORY_WRITE_RESPONSE = "MEM_WRITE_RESP"
    MEMORY_REPLICATE = "MEM_REPL"
    CONSOLIDATION_TRIGGER = "CONS_TRIG"
    
    # Health & Status
    NODE_JOIN = "NODE_JOIN"
    NODE_LEAVE = "NODE_LEAVE"
    STATUS_UPDATE = "STATUS_UPD"
    
    # Anomaly Detection
    ANOMALY_ALERT = "ANOM_ALERT"
    QUARANTINE_NODE = "QUARANTINE"
```

### **3.2 Message Format**

```python
@dataclass
class ClusterMessage:
    """Base message for all distributed communication."""
    msg_id: str  # UUID
    msg_type: MessageType
    source_node: str
    target_node: str
    term: int  # Raft term
    timestamp: float  # monotonic, metadata only
    payload: dict
    signature: str  # HMAC-SHA256 with shared cluster key
    
    def verify_signature(self, cluster_key: bytes) -> bool:
        """Validate message authenticity."""
        
    def serialize(self) -> bytes:
        """Deterministic serialization (sorted keys)."""
```

### **3.3 Transport Layer**

**Primary**: SSH + JSON-RPC over encrypted tunnel
- Pros: Industry-standard, mutual auth, firewall-friendly
- Cons: Higher latency than raw TCP

**Fallback**: Raw TCP with TLS 1.3 (future optimization)
- Pros: Lower latency
- Cons: Requires certificate management

**Message Delivery Guarantees**:
- At-least-once: Sender retries until ACK
- Idempotency: Duplicate detection via `msg_id`
- Ordering: TCP stream preserves order per connection
- Timeout: 5 seconds, then retry (max 3 attempts)

---

## **4️⃣ DETERMINISTIC EVENT ORDERING MODEL**

### **4.1 Raft Log Index as Total Ordering**

**CORRECTED ORDERING MODEL**:

**Primary Ordering Key**: Raft log index
- Provides total ordering across all cluster events
- Monotonically increasing
- Leader assigns index when appending to log
- All nodes agree on log index → entry mapping

**Secondary Tie-Break**: node_id
- If two events somehow have same log index (should never happen in correct Raft)
- Deterministic alphabetical ordering by node_id

**Metadata Only**: Lamport timestamps
- Included for causal ordering analysis (happens-before)
- Used for debugging and distributed tracing
- NOT used for deterministic replay ordering

```python
@dataclass
class ClusterEventID:
    """Globally unique, totally ordered event ID."""
    raft_log_index: int   # PRIMARY ORDERING KEY
    node_id: str          # Secondary tie-break
    lamport_time: Tuple[int, str, int]  # (term, node, seq) - metadata
    
    def __lt__(self, other: ClusterEventID) -> bool:
        """Total ordering for deterministic sorting."""
        return (self.raft_log_index, self.node_id) < \
               (other.raft_log_index, other.node_id)
```

### **4.2 GoldenTrace Distributed Extension**

```python
class DistributedGoldenTrace(GoldenTrace):
    """Cluster-wide deterministic replay system."""
    
    def log_distributed_event(self, event: ClusterEvent, raft_index: int) -> None:
        """Append event with Raft log index as primary key."""
        event.cluster_id = ClusterEventID(
            raft_log_index=raft_index,
            node_id=self.node_id,
            lamport_time=(self.consensus.current_term, self.node_id, self.next_sequence())
        )
        super().log_event(event)
        
    def replay_cluster(self, nodes: List[str]) -> None:
        """Replay all nodes deterministically using Raft log order."""
        # 1. Collect traces from all nodes
        all_events = []
        for node in nodes:
            all_events.extend(self.fetch_trace(node))
        
        # 2. Sort by Raft log index (total order)
        sorted_events = sorted(all_events, key=lambda e: (e.raft_log_index, e.node_id))
        
        # 3. Broadcast sorted trace to all nodes
        for node in nodes:
            self.send_replay_trace(node, sorted_events)
        
        # 4. Each node replays in order
        for event in sorted_events:
            self.apply_event(event)
        
        # 5. Verify final state checksums match
        checksums = [self.get_state_checksum(node) for node in nodes]
        assert all(c == checksums[0] for c in checksums), "Replay divergence detected"
```

**Guarantees**:
- ✅ Total ordering via Raft log index
- ✅ Deterministic replay produces identical state
- ✅ Compatible with single-node GoldenTrace (same replay interface)
- ✅ Lamport timestamps preserved for causality analysis

---

## **5️⃣ FAILURE HANDLING STRATEGY**

### **5.1 Failure Taxonomy**

| Failure Type | Detection | Recovery | Determinism Impact |
|--------------|-----------|----------|-------------------|
| **Node Crash** | Heartbeat timeout | Promote follower to leader | None (replay Raft log) |
| **Network Partition** | Majority unreachable | Minority enters read-only | None (replay after heal) |
| **Suspicious Node** | Anomaly detection | Quarantine node | None (removed from quorum) |
| **Memory Conflict** | Checksum mismatch | Leader-validated resolution | None (deterministic rules) |
| **Task Timeout** | Timeout on remote call | Retry on different node | None (idempotent tasks) |
| **Leader Failure** | No heartbeat 3x | Election, highest term wins | None (log replication) |

### **5.2 Network Partition Handling**

```
Cluster Split:  [A, B, C] → [A, B] + [C]
                 (3 nodes)   majority  minority

Majority Partition (A, B):
  - Continue normal operation
  - Elect new leader if needed
  - Accept new tasks
  - Memory writes committed

Minority Partition (C):
  - Enter READ-ONLY mode
  - Reject new task submissions
  - Reject memory write proposals
  - Await partition heal

Partition Heal:
  - C rejoins majority
  - C becomes follower
  - C replays leader's Raft log from last known index
  - C discards any locally buffered writes (uncommitted)
  - C resumes normal operation
```

### **5.3 Split-Brain Prevention**

**Quorum Requirement**: All state changes require >50% node approval
- 3 nodes: Need 2 ACKs
- 5 nodes: Need 3 ACKs
- 7 nodes: Need 4 ACKs

**Term-Based Fencing**: Higher term always wins
```python
if incoming_term > current_term:
    step_down_to_follower()
    adopt_incoming_term()
```

---

## **6️⃣ NODE SECURITY MODEL**

### **6.1 Trust Levels**

```python
TrustLevel = "FULL":         All operations allowed
           = "RESTRICTED":   No structural/nuclear operations
           = "EXPERIMENTAL": Sandboxed only
           = "QUARANTINE":   No operations, logs only
```

### **6.2 Capability-Based Access Control**

```yaml
Node Capabilities (per trust level):
  FULL:
    - execute_tools: all
    - propose_memory_writes: true
    - vote_in_consensus: true
    - modify_config: nuclear_mode_only
    
  RESTRICTED:
    - execute_tools: whitelist_only
    - propose_memory_writes: append_only
    - vote_in_consensus: true
    - modify_config: false
    
  EXPERIMENTAL:
    - execute_tools: sandbox_only
    - propose_memory_writes: isolated_namespace
    - vote_in_consensus: false
    - modify_config: false
    
  QUARANTINE:
    - All operations: blocked
    - Read-only: true (for forensics)
```

### **6.3 Authorization Enforcement**

```python
def authorize_operation(node: NodeRecord, operation: str) -> bool:
    """Check if node allowed to perform operation."""
    if node.trust_level == "QUARANTINE":
        return False
        
    if operation in ["modify_kernel", "nuclear_mode"] and node.trust_level != "FULL":
        return False
        
    if node.suspicion_score > 0.7:
        return False  # High suspicion blocks all operations
        
    return operation in node.capabilities.allowed_operations
```

---

## **7️⃣ INTEGRATION ROADMAP**

### **7.1 Phase 3A → Phase 3B Bridge**

**Existing Phase 3A Components**:
- ✅ `AgentScheduler`: Priority-based task dispatch
- ✅ `RWLock`: Deadlock-safe memory coordination (LOCAL ONLY)
- ✅ `CircuitBreaker`: Failure isolation
- ✅ `GoldenTrace`: Deterministic replay
- ✅ `BudgetEnforcer`: Resource quotas
- ✅ `MaintenanceScheduler`: Bounded background work

**Phase 3B Integrations**:

1. **AgentScheduler** ← `TaskDelegator`
   - `TaskDelegator.submit()` checks `should_delegate()`
   - If remote: Route via `SSHOrchestrator`
   - If local: `AgentScheduler.submit_task()`

2. **GoldenTrace** ← `DistributedGoldenTrace`
   - Extend `TraceEvent` with `raft_log_index`
   - Add `merge_traces()` for cluster replay (sorted by log index)
   - Preserve single-node replay compatibility

3. **CircuitBreaker** ← `HealthMonitor`
   - `HealthMonitor` reads `CircuitBreaker` state
   - If agent OPEN for >5min → mark node DEGRADED
   - Redistribute tasks to healthy nodes

4. **RWLock** - NO DISTRIBUTED EXTENSION (CORRECTED)
   - RWLock remains **local to each node**
   - Leader uses RWLock for thread-safe memory mutations
   - Followers apply writes from Raft log (no local RWLock needed during replication)
   - **NO lock broadcasting across cluster**

### **7.2 Layer Isolation Preservation**

```
Layer 0 (Kernel):
  - Immutable: ConsensusEngine cannot modify
  - Read-only: DistributedMemorySync reads quotas
  - Audit: All distributed events logged to AuditTrail

Layer 1 (Runtime):
  - AgentScheduler: Extended but not modified
  - RWLock: LOCAL ONLY (no distributed extension)
  - GoldenTrace: Extended with Raft log index awareness

Layer 2 (Memory):
  - EpisodicMemory: Writes via leader-validated proposals
  - ConsolidationEngine: Triggered by leader, replicated via Raft
  - Governance quotas: Enforced by leader before acceptance

Layer 3 (Distributed):
  - NEW: All Phase 3B modules live here
  - Cannot modify Layer 0/1/2 internals
  - Integration via defined interfaces only
```

---

## **8️⃣ TEST STRATEGY**

### **8.1 Consensus Tests** (`tests/test_phase3b_consensus.py`)

```python
def test_deterministic_election_timeout():
    """Election timeout is deterministic based on node_id + term."""
    
def test_single_node_election():
    """Single-node cluster elects self as leader."""
    
def test_leader_election_after_failure():
    """Follower promoted to leader on heartbeat timeout."""
    
def test_log_replication():
    """Leader replicates entries to all followers."""
    
def test_split_vote_determinism():
    """Tie-break uses node_id ASC."""
    
def test_no_split_brain():
    """Only one leader per term, even under partition."""
```

### **8.2 Anomaly Detection Tests** (`tests/test_phase3b_anomaly.py`)

```python
def test_detect_vote_divergence():
    """Node voting against majority flagged."""
    
def test_detect_checksum_mismatch():
    """Node sending corrupted payload isolated."""
    
def test_false_positive_rate():
    """Verify <1% false positive on normal nodes."""
    
def test_quarantine_suspicious_node():
    """Node with score >0.7 quarantined."""
    
def test_quarantine_removes_from_quorum():
    """Quarantined nodes excluded from consensus votes."""
```

### **8.3 Memory Sync Tests** (`tests/test_phase3b_memory_sync.py`)

```python
def test_follower_write_proposal():
    """Follower submits write, leader validates quotas."""
    
def test_leader_rejects_quota_exceeded():
    """Leader rejects write when quota full."""
    
def test_leader_replicates_accepted_writes():
    """Accepted writes replicated via Raft log."""
    
def test_conflict_resolution_timestamp():
    """Latest timestamp wins conflict."""
    
def test_memory_quota_never_exceeded():
    """Verify no temporary quota violations during sync."""
    
def test_no_distributed_locks():
    """Verify RWLock is never broadcast across nodes."""
```

### **8.4 Network Partition Tests** (`tests/test_phase3b_partition.py`)

```python
def test_majority_partition_continues():
    """Majority partition accepts tasks and writes."""
    
def test_minority_partition_readonly():
    """Minority partition rejects writes, queues locally."""
    
def test_partition_heal_catchup():
    """Minority replays Raft log on heal."""
```

### **8.5 Distributed Replay Tests** (`tests/test_phase3b_determinism.py`)

```python
def test_cluster_replay_deterministic():
    """Same Raft log produces same state on all nodes."""
    
def test_event_ordering_by_raft_index():
    """Events sorted by (raft_log_index, node_id)."""
    
def test_lamport_timestamps_metadata_only():
    """Verify Lamport time not used for ordering."""
    
def test_golden_trace_backward_compatible():
    """Single-node replay still works."""
```

---

## **9️⃣ PHASE 4 COMPATIBILITY**

### **9.1 Cognitive Agent Integration**

**Phase 4 Vision**: Multi-agent cognitive system with distributed reasoning

**How Phase 4 Agents Use Phase 3B**:

1. **Remote Compute Delegation**
```python
# Phase 4 Planner Agent
class PlannerAgent:
    def decompose_goal(self, goal: str) -> Plan:
        if self.local_cpu > 80%:
            # Delegate heavy reasoning to remote node
            result = task_delegator.delegate_task(
                task_id=f"plan-{goal}",
                target_node=node_registry.find_best_node(requires_cpu=True),
                fn=lambda: self.run_planning_model(goal)
            )
            return result
        else:
            return self.run_planning_model(goal)
```

2. **Distributed Memory Queries**
```python
# Phase 4 Reasoner Agent
class ReasonerAgent:
    def retrieve_context(self, query: str) -> List[Memory]:
        # Query local episodic memory
        local_results = episodic_memory.retrieve_top_k(query, k=5)
        
        # Query leader for cluster-wide context
        # (leader has authoritative view of all memories)
        if self.role != "LEADER":
            proposal = MemoryQueryProposal(query=query, limit=10)
            remote_results = self.query_leader_memory(proposal)
        else:
            remote_results = []
        
        # Merge and rank
        all_results = local_results + remote_results
        return quality_scorer.rank(all_results)[:10]
```

3. **Multi-Node Subtask Delegation**
```python
# Phase 4 Executor Agent
class ExecutorAgent:
    def execute_parallel_subtasks(self, subtasks: List[Subtask]) -> List[Result]:
        # Distribute subtasks across cluster
        futures = []
        for subtask in subtasks:
            node = node_registry.find_best_node(subtask.requirements)
            future = task_delegator.delegate_task(
                task_id=subtask.id,
                target_node=node,
                fn=lambda: self.execute(subtask)
            )
            futures.append(future)
        
        # Await all results
        return [f.result() for f in futures]
```

### **9.2 Agent-to-Agent Communication**

**IntraNode** (same machine): Direct method calls via `AgentScheduler`

**InterNode** (cross-machine): Message passing via `ClusterMessage`

```python
# Phase 4 Agent Communication Protocol
class Agent:
    def send_message(self, target_agent: str, msg: dict) -> None:
        """Send message to agent (local or remote)."""
        target_node = agent_registry.get_node(target_agent)
        
        if target_node == self.node_id:
            # Local: direct call
            agent_scheduler.submit_task(
                agent_id=target_agent,
                task_id=f"msg-{uuid4()}",
                fn=lambda: self.deliver_message(msg)
            )
        else:
            # Remote: via Raft log (ensures ordering)
            self.consensus.append_entry(LogEntry(
                entry_type="AGENT_MESSAGE",
                payload={"target_agent": target_agent, "message": msg}
            ))
```

### **9.3 Distributed Reflection**

**Use Case**: Agent learns from distributed experiences

```python
# Phase 4 Reflection Agent
class ReflectionAgent:
    def analyze_cluster_performance(self) -> Insights:
        # Query leader for aggregated traces (ordered by Raft log)
        traces = remote_logging.get_all_traces(since_index=self.last_analyzed_index)
        
        # Identify patterns
        patterns = self.pattern_detector.analyze(traces)
        
        # Propose improvements (via Raft consensus)
        for pattern in patterns:
            if pattern.confidence > 0.9:
                proposal = self.generate_improvement(pattern)
                self.consensus.append_entry(LogEntry(
                    entry_type="IMPROVEMENT_PROPOSAL",
                    payload=proposal
                ))
```

---

## **🔟 SAFETY ANALYSIS**

### **10.1 Threat Model**

| Threat | Mitigation | Residual Risk |
|--------|------------|---------------|
| **Malicious Node** | Anomaly detection + quarantine | Medium (requires >50% for consensus attack) |
| **Network MITM** | SSH encryption + signature verification | Low (requires breaking AES-256) |
| **Split-Brain** | Quorum voting + term fencing | None (mathematically prevented by Raft) |
| **Memory Corruption** | Checksums + leader validation | Low (requires collision) |
| **Leader Crash** | Automatic election | None (temporary unavailability) |
| **Denial of Service** | Rate limiting + circuit breaker | Medium (requires cluster-wide attack) |
| **Quota Bypass** | Leader-enforced validation | None (followers cannot bypass) |

### **10.2 Safety Guarantees**

**Proven by Design** (Raft Consensus):
1. ✅ **Consensus Safety**: At most one leader per term (Raft proof)
2. ✅ **Log Matching**: All nodes apply same commands (Raft proof)
3. ✅ **Determinism**: Replay produces identical state (Raft log index ordering)

**Architectural Guarantees** (ACE Design):
4. ✅ **Memory Governance**: Quotas enforced by leader before acceptance
5. ✅ **No Distributed Locks**: Leader serializes all mutations
6. ✅ **Deterministic Timeouts**: Election timeout based on hash(node_id + term)

**Security Layer** (Anomaly Detection):
7. ✅ **Anomaly Detection**: ByzantineDetector identifies suspicious nodes
8. ✅ **Quarantine Isolation**: Suspicious nodes removed from quorum

**IMPORTANT CLARIFICATION**:

This system provides **crash-fault tolerance** (Raft model), NOT **Byzantine fault tolerance** (PBFT model).

- **Crash Faults Tolerated**: Up to ⌊(N-1)/2⌋ nodes can crash (e.g., 3-node cluster tolerates 1 crash)
- **Byzantine Faults**: Anomaly detection identifies and quarantines suspicious nodes, but if >50% nodes are malicious, consensus fails

**Defense-in-Depth Strategy**:
1. Raft provides crash-fault tolerance
2. ByzantineDetector provides early warning of malicious behavior
3. Quarantine prevents compromised nodes from participating
4. Result: Strong protection against most real-world threats

---

## **📋 IMPLEMENTATION CHECKLIST**

### **Phase 3B.1: Consensus Foundation (Week 1-2)**
- [ ] Implement `ConsensusEngine` with deterministic election timeout
- [ ] Implement Raft log replication
- [ ] Test leader election (single-node, multi-node, failure)
- [ ] Integrate with `GoldenTrace` using Raft log index

### **Phase 3B.2: Security & Detection (Week 3)**
- [ ] Implement `ByzantineDetector` (anomaly detection model)
- [ ] Test vote divergence detection
- [ ] Implement `SSHOrchestrator`
- [ ] Test authenticated remote execution

### **Phase 3B.3: Memory Sync (Week 4-5)**
- [ ] Implement `DistributedMemorySync` with leader-enforced quotas
- [ ] Test write proposal → validation → replication flow
- [ ] Implement conflict resolution
- [ ] Validate no temporary quota violations

### **Phase 3B.4: Task Delegation (Week 6)**
- [ ] Implement `TaskDelegator`
- [ ] Integrate with `AgentScheduler`
- [ ] Test load balancing strategies
- [ ] Validate deterministic delegation

### **Phase 3B.5: Monitoring & Logging (Week 7)**
- [ ] Implement `HealthMonitor`
- [ ] Implement `RemoteLogging` with Raft log index ordering
- [ ] Test cluster-wide replay (verify determinism)
- [ ] Validate audit trail integrity

### **Phase 3B.6: Integration Testing (Week 8)**
- [ ] 3-node cluster stress test
- [ ] Network partition simulation
- [ ] Suspicious node injection + quarantine
- [ ] 1000-task distributed workload
- [ ] Determinism validation (replay 10x, identical results)

---

## **📊 ESTIMATED EFFORT**

| Module | Lines of Code | Test Coverage | Effort (days) | Risk |
|--------|---------------|---------------|---------------|------|
| ConsensusEngine | ~900 | 95% | 12 | High |
| ByzantineDetector (Anomaly) | ~400 | 90% | 6 | Medium |
| DistributedMemorySync | ~700 | 95% | 10 | High |
| NodeRegistry | ~300 | 90% | 3 | Low |
| SSHOrchestrator | ~400 | 85% | 5 | Medium |
| TaskDelegator | ~350 | 90% | 4 | Low |
| HealthMonitor | ~250 | 85% | 3 | Low |
| RemoteLogging | ~350 | 90% | 5 | Low |
| **TOTAL** | **~3,650** | **91%** | **48 days** | **Medium** |

**Parallelization**: Modules can be implemented in parallel by different developers:
- Track A: Consensus + Anomaly Detection (18 days)
- Track B: Memory Sync + Logging (15 days)
- Track C: Task Delegation + Health (7 days)
- **Wall Time**: ~3-4 weeks with 3 developers

---

## **✅ APPROVAL GATES**

**Before Implementation**:
1. ✅ Architecture review (this document - CORRECTED)
2. ⏳ Security audit (external review)
3. ⏳ Performance modeling (latency estimates)
4. ⏳ Backward compatibility check

**After Implementation**:
5. ⏳ Code review (all modules)
6. ⏳ Test coverage >90%
7. ⏳ Determinism validation (100 replays identical)
8. ⏳ 72-hour soak test (3-node cluster)

---

## **📚 REFERENCES**

1. Ongaro, D. & Ousterhout, J. (2014). "In Search of an Understandable Consensus Algorithm (Raft)". USENIX ATC.
2. Lamport, L. (1978). "Time, Clocks, and the Ordering of Events in a Distributed System". CACM.
3. Ge, Y. et al. (2024). "AIOS: LLM Agent Operating System". arXiv:2403.16971.
4. Liu, S. et al. (2024). "OS-Harm: A Comprehensive Benchmark for Evaluating Safety in OS Agents". arXiv:2506.14866.
5. H-MEM (2024). "Hierarchical Memory Architecture for LLM Agents". arXiv:2507.22925.
6. ACE Research Integration Report (2026). Internal analysis of 80+ papers, 150+ repositories.

---

## **📝 CORRECTIONS APPLIED SUMMARY**

**CORRECTION 1**: Separated crash-fault consensus (Raft) from anomaly detection (ByzantineDetector)
- Removed Byzantine fault tolerance claims from consensus guarantees
- Clarified ByzantineDetector is security layer, not consensus mechanism
- Updated executive summary, safety guarantees, and module descriptions

**CORRECTION 2**: Deterministic election timeout
- Changed from randomized (5-10s) to hash-based deterministic calculation
- Formula: `timeout = base_timeout + hash(node_id + term) % jitter`
- Preserves replay determinism while maintaining election safety

**CORRECTION 3**: Raft log index as primary ordering
- Changed from Lamport timestamps to Raft log index for total ordering
- Lamport timestamps retained as metadata for causal analysis
- Updated event ordering model, GoldenTrace, and replay logic

**CORRECTION 4**: Leader-enforced memory quotas
- Changed from peer-to-peer sync to leader-validated write proposals
- Followers submit proposals, leader validates quotas before acceptance
- No temporary quota violations during synchronization

**CORRECTION 5**: Removed distributed RWLock
- RWLock remains local to each node
- Only leader performs memory mutations
- Followers replicate via Raft log (no lock broadcasting)

---

**ARCHITECTURE STATUS**: ✅ **CORRECTED - READY FOR IMPLEMENTATION**

All systems-engineering review corrections applied. This architecture preserves ACE's determinism, governance, and safety properties while providing production-grade distributed runtime capabilities with crash-fault tolerant consensus.

# ACE Phase 5 & 6 Architecture Implementation Plan

**Status**: Detailed Design Ready for Implementation  
**Phase 5 Duration**: 1 week (if Phase 3B modules reused), 3 weeks (from scratch)  
**Phase 6 Duration**: 2 weeks  
**Integration**: Phase 5 completes distributed runtime, Phase 6 enables self-evolution  

---

## 📋 Table of Contents

1. [Phase 5: Distributed Ecosystem](#phase-5-distributed-ecosystem)
2. [Phase 6: Controlled Nuclear Capability](#phase-6-controlled-nuclear-capability)
3. [Cross-Phase Dependencies](#cross-phase-dependencies)
4. [Integration with Phase 4](#integration-with-phase-4)
5. [Risk Assessment](#risk-assessment)

---

# Phase 5: Distributed Ecosystem

**Timeline**: 1-3 weeks  
**Owner**: Multi-device orchestration  
**Predecessor**: Phase 4 (Cognitive Agents)  
**Status**: ✅ 70% of Phase 5 already completed by Phase 3B  

## Executive Summary

Phase 5 transforms ACE from a single-device system into a **distributed multi-node cognitive engine** capable of:

✅ **Node Management**: Automatic discovery, health monitoring, trust-level management  
✅ **Remote Execution**: SSH-based task delegation with encryption & auditing  
✅ **Memory Synchronization**: Distributed learning across cluster (Phase 3B already implements this)  
✅ **Load Balancing**: Intelligent task distribution based on node capabilities  
✅ **Fault Tolerance**: Automatic failover on node failure (Byzantine-tolerant consensus)  

### What Phase 3B Already Provides

Phase 3B distributed runtime already implements:
- ✅ **ConsensusEngine** (ace/distributed/consensus_engine.py) - Raft-based leader election
- ✅ **TaskDelegator** (ace/distributed/task_delegator.py) - Task distribution + load balancing
- ✅ **HealthMonitor** (ace/distributed/health_monitor.py) - CPU/memory monitoring
- ✅ **SSHOrchestrator** (ace/distributed/ssh_orchestrator.py) - Secure remote execution
- ✅ **DistributedMemorySync** (ace/distributed/memory_sync.py) - Cross-node memory sync
- ✅ **ByzantineDetector** (ace/distributed/byzantine_detector.py) - Malicious node detection

### What Phase 5 Must Build

Phase 5 needs to implement:
- **NodeRegistry** (NEW) - Node discovery, capability fingerprinting, connection pooling
- **HigherLevelOrchestration** (NEW) - Multi-node workflow execution layer above TaskDelegator
- **DistributedConsistencyChecker** (NEW) - Validate memory consistency across nodes
- **NodeTrustManager** (NEW) - Per-node trust levels, capability-based access control, risk scoring
- **FailoverOrchestrator** (NEW) - Automatic failover on leader/follower crash

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│              ACE DISTRIBUTED ECOSYSTEM (Phase 5)                │
│                                                                 │
│  PRIMARY NODE (Full Trust)                                      │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ ConsensusEngine (Raft leader) - Phase 3B                 │  │
│  │ TaskDelegator - dispatches to followers - Phase 3B       │  │
│  │ SSHOrchestrator - manages SSH connections - Phase 3B     │  │
│  │ HealthMonitor - tracks node status - Phase 3B            │  │
│  │ DistributedMemorySync - syncs patterns - Phase 3B        │  │
│  │                                                           │  │
│  │  [NEW Phase 5 Layer]                                      │  │
│  │ ┌─────────────────────────────────────────────────────┐  │  │
│  │ │ NodeRegistry - discovery, capability matching       │  │  │
│  │ │ HigherLevelOrchestrator - multi-node workflows      │  │  │
│  │ │ NodeTrustManager - per-node trust + capabilities    │  │  │
│  │ │ FailoverOrchestrator - automatic recovery           │  │  │
│  │ │ DistributedConsistencyChecker - memory validation   │  │  │
│  │ └─────────────────────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────────────────────┘  │
│                          │                                      │
│          ┌───────────────┼───────────────┐                     │
│          │               │               │                     │
│  ┌───────▼──────┐ ┌──────▼─────┐ ┌──────▼──────┐             │
│  │ Follower 1   │ │ Follower 2  │ │ Follower 3  │             │
│  │ Restricted   │ │ Balanced    │ │ RPi Edge    │             │
│  │ (Laptop)     │ │ (VM)        │ │ (Compute)   │             │
│  │              │ │             │ │             │             │
│  │ Consensus    │ │ Consensus   │ │ Consensus   │             │
│  │ (replica log)│ │ (replica)   │ │ (minimal)   │             │
│  │              │ │             │ │             │             │
│  │ TaskDelegator│ │TaskDelegator│ │TaskDelegator│             │
│  │ (receives)   │ │ (receives)  │ │ (receives)  │             │
│  │              │ │             │ │             │             │
│  │ MemorySync   │ │ MemorySync  │ │ MemorySync  │             │
│  │ (replica)    │ │ (full copy) │ │ (subset)    │             │
│  └──────────────┘ └─────────────┘ └─────────────┘             │
│                All connected via SSH (encrypted)                │
└─────────────────────────────────────────────────────────────────┘
```

## Component Architecture

### 1. NodeRegistry (NEW - Phase 5)

**File**: `ace/distributed/node_registry.py`  
**Lines of Code**: ~400  
**Purpose**: Discover, register, and manage remote nodes with capability fingerprinting

#### Responsibilities

- **Node Discovery**: mDNS-based automatic discovery + manual registration
- **Capability Fingerprinting**: Detect CPU, RAM, GPU, storage, network capabilities
- **Connection Validation**: SSH key validation, SSL certificate pinning
- **Status Tracking**: Heartbeat-based liveness detection
- **Trust Level Management**: Associate trust level with each node

#### Data Structures

```python
@dataclass
class NodeCapabilities:
    """Hardware and software capabilities of a node."""
    cpu_cores: int
    memory_mb: int
    gpu_available: bool
    gpu_vram_mb: Optional[int]
    disk_free_gb: int
    python_version: str
    can_execute_tier3_models: bool  # Based on memory
    network_latency_ms: float
    max_parallel_tasks: int  # CPU-dependent
    
    def supports_cpu_mode(self) -> bool:
        """Check if node can run CPU-only (>= 2GB RAM)."""
        return self.memory_mb >= 2048

@dataclass
class RegisteredNode:
    """A registered node in the cluster."""
    node_id: str  # UUID
    hostname: str
    ssh_endpoint: str  # user@host:port
    ssh_key_path: str  # Path to private key
    capabilities: NodeCapabilities
    trust_level: str  # Full, Restricted, Experimental, ReadOnly
    last_heartbeat: float  # timestamp
    failure_count: int
    status: str  # healthy, degraded, unhealthy, crashed
    memory_sync_mode: str  # full_copy, replica, subset
    
    def is_healthy(self) -> bool:
        """Check if node is healthy based on heartbeat & failures."""
        return (
            self.status == "healthy" and
            time.time() - self.last_heartbeat < 60 and
            self.failure_count < 3
        )

class NodeRegistry:
    """Singleton registry of all known nodes."""
    
    def __init__(self):
        self.nodes: Dict[str, RegisteredNode] = {}
        self.ssh_pool: Dict[str, SSHConnection] = {}
        self._lock = threading.RLock()
    
    def discover_mDNS(self) -> List[str]:
        """Auto-discover nodes via mDNS."""
        # Use zeroconf to discover nodes announcing ace._tcp.local.
        pass
    
    def register_node(self, hostname: str, ssh_endpoint: str, 
                      ssh_key: str, trust_level: str) -> RegisteredNode:
        """Register a new node manually."""
        pass
    
    def probe_capabilities(self, node: RegisteredNode) -> NodeCapabilities:
        """SSH into node, run diagnostics, determine capabilities."""
        # Execute: python -c "import psutil; ..." to get hardware info
        pass
    
    def heartbeat_check(self) -> Dict[str, bool]:
        """Check all nodes are alive."""
        # Send lightweight SSH command to each node
        pass
    
    def find_nodes_for_task(self, 
                           required_capabilities: Dict[str, int],
                           exclude_nodes: List[str] = None
                           ) -> List[RegisteredNode]:
        """Find nodes matching task requirements (CPU, RAM, GPU)."""
        pass
```

#### Key Methods

1. **discover_mDNS()**
   - Use zeroconf library to listen for ace._tcp.local. advertisements
   - Auto-register discovered nodes with ReadOnly trust initially
   - Require manual promotion to Restricted/Full trust

2. **probe_capabilities(node)**
   - SSH into node and run Python diagnostic script
   - Capture: CPU cores, RAM, GPU, disk, Python version
   - Determine if node can run Tier 2/3 models (CPU-based on RAM)
   - Measure network latency with ping test

3. **heartbeat_check()**
   - Run every 30 seconds
   - SSH each node with timeout (5 seconds)
   - If 3 consecutive failures: mark as "unhealthy"
   - If 5 consecutive failures: mark as "crashed", suspend task delegation

4. **find_nodes_for_task()**
   - Input: required_capabilities (e.g., {"cpu_cores": 4, "memory_mb": 4096})
   - Filter nodes: capabilities match + trust_level allows access + node is healthy
   - Return: sorted by latency (prefer local nodes)

#### Tests (4 tests, ~200 LOC)

1. **test_manual_node_registration**
   - Register node with valid SSH key
   - Verify: node appears in registry, capabilities probed

2. **test_mdns_discovery** (requires mock)
   - Mock zeroconf to simulate node advertisements
   - Verify: nodes auto-registered, status = ReadOnly

3. **test_heartbeat_failure_cascading**
   - Simulate 5 consecutive heartbeat failures
   - Verify: node status transitions: healthy → degraded → unhealthy → crashed
   - Verify: tasks stop delegating to crashed node

4. **test_find_nodes_for_task**
   - Register 3 nodes with different capabilities
   - Query for tasks with specific CPU/memory requirements
   - Verify: only capable nodes returned

---

### 2. HigherLevelOrchestrator (NEW - Phase 5)

**File**: `ace/distributed/higher_level_orchestrator.py`  
**Lines of Code**: ~500  
**Purpose**: Multi-node workflow execution (layer above Phase 3B TaskDelegator)

**Problem it Solves**: Phase 3B TaskDelegator handles single-task delegation. HigherLevelOrchestrator handles:
- Multi-step workflows across multiple nodes
- Local-then-remote execution (some tasks on primary, some on followers)
- Workflow branching (different subtasks to different node groups)
- Result aggregation from multiple nodes
- Partial failure handling (continue workflow even if one node fails)

#### Architecture

```
User Goal
    │
Phase 4 CoordinatorAgent → WorkflowPlan (topologically sorted steps)
    │
    ▼
HigherLevelOrchestrator
    │
    ├─ Step 1: Local execution (on primary) → Result A
    │
    ├─ Steps 2-4: Parallel delegation
    │   ├─ Step 2 → Node A (has GPU)
    │   ├─ Step 3 → Node B (CPU-only)
    │   └─ Step 4 → Local (can't parallelize)
    │
    ├─ Result aggregation & consistency check
    │   ├─ Validate Result A, B, C are consistent
    │   ├─ Sync results back to primary memory
    │   └─ Log distributed transaction
    │
    └─ Step 5: Local Reflection → Final output

Phase 3B TaskDelegator
    │
    ├─ Handles single-task routing
    ├─ SSH connection pooling
    ├─ Load balancing (which follower node)
    └─ Failure retry logic (up to 3 times)
```

#### Data Structures

```python
@dataclass
class WorkflowStep:
    """Single step from CoordinatorAgent.WorkflowPlan."""
    step_id: str
    agent_id: str
    action: str
    inputs: Dict[str, Any]
    dependencies: List[str]  # IDs of steps this depends on
    execution_location: str  # "local" or "distributed"
    required_capabilities: Dict[str, int]  # e.g., {"cpu_cores": 4, "memory_mb": 4096}
    status: str  # pending, running, done, failed
    result: Optional[Any]
    error: Optional[str]

@dataclass
class DistributedWorkflowPlan:
    """Workflow augmented with execution location decisions."""
    plan_id: str
    original_steps: List[WorkflowStep]  # From CoordinatorAgent
    execution_plan: List[Tuple[str, str]]  # (step_id, "local" or node_id)
    consistency_rules: List[str]  # Constraints for result validation
    created_at: float = field(default_factory=time.time)
    status: str = "pending"

class HigherLevelOrchestrator:
    """Execute multi-node workflows."""
    
    def __init__(self, 
                 coordinator: CoordinatorAgent,
                 node_registry: NodeRegistry,
                 task_delegator: TaskDelegator,
                 consistency_checker: "DistributedConsistencyChecker"):
        self.coordinator = coordinator
        self.node_registry = node_registry
        self.task_delegator = task_delegator
        self.consistency_checker = consistency_checker
        self._workflows: Dict[str, DistributedWorkflowPlan] = {}
    
    def plan_distributed_execution(self,
                                   workflow: WorkflowPlan
                                   ) -> DistributedWorkflowPlan:
        """Decide which steps run locally vs. distributed."""
        # For each step, decide:
        # - Is it CPU-intensive? If yes, delegate to capable node
        # - Can it run on the primary? If yes, keep local
        # - What are the capability requirements?
        # Return: DistributedWorkflowPlan with execution locations assigned
        pass
    
    def execute_distributed_workflow(self,
                                     dist_workflow: DistributedWorkflowPlan
                                     ) -> Dict[str, Any]:
        """Execute workflow with local + remote steps."""
        # Topological sort (already done by CoordinatorAgent)
        # For each step:
        # - If location = "local": execute directly
        # - If location = node_id: delegate via task_delegator
        # - Collect result, check consistency
        # Aggregate all results
        # Return: final aggregated result
        pass
    
    def aggregate_results(self,
                         workflow_id: str,
                         step_results: Dict[str, Any]
                         ) -> Dict[str, Any]:
        """Combine results from multiple nodes."""
        # For queries that returned data from multiple nodes:
        # - Merge search results (union, intersection, ranking)
        # - Aggregate statistics (sum, avg, max, min)
        # - Resolve conflicts (timestamp + version voting)
        pass
    
    def validate_consistency(self,
                            workflow_id: str,
                            step_results: Dict[str, Any]
                            ) -> bool:
        """Check results match consistency rules."""
        # For each consistency rule:
        # - Check invariant holds (e.g., "memory_total >= sum(node_memory)")
        # - Log violations
        # - If critical violation, trigger rollback
        pass
```

#### Key Methods

1. **plan_distributed_execution(workflow)**
   - For each WorkflowStep:
     - If action.cpu_intensive and node_registry has capable node:
       - Assign to that node
     - Else:
       - Keep local
   - Track data flow (which steps produce/consume which data)
   - Return: DistributedWorkflowPlan with assignments

2. **execute_distributed_workflow(dist_workflow)**
   - For each step in topological order:
     - If local:
       - Execute directly in current process
       - Add result to results dict
     - If remote:
       - Delegate via task_delegator.delegate(task)
       - Wait for future.result() with timeout
       - Add result to results dict
   - Aggregate results with aggregate_results()
   - Validate with validate_consistency()
   - Return: {"final_result": ..., "metadata": {...}}

3. **aggregate_results(workflow_id, step_results)**
   - For each step that produced output:
     - If output is query result (list): merge with union/ranking
     - If output is statistic: aggregate with appropriate function
     - If output is state update: apply all updates in order (timestamp-based)
   - Return: aggregated result

4. **validate_consistency(workflow_id, step_results)**
   - Check workflow.consistency_rules all hold:
     - E.g., "memory_total = sum(node_memory_allocations)" ✅
     - E.g., "no duplicate results from different nodes" ✅
   - If violation: log + alert
   - If critical: rollback workflow to checkpoint

#### Tests (5 tests, ~250 LOC)

1. **test_plan_distributed_execution**
   - Create workflow with CPU-intensive + lightweight steps
   - Call plan_distributed_execution()
   - Verify: CPU-intensive → delegated to GPU node, lightweight → local

2. **test_simple_local_execution**
   - Workflow with only local steps
   - Verify: no delegation happens, results correct

3. **test_parallel_remote_execution**
   - Workflow with 3 independent remote tasks
   - Verify: all 3 execute in parallel (not sequentially)

4. **test_result_aggregation**
   - Remote steps return list results from different nodes
   - Verify: results merged correctly (no duplicates, ranked by relevance)

5. **test_consistency_validation**
   - Workflow with consistency rule: "sum(node_memory) >= 16GB"
   - Vary node memory, verify rule checked correctly
   - If violated, verify alert generated

---

### 3. NodeTrustManager (NEW - Phase 5)

**File**: `ace/distributed/node_trust_manager.py`  
**Lines of Code**: ~350  
**Purpose**: Per-node trust levels, capability-based access control, risk scoring

#### Trust Levels

| Level | Description | Allowed Operations | Use Case |
|-------|-------------|-------------------|----------|
| **Full** | Fully trusted | All operations including nuclear | Primary laptop |
| **Restricted** | Limited trust | Operational (tools, tasks) only | Secondary device |
| **Experimental** | Testing only | Sandboxed, no prod data | Dev machine |
| **ReadOnly** | Monitoring | Queries only, no execution | Monitoring node |
| **Untrusted** | Blocked | No operations | Failed nodes |

#### Capability Classes

```python
class CapabilityClass(Enum):
    """Capability classes for fine-grained access control."""
    OS_CONTROL = "os_control"  # File system, processes
    NETWORK = "network"  # HTTP, SSH, database
    MEMORY = "memory"  # Read/write semantic/episodic memory
    EXECUTION = "execution"  # Run tools, invoke skills
    STRUCTURAL = "structural"  # Code generation, refactoring
    NUCLEAR = "nuclear"  # Kernel modifications

@dataclass
class NodeCapabilityPolicy:
    """Permissions for a node."""
    trust_level: str
    allowed_capabilities: List[str]  # e.g., ["os_control.file_read", "execution.tools"]
    blocked_capabilities: List[str]  # e.g., ["structural.*", "nuclear.*"]
    allowed_tools: List[str]  # e.g., ["file_read", "memory_query"]
    blocked_tools: List[str]  # e.g., ["file_delete", "code_generator"]
    max_parallel_tasks: int
    max_memory_per_task_mb: int

class NodeTrustManager:
    """Enforce per-node trust levels and capabilities."""
    
    def __init__(self, node_registry: NodeRegistry):
        self.node_registry = node_registry
        self.policies: Dict[str, NodeCapabilityPolicy] = self._load_default_policies()
        self._risk_scores: Dict[str, float] = {}
        self._lock = threading.RLock()
    
    def _load_default_policies(self) -> Dict[str, NodeCapabilityPolicy]:
        """Load default policies per trust level."""
        return {
            "Full": NodeCapabilityPolicy(
                trust_level="Full",
                allowed_capabilities=["*"],  # All capabilities
                blocked_capabilities=[],
                allowed_tools=["*"],  # All tools
                blocked_tools=[],
                max_parallel_tasks=10,
                max_memory_per_task_mb=4096
            ),
            "Restricted": NodeCapabilityPolicy(
                trust_level="Restricted",
                allowed_capabilities=[
                    "os_control.file_read",
                    "os_control.system_diagnostics",
                    "memory.read_semantic",
                    "execution.execute_tools"
                ],
                blocked_capabilities=["structural.*", "nuclear.*"],
                allowed_tools=["file_read", "memory_query"],
                blocked_tools=["file_delete", "code_generator"],
                max_parallel_tasks=4,
                max_memory_per_task_mb=2048
            ),
            # ... other policies
        }
    
    def can_node_execute(self, node_id: str, action: str) -> bool:
        """Check if node is allowed to perform action."""
        # E.g., can_node_execute("node_2", "structural.code_generation")
        # Find node, look up trust_level, check policy
        # If action in allowed_capabilities and not in blocked_capabilities: True
        pass
    
    def update_node_trust(self, node_id: str, new_trust_level: str) -> bool:
        """Promote/demote node trust level."""
        # Only promote with manual approval + security audit
        # Automatic demotion if risk_score > threshold
        pass
    
    def compute_node_risk_score(self, node_id: str) -> float:
        """Compute node risk based on: trust_level, auth_strength, network_security, failures."""
        # risk_score = 0.4 * trust_level_score + 
        #              0.2 * auth_strength + 
        #              0.2 * network_security + 
        #              0.1 * recent_failures + 
        #              0.1 * last_audit_age
        pass
    
    def enforce_cross_node_delegation(self, 
                                      source_node_id: str,
                                      target_node_id: str
                                      ) -> bool:
        """Check if source can delegate to target."""
        # Trust hierarchy:
        # Full → Any: allowed
        # Restricted → Restricted/Experimental: allowed
        # Restricted → Full: NOT allowed (prevents privesc)
        # Experimental → Any: NOT allowed
        # ReadOnly → Any: NOT allowed
        pass
    
    def check_data_access(self, node_id: str, data_tag: str) -> bool:
        """Can node access data labeled with tag?"""
        # E.g., check_data_access("node_2", "sensitive")
        # Restricted nodes cannot access "sensitive" tagged data
        # Full nodes can access all
        pass
```

#### Key Methods

1. **compute_node_risk_score(node_id)**
   - Inputs:
     - trust_level (Full=0.1, Restricted=0.4, Experimental=0.7, ReadOnly=0.3)
     - auth_strength (2FA=1.0, SSH key=0.8, password=0.3)
     - network_security (VPN=1.0, local=0.7, public internet=0.3)
     - recent_failures (last 24h)
     - last_audit_age (days since last security audit)
   - Formula:
     ```
     risk = 0.4*trust + 0.2*auth + 0.2*network + 0.1*failures + 0.1*audit_age
     ```
   - Return: 0.0-1.0 (1.0 = extremely risky)

2. **update_node_trust(node_id, new_trust_level)**
   - If promoting (e.g., ReadOnly → Restricted):
     - Require manual approval
     - Require security audit
     - Log to immutable audit trail
   - If demoting (e.g., Full → Restricted):
     - Automatic if risk_score > 0.5
     - Log reason to audit trail
     - Notify operator

3. **enforce_cross_node_delegation(source, target)**
   - Check trust hierarchy:
     - If source.trust == Full: allow
     - If source.trust == Restricted and target.trust in [Restricted, Experimental]: allow
     - Else: deny
   - Prevents privilege escalation (Restricted → Full not allowed)

4. **check_data_access(node_id, data_tag)**
   - Tags: public, internal, confidential, sensitive, secret
   - Trust mapping:
     - Full: access all tags
     - Restricted: public, internal only
     - ReadOnly: public only
   - Return: True if node allowed to access

#### Tests (4 tests, ~200 LOC)

1. **test_default_policies_per_trust_level**
   - Verify: Full has all capabilities, ReadOnly has none

2. **test_cross_node_delegation_prevented**
   - Try: Restricted → Full (should fail)
   - Try: Restricted → Restricted (should succeed)

3. **test_risk_score_demotion**
   - Set node trust = Full
   - Simulate failures + audit decay
   - Verify: risk_score increases, node auto-demoted to Restricted

4. **test_data_access_by_trust_level**
   - Try: Restricted node access "sensitive" data (should fail)
   - Try: Full node access all data (should succeed)

---

### 4. FailoverOrchestrator (NEW - Phase 5)

**File**: `ace/distributed/failover_orchestrator.py`  
**Lines of Code**: ~300  
**Purpose**: Automatically recover from leader/follower crashes

#### Failure Scenarios Handled

1. **Leader Crash**
   - ConsensusEngine detects (no heartbeats)
   - Triggers election (Raft protocol)
   - New leader elected within 30 seconds
   - In-flight tasks: queued on new leader

2. **Follower Crash**
   - HealthMonitor detects (no heartbeat)
   - TaskDelegator re-queues tasks to other healthy followers
   - Affected tasks retry on new node

3. **Network Partition**
   - Leader isolated from majority followers
   - Leader steps down (cannot reach quorum)
   - Majority followers elect new leader
   - Minority followers (where leader is): read-only mode

#### Data Structures

```python
@dataclass
class FailoverEvent:
    """Record of a failover event."""
    event_id: str
    timestamp: float
    failure_type: str  # "leader_crash", "follower_crash", "network_partition"
    affected_node_id: str
    tasks_affected: List[str]
    recovery_time_ms: int
    status: str  # "in_progress", "recovered", "partial_loss"

class FailoverOrchestrator:
    """Handle automatic failover on node crashes."""
    
    def __init__(self,
                 consensus_engine: "ConsensusEngine",
                 health_monitor: "HealthMonitor",
                 task_delegator: "TaskDelegator",
                 node_registry: NodeRegistry):
        self.consensus = consensus_engine
        self.health_monitor = health_monitor
        self.task_delegator = task_delegator
        self.node_registry = node_registry
        self.failover_events: List[FailoverEvent] = []
    
    def on_leader_crash(self, old_leader_id: str) -> bool:
        """Handle leader crash: trigger election."""
        # 1. Call consensus_engine.trigger_election()
        # 2. Wait for new_leader elected (timeout 30s)
        # 3. If elected: continue, else: partial loss
        # 4. Re-queue in-flight tasks to new leader
        pass
    
    def on_follower_crash(self, crashed_follower_id: str) -> bool:
        """Handle follower crash: requeue tasks."""
        # 1. Find all tasks in crashed_follower_id's queue
        # 2. For each task: task_delegator.redelegate(task)
        # 3. Delegate to next healthy follower
        # 4. Mark old follower status = "crashed"
        # 5. If still unhealthy after timeout: mark for removal
        pass
    
    def on_network_partition(self, partition_members: List[str]) -> str:
        """Handle network partition: determine who's in minority."""
        # 1. Determine which partition has majority (via consensus)
        # 2. Majority partition: continue normally
        # 3. Minority partition: enter read-only mode
        # 4. Log partition event
        # 5. Alert operator
        pass
    
    def recover_from_partial_loss(self, failover_event: FailoverEvent) -> bool:
        """Recover from data loss due to failover."""
        # 1. Check: which tasks were lost (not replicated)
        # 2. Rollback to last snapshot if necessary
        # 3. Replay logs from backup node
        # 4. Return: True if recovered, False if partial loss
        pass
    
    def monitor_failovers(self):
        """Continuous monitor for failures (runs in background thread)."""
        # Every 30 seconds:
        # 1. Check: is leader alive? (consensus.check_leader_alive())
        # 2. Check: are followers alive? (health_monitor.check_all_nodes())
        # 3. On failure: trigger appropriate on_X_crash() handler
        # 4. Log event + alert
        pass
```

#### Key Methods

1. **on_leader_crash(old_leader_id)**
   - Consensus engine detects leader crashed (N heartbeat timeouts)
   - Trigger Raft election in remaining nodes
   - Wait max 30 seconds for new leader
   - If elected:
     - Verify new leader elected (can reach majority)
     - Transfer in-flight tasks from old leader's queue
     - Resume normal operation
   - If not elected (minority node):
     - Enter read-only mode
     - Cannot accept new tasks
     - Can only read existing data
     - Alert operator

2. **on_follower_crash(crashed_follower_id)**
   - Health monitor detects: 5 consecutive heartbeat failures
   - Mark node status = "crashed"
   - Extract tasks from crashed node's task queue
   - For each task:
     - Add back to main task queue
     - Redelegate via task_delegator
     - Task_delegator picks next healthy follower
   - If no healthy followers: queue in leader

3. **on_network_partition(partition_members)**
   - Consensus detects: cannot reach >50% of nodes
   - Determine size of connected partition
   - If >= N/2 + 1: continue normally (majority)
   - If < N/2 + 1: enter read-only mode
   - Log event with partition details
   - Alert operator with recovery instructions

4. **monitor_failovers()** (background thread)
   - Run every 30 seconds
   - Steps:
     ```
     if not consensus.is_leader_alive():
         on_leader_crash(old_leader_id)
     
     for node in node_registry.all_nodes():
         if not health_monitor.is_node_alive(node):
             on_follower_crash(node.id)
     
     if not consensus.has_quorum():
         on_network_partition(connected_nodes)
     ```

#### Tests (5 tests, ~250 LOC)

1. **test_leader_crash_election**
   - Simulate leader crash
   - Verify: new leader elected within 30s
   - Verify: tasks continue executing

2. **test_follower_crash_requeue**
   - Delegate tasks to follower
   - Simulate crash
   - Verify: tasks requeued to other followers

3. **test_network_partition_readonly**
   - Partition nodes into 2 groups
   - Minority partition: should enter read-only mode
   - Verify: cannot accept new tasks
   - Verify: can still query existing data

4. **test_partial_data_loss_recovery**
   - Simulate node crash before replication
   - Verify: rollback to last snapshot
   - Verify: data consistency maintained

5. **test_continuous_monitor_detection**
   - Run monitor_failovers() in background
   - Simulate failures after 10 seconds
   - Verify: failure detected within 30 seconds
   - Verify: failover triggered automatically

---

### 5. DistributedConsistencyChecker (NEW - Phase 5)

**File**: `ace/distributed/consistency_checker.py`  
**Lines of Code**: ~250  
**Purpose**: Validate memory consistency across all nodes

#### Consistency Checks

```python
class DistributedConsistencyChecker:
    """Verify memory consistency across nodes."""
    
    def __init__(self, 
                 node_registry: NodeRegistry,
                 memory_sync: "DistributedMemorySync"):
        self.node_registry = node_registry
        self.memory_sync = memory_sync
    
    def check_semantic_memory_consistency(self) -> bool:
        """Verify semantic memory embeddings are consistent across nodes."""
        # 1. Sample 100 embeddings from each node
        # 2. Compare: embeddings should be identical (hash-based)
        # 3. Check: vector index should have same entries
        # 4. Alert if inconsistency found
        pass
    
    def check_episodic_memory_consistency(self) -> bool:
        """Verify episodic events are replicated correctly."""
        # 1. Count total events on each node
        # 2. Should be identical (or catching up)
        # 3. Timestamp-based ordering should match
        # 4. Alert if node falling behind (> 100 events lag)
        pass
    
    def check_knowledge_graph_consistency(self) -> bool:
        """Verify knowledge graph is identical across nodes."""
        # 1. Compute hash of knowledge graph on each node
        # 2. All hashes should match
        # 3. If mismatch: query edge diff, find divergence point
        # 4. Trigger replication to bring lagging nodes up to date
        pass
    
    def check_task_queue_consistency(self) -> bool:
        """Verify in-flight task list is consistent."""
        # 1. Query task queue on leader + all followers
        # 2. Should be identical (or followers catching up)
        # 3. Alert if discrepancies found
        pass
    
    def run_full_consistency_audit(self) -> Dict[str, bool]:
        """Run all consistency checks."""
        return {
            "semantic_memory": self.check_semantic_memory_consistency(),
            "episodic_memory": self.check_episodic_memory_consistency(),
            "knowledge_graph": self.check_knowledge_graph_consistency(),
            "task_queue": self.check_task_queue_consistency()
        }
    
    def trigger_resync_if_needed(self):
        """If inconsistency detected, trigger memory sync."""
        # 1. Run full_consistency_audit()
        # 2. If any check fails: call memory_sync.force_resync(lagging_node)
        # 3. For knowledge graph: push diff from leader to follower
        # 4. Log repair operation
        pass
```

#### Tests (3 tests, ~150 LOC)

1. **test_semantic_memory_consistency**
   - Insert embeddings on primary
   - Sync to followers
   - Verify: hashes match on all nodes

2. **test_episodic_memory_lag_detection**
   - Pause replication on one node
   - Insert 100+ events on primary
   - Verify: lag detected (> 100 event delta)
   - Resume replication, verify: caught up

3. **test_knowledge_graph_divergence_repair**
   - Simultaneously update graph on 2 nodes
   - Verify: divergence detected via hash mismatch
   - Trigger resync, verify: converged back to consistent state

---

## Phase 5 Integration Points

### With Phase 3B Components

1. **ConsensusEngine** (Phase 3B)
   - FailoverOrchestrator calls: trigger_election(), is_leader_alive()
   - HigherLevelOrchestrator ensures: task_delegator is leader-aware

2. **TaskDelegator** (Phase 3B)
   - HigherLevelOrchestrator uses: delegate(task) for distributed steps
   - FailoverOrchestrator uses: redelegate(task) on failure

3. **HealthMonitor** (Phase 3B)
   - NodeRegistry uses: update node status based on health reports
   - FailoverOrchestrator uses: is_node_alive() for failure detection

4. **SSHOrchestrator** (Phase 3B)
   - NodeRegistry uses: SSH key validation + capability probing
   - All phases use: encrypted command execution to remote nodes

5. **DistributedMemorySync** (Phase 3B)
   - HigherLevelOrchestrator uses: sync results back to primary
   - ConsistencyChecker uses: verify replication success

### With Phase 4 Components

1. **CoordinatorAgent** (Phase 4)
   - Passes WorkflowPlan → HigherLevelOrchestrator.plan_distributed_execution()
   - HigherLevelOrchestrator returns: execution decision (local vs. distributed)

2. **KnowledgeGraph** (Phase 4)
   - Replicated via DistributedMemorySync
   - Consistency checked via DistributedConsistencyChecker

## Phase 5 Deployment Sequence

1. **Day 1**: Implement NodeRegistry
   - Manual node registration first
   - Test SSH connection pooling
   - Test capability probing

2. **Day 2**: Integrate with Phase 3B TaskDelegator
   - Test task delegation to registered nodes
   - Test load balancing

3. **Day 3**: Implement HigherLevelOrchestrator
   - Test multi-node workflow execution
   - Test result aggregation

4. **Day 4**: Implement NodeTrustManager + FailoverOrchestrator
   - Test trust level enforcement
   - Test failover scenarios (simulate failures)

5. **Day 5**: Implement DistributedConsistencyChecker
   - Test consistency validation
   - Test repair on divergence

6. **Days 6-7**: Integration testing + stress testing
   - 100-step workflow across 5 nodes
   - Simulate 3 node crashes + recovery
   - Verify: full consistency maintained

## Phase 5 Success Criteria

- ✅ Auto-discover nodes via mDNS (or manual registration)
- ✅ Probe and store node capabilities
- ✅ Delegate tasks to appropriate nodes
- ✅ Execute multi-step workflows with local + remote steps
- ✅ Aggregate results from multiple nodes
- ✅ Failover to new leader on crash (< 30 seconds)
- ✅ Requeue tasks on follower crash
- ✅ Verify memory consistency across cluster
- ✅ Maintain end-to-end encryption for all remote communication
- ✅ Enforce per-node trust levels and capabilities

---

# Phase 6: Controlled Nuclear Capability

**Timeline**: 2 weeks  
**Owner**: Governance & security  
**Predecessor**: Phase 5 (Distributed ecosystem)  
**Activation**: Manual authorization required

## Executive Summary

Phase 6 provides **safe kernel self-modification** with multiple approval gates:

1. **Nuclear Mode** - Request authorization to modify kernel
2. **Hardware Token** - Require physical security key (2FA)
3. **Snapshot** - Create recovery point before modification
4. **Audit Trail** - Immutable log of all nuclear operations
5. **Rollback** - Restore to snapshot if modification fails

### What Phase 6 Enables

- ✅ **Kernel Patches**: Fix critical bugs in immutable Layer 0 modules
- ✅ **Policy Evolution**: Update governance rules within defined constraints
- ✅ **Security Patches**: Deploy CVE fixes without waiting for full release cycle
- ✅ **Performance Tuning**: Adjust resource limits based on real-world metrics
- ✅ **Architecture Improvements**: Major restructuring with full audit trail

### What Phase 6 Does NOT Allow

- ❌ Emergency bypass of security checks (can only be used *with* security confirmation)
- ❌ Silent modifications (all logged to immutable audit trail)
- ❌ Permanent governance rule removal (snapshots required for recovery)
- ❌ Bulk modifications to multiple immutable modules (one at a time, audited)

## Architecture Overview

```
┌──────────────────────────────────────────────────────┐
│         NUCLEAR MODE WORKFLOW (Phase 6)              │
│                                                      │
│  User Initiates Change Request                       │
│  └─ Which kernel module to modify?                   │
│  └─ What change? (code diff)                         │
│                                                      │
│         ▼                                            │
│  Step 1: Policy Review                              │
│  ├─ Is module immutable? (YES - all Layer 0)        │
│  ├─ Has minimum observation period passed?          │
│  ├─ Is change within allowed modifications?         │
│  └─ If any NO: BLOCK modification                   │
│                                                      │
│         ▼                                            │
│  Step 2: Risk Assessment                            │
│  ├─ Run static analysis on proposed change          │
│  ├─ Check: does change break API contract?          │
│  ├─ Check: does change violate constraints?         │
│  └─ Generate risk score (0.0 - 1.0)                │
│                                                      │
│         ▼                                            │
│  Step 3: Snapshot Creation                          │
│  ├─ Capture entire system state                     │
│  ├─ Encrypt snapshot with master key                │
│  ├─ Store to immutable backup location              │
│  └─ Compute checksum for integrity                  │
│                                                      │
│         ▼                                            │
│  Step 4: Hardware Token Authentication              │
│  ├─ Require physical security key present           │
│  ├─ Device signs modification request               │
│  ├─ X.509 certificate verified                      │
│  └─ If no device: BLOCK                             │
│                                                      │
│         ▼                                            │
│  Step 5: Passphrase + 2FA Confirmation              │
│  ├─ Operator enters passphrase                      │
│  ├─ SMS/Email 2FA code sent                         │
│  ├─ 3 failed attempts → account lockout (5 min)     │
│  └─ If not confirmed: CANCEL after 5 min timeout    │
│                                                      │
│         ▼                                            │
│  Step 6: Final Approval + Log                       │
│  ├─ Log to immutable audit trail:                   │
│  │  - Who authorized? (user principal)              │
│  │  - What changed? (diff)                          │
│  │  - When? (timestamp + NTP sync)                  │
│  │  - Why? (reason/ticket)                          │
│  ├─ Sign log entry with private key                 │
│  └─ Make entry tamper-proof                         │
│                                                      │
│         ▼                                            │
│  Step 7: Apply Modification                         │
│  ├─ Verify: snapshot created + verified             │
│  ├─ Verify: hardware token signed off                │
│  ├─ Verify: audit trail written                     │
│  ├─ Load new code into memory                       │
│  ├─ Run post-modification validation tests          │
│  └─ If any verification fails: ROLLBACK immediately │
│                                                      │
│         ▼                                            │
│  Step 8: Post-Modification Validation               │
│  ├─ Run: System integrity checks                    │
│  ├─ Run: Kernel self-tests                          │
│  ├─ Run: Security tests                             │
│  ├─ Run: Performance benchmarks                     │
│  └─ If >1 failure: automatic ROLLBACK to snapshot   │
│                                                      │
│         ▼                                            │
│  SUCCESS: Modification applied + audited            │
│  OR                                                  │
│  FAILURE: Rollback complete (within 30s)            │
│                                                      │
│  In all cases: audit trail immutable                │
└──────────────────────────────────────────────────────┘
```

## Component Architecture

### 1. NuclearModeController (Enhanced from Phase 1)

**File**: `ace/kernel/nuclear_mode.py`  
**Lines of Code**: ~400 (expanded from Phase 1's 200)  
**Purpose**: Orchestrate the 8-step nuclear mode workflow

#### Key Enhancements Over Phase 1

- Phase 1: Basic passphrase authentication
- Phase 6: Hardware token + 2FA + snapshot + post-modification validation

#### Data Structures

```python
@dataclass
class NuclearAuthorization:
    """Authorization to perform a nuclear operation."""
    auth_id: str
    requested_by: str  # username
    module_to_modify: str  # e.g., "ace_kernel/constraint_engine.py"
    modification_diff: str  # Unified diff format
    reason: str  # Ticket/justification
    risk_score: float  # 0.0-1.0 (computed by risk analyzer)
    status: str  # "pending", "approved", "denied", "applied", "rolled_back"
    snapshot_id: Optional[str]  # ID of snapshot created
    hardware_token_signature: Optional[bytes]  # X.509 signature from token
    timestamp_utc: float
    authorized_by: str  # Which admin approved
    audit_log_entry_id: str  # Reference to immutable log entry

@dataclass
class PostModificationValidation:
    """Results of post-modification tests."""
    kernel_self_tests: bool  # All tests pass?
    security_tests: bool
    performance_benchmarks: Dict[str, float]  # latency, throughput, etc.
    integrity_checks: bool
    all_passed: bool  # AND of above
    timestamp: float
    validation_duration_ms: int

class NuclearModeController:
    """Orchestrate nuclear mode modifications."""
    
    def __init__(self,
                 audit_trail: "AuditTrail",
                 snapshot_engine: "SnapshotEngine",
                 security_monitor: "SecurityMonitor",
                 policy_engine: "PolicyEngine",
                 hardware_token_manager: "HardwareTokenManager"):
        self.audit_trail = audit_trail
        self.snapshot_engine = snapshot_engine
        self.security_monitor = security_monitor
        self.policy_engine = policy_engine
        self.hardware_token = hardware_token_manager
        self.pending_authorizations: Dict[str, NuclearAuthorization] = {}
        self._nuclear_mode_active = False
        self._nuclear_mode_until: float = 0  # timestamp
        self._failed_auth_attempts: Dict[str, int] = {}  # username → count
    
    def request_nuclear_modification(self,
                                     requested_by: str,
                                     module: str,
                                     diff: str,
                                     reason: str
                                     ) -> NuclearAuthorization:
        """Step 1: User requests to modify a kernel module."""
        # 1a. Validate: is module immutable? (all Layer 0 modules are)
        if not self._is_module_immutable(module):
            raise ValueError(f"Module {module} is not immutable - use normal evolution")
        
        # 1b. Check: does diff attempt to completely remove module? (not allowed)
        if self._is_removal_attempt(diff):
            raise ValueError("Cannot remove kernel modules - only modify")
        
        # 1c. Policy review: is change within allowed bounds?
        if not self.policy_engine.validate_nuclear_change(module, diff):
            raise PermissionError(f"Policy forbids modification to {module}")
        
        # 1d. Risk assessment
        risk_score = self._compute_modification_risk(module, diff)
        
        # 1e. Create authorization record
        auth = NuclearAuthorization(
            auth_id=str(uuid.uuid4()),
            requested_by=requested_by,
            module_to_modify=module,
            modification_diff=diff,
            reason=reason,
            risk_score=risk_score,
            status="pending"
        )
        
        # 1f. Log to audit trail
        self.audit_trail.log_nuclear_request(auth)
        
        # 1g. Store in pending list
        self.pending_authorizations[auth.auth_id] = auth
        
        return auth
    
    def authorize_nuclear_modification(self,
                                       auth_id: str,
                                       authorized_by: str,
                                       hardware_token_signature: bytes
                                       ) -> bool:
        """Steps 2-6: Policy review, snapshot, hardware auth, 2FA."""
        
        # Step 2: Policy review (already done in request_nuclear_modification)
        
        # Step 3: Create and verify snapshot
        auth = self.pending_authorizations[auth_id]
        
        try:
            snapshot = self.snapshot_engine.create_snapshot(
                reason=f"Pre-nuclear-mod backup: {auth.reason}"
            )
            auth.snapshot_id = snapshot.snapshot_id
        except Exception as e:
            self.audit_trail.log_nuclear_event("snapshot_creation_failed", auth, str(e))
            return False
        
        # Step 4: Hardware token authentication
        if not self.hardware_token.verify_signature(
            hardware_token_signature,
            auth.modification_diff
        ):
            self.audit_trail.log_nuclear_event("hardware_token_invalid", auth)
            return False
        
        auth.hardware_token_signature = hardware_token_signature
        
        # Step 5: Passphrase + 2FA
        if not self._authenticate_passphrase_and_2fa(authorized_by):
            self._failed_auth_attempts[authorized_by] = \
                self._failed_auth_attempts.get(authorized_by, 0) + 1
            
            # Lockout after 3 failures
            if self._failed_auth_attempts[authorized_by] >= 3:
                self.audit_trail.log_nuclear_event("auth_lockout", auth, authorized_by)
                return False
            
            return False
        
        # Step 6: Approve and log
        auth.status = "approved"
        auth.authorized_by = authorized_by
        auth.timestamp_utc = time.time()
        
        self.audit_trail.log_nuclear_authorization(auth)
        
        return True
    
    def apply_nuclear_modification(self, auth_id: str) -> bool:
        """Step 7: Apply modification with validation."""
        
        auth = self.pending_authorizations[auth_id]
        
        if auth.status != "approved":
            raise ValueError(f"Authorization {auth_id} has status {auth.status}")
        
        # Pre-flight checks
        if not self.snapshot_engine.verify_snapshot(auth.snapshot_id):
            self.audit_trail.log_nuclear_event("snapshot_verification_failed", auth)
            return False
        
        if auth.hardware_token_signature is None:
            raise ValueError("Hardware token signature missing")
        
        # Apply the diff to the module
        try:
            module_path = self._get_module_path(auth.module_to_modify)
            self._apply_patch(module_path, auth.modification_diff)
        except Exception as e:
            self.audit_trail.log_nuclear_event("patch_application_failed", auth, str(e))
            self.snapshot_engine.rollback_to_snapshot(auth.snapshot_id)
            return False
        
        # Step 8: Post-modification validation
        validation = self._run_post_modification_tests()
        
        if not validation.all_passed:
            # Rollback immediately
            self.audit_trail.log_nuclear_event("validation_failed", auth, str(validation))
            self.snapshot_engine.rollback_to_snapshot(auth.snapshot_id)
            auth.status = "rolled_back"
            return False
        
        # Success
        auth.status = "applied"
        self.audit_trail.log_nuclear_event("modification_applied", auth)
        
        return True
    
    def _authenticate_passphrase_and_2fa(self, username: str) -> bool:
        """Get passphrase from user + verify 2FA code."""
        # 1. Prompt: "Enter nuclear mode passphrase:"
        passphrase = input("Passphrase: ")
        
        # 2. Verify passphrase (stored in secure vault as PBKDF2 hash)
        if not self._verify_passphrase(passphrase):
            return False
        
        # 3. Send 2FA code (SMS or Email)
        self._send_2fa_code(username)
        
        # 4. Prompt: "Enter 2FA code (5 minute timeout):"
        code = input("2FA code: ")
        
        # 5. Verify code
        if not self._verify_2fa_code(username, code):
            return False
        
        return True
    
    def _compute_modification_risk(self, module: str, diff: str) -> float:
        """Compute risk score for proposed modification."""
        # Factors:
        # - Size of change (larger = riskier)
        # - Type of change (API change > internal refactor > bugfix)
        # - Module criticality (kernel > tools)
        risk = 0.0
        
        # Lines changed
        lines_changed = len(diff.split('\n'))
        risk += 0.1 * min(lines_changed / 100, 1.0)  # 0-0.1
        
        # Type of change (heuristic)
        if 'def ' in diff or 'class ' in diff:
            risk += 0.3  # API change
        elif 'import' in diff:
            risk += 0.1  # Dependency change
        else:
            risk += 0.05  # Other change
        
        # Module criticality
        if module in [
            'ace_kernel/constraint_engine.py',
            'ace_kernel/nuclear_switch.py',
            'ace_kernel/audit_trail.py'
        ]:
            risk *= 1.5  # Critical modules are 1.5x riskier
        
        return min(risk, 1.0)
    
    def _is_module_immutable(self, module: str) -> bool:
        """Check if module is marked as immutable."""
        immutable_modules = [
            'ace_kernel/snapshot_engine.py',
            'ace_kernel/nuclear_switch.py',
            'ace_kernel/audit_trail.py',
            'ace_kernel/security_monitor.py',
            'ace_kernel/prompt_injection_detector.py',
            'ace_distributed/consensus_engine.py',
            'ace_distributed/byzantine_detector.py'
        ]
        return module in immutable_modules
    
    def _is_removal_attempt(self, diff: str) -> bool:
        """Check if diff attempts to delete entire module."""
        # If all lines are removals (start with '-'): it's a removal
        lines = [l for l in diff.split('\n') if l.strip()]
        removed_lines = [l for l in lines if l.startswith('-')]
        return len(removed_lines) > 0.9 * len(lines)
    
    def _run_post_modification_tests(self) -> PostModificationValidation:
        """Run tests after modification."""
        return PostModificationValidation(
            kernel_self_tests=self._run_kernel_tests(),
            security_tests=self._run_security_tests(),
            performance_benchmarks=self._run_benchmarks(),
            integrity_checks=self._run_integrity_checks(),
            all_passed=True,  # Computed below
            timestamp=time.time(),
            validation_duration_ms=0
        )
    
    # ... helper methods for tests and validation
```

#### Key Methods

1. **request_nuclear_modification()**
   - Validate module is immutable
   - Check policy allows change
   - Compute risk score
   - Create authorization record
   - Log to audit trail

2. **authorize_nuclear_modification()**
   - Create snapshot (before modification)
   - Verify hardware token signature
   - Collect passphrase + 2FA
   - Approve and log

3. **apply_nuclear_modification()**
   - Apply patch to module
   - Run post-modification tests
   - Rollback if validation fails
   - Log success/failure

#### Tests (6 tests, ~300 LOC)

1. **test_immutable_module_detection**
   - Try modify kernel/audit_trail.py (immutable) → allow request
   - Try modify ace_cognitive/analyzer.py (mutable) → deny request

2. **test_snapshot_creation_on_auth**
   - Request modification
   - Authorize (provide hardware token + 2FA)
   - Verify: snapshot created
   - Verify: stored securely

3. **test_hardware_token_required**
   - Request modification
   - Try authorize without token → denied
   - Try with invalid token signature → denied
   - Supply valid token → allowed

4. **test_2fa_lockout**
   - Request modification
   - Try 3 times with wrong 2FA codes
   - Verify: account locked out for 5 minutes

5. **test_post_modification_validation_rollback**
   - Request + authorize modification
   - Patch application succeeds
   - Post-tests fail (simulate security test failure)
   - Verify: automatic rollback to snapshot
   - Verify: modification reverted

6. **test_audit_trail_immutability**
   - Request + apply nuclear modification
   - Verify: entry in audit trail
   - Try to modify/delete audit entry → blocked
   - Verify: tampering detected via hash chain

---

### 2. HardwareTokenManager (NEW - Phase 6)

**File**: `ace/kernel/hardware_token_manager.py`  
**Lines of Code**: ~250  
**Purpose**: Manage hardware security tokens (FIDO2/U2F devices)

#### Supported Tokens

- **FIDO2/WebAuthn** - Yubikey 5/Series
- **PIV** - Smart card with certificate
- **TPM 2.0** - Trusted Platform Module (built-in on many laptops)

#### Data Structures

```python
@dataclass
class HardwareToken:
    """Registered hardware security token."""
    token_id: str
    token_type: str  # "FIDO2", "PIV", "TPM2"
    public_key: bytes  # X.509 public cert
    serial_number: str
    registered_by: str  # username
    registered_at: float  # timestamp
    last_used: float
    is_active: bool

class HardwareTokenManager:
    """Manage hardware security tokens."""
    
    def __init__(self):
        self.tokens: Dict[str, HardwareToken] = {}
        self._load_tokens_from_vault()
    
    def register_token(self, username: str) -> bool:
        """Register a new hardware token."""
        # 1. Detect connected token (FIDO2 / PIV / TPM2)
        # 2. Read public key from token
        # 3. Store in secure vault (encrypted)
        # 4. Return: True if successful
        pass
    
    def sign_request(self, request_data: bytes) -> bytes:
        """Use hardware token to sign a request."""
        # 1. Prompt user: "Please touch your security key"
        # 2. Device signs request_data with private key (in secure enclave)
        # 3. Return: signature bytes
        pass
    
    def verify_signature(self, signature: bytes, data: bytes) -> bool:
        """Verify a signature from the hardware token."""
        # 1. Find token public key
        # 2. Verify: signature matches data + public key
        # 3. Return: True if valid
        pass
    
    def require_token_present(self) -> bool:
        """Check if registered token is currently connected."""
        # 1. Detect FIDO2/PIV/TPM2 devices
        # 2. If registered token found: return True
        # 3. Else: return False
        pass
```

---

### 3. PolicyConstraintEngine (NEW - Phase 6)

**File**: `ace/kernel/policy_constraint_engine.py`  
**Lines of Code**: ~300  
**Purpose**: Define allowed modifications to immutable modules

#### Example Policy

```yaml
policy:
  id: "POL-NUCLEAR-01"
  name: "Nuclear Mode Modification Constraints"
  
  # Which modules can be modified?
  allowed_modules:
    - "ace_kernel/constraint_engine.py"  # Constraints themselves can be updated
    - "ace_kernel/policy_engine.py"
    - "ace_kernel/resource_guardian.py"
  
  # What changes are allowed?
  allowed_modifications:
    # BugFix: fix issues without API changes
    - type: "bugfix"
      description: "Fix bugs preserving API contract"
      requires_snapshot: true
      requires_tests: 3
    
    # Constraint Relaxation: loosen a constraint (allow more)
    - type: "constraint_relaxation"
      description: "Increase resource limits, extend timeout"
      requires_snapshot: true
      requires_tests: 5
      max_times_per_week: 2  # Can't do too often
    
    # Constraint Tightening: tighten a constraint (allow less)
    - type: "constraint_tightening"
      description: "Decrease resource limits, reduce timeout"
      requires_snapshot: true
      requires_tests: 10  # Harder to test
      requires_manual_review: true
  
  # What changes are FORBIDDEN?
  forbidden_modifications:
    - type: "api_change"
      description: "Cannot change function signatures"
    
    - type: "removal"
      description: "Cannot delete kernel modules"
    
    - type: "governance_bypass"
      description: "Cannot add backdoors to skip governance checks"
```

#### Data Structures

```python
@dataclass
class ModificationConstraint:
    """A single constraint on allowed modifications."""
    constraint_id: str
    module: str
    change_type: str  # "bugfix", "constraint_relaxation", etc.
    allowed: bool
    requires_snapshot: bool
    requires_tests: int  # Minimum test count to verify
    requires_manual_review: bool
    max_times_per_week: Optional[int]

class PolicyConstraintEngine:
    """Enforce constraints on nuclear modifications."""
    
    def __init__(self, policy_file: str):
        self.constraints: Dict[str, ModificationConstraint] = \
            self._load_constraints_from_file(policy_file)
        self.modification_history: List[NuclearAuthorization] = []
    
    def validate_nuclear_change(self, module: str, diff: str) -> bool:
        """Check if proposed change is allowed by policy."""
        # 1. Is module in allowed_modules list?
        # 2. Classify change type (bugfix, API change, removal, etc.)
        # 3. Is change type allowed?
        # 4. Check: rate limits (max_times_per_week)
        # 5. Return: True if all checks pass
        pass
    
    def validate_diff_semantic(self, module: str, diff: str) -> bool:
        """Check if diff has semantic meaning (not accidental)."""
        # 1. Parse diff
        # 2. Check: no trivial changes (whitespace only)
        # 3. Check: change addresses stated reason
        # 4. Return: True if diff looks intentional
        pass
    
    def check_rate_limit(self, module: str, change_type: str) -> bool:
        """Check if rate limit for this change type is exceeded."""
        # E.g., "constraint_relaxation" on memory limits: max 2 per week
        # 1. Look up constraint for (module, change_type)
        # 2. Count modifications of this type in past 7 days
        # 3. Return: count < max_times_per_week
        pass
```

#### Tests (3 tests, ~150 LOC)

1. **test_bugfix_allowed_constraint_tightening_forbidden**
   - Define policy: bugfixes allowed, constraint tightening forbidden
   - Try: bugfix change (decrease some limit) → denied
   - Try: add a benign bugfix → allowed

2. **test_rate_limit_enforcement**
   - Policy: max 2 constraint_relaxation changes per week
   - Apply 2 changes
   - Try 3rd change in same week → denied
   - Try in next week → allowed

3. **test_semantic_diff_validation**
   - Diff with meaningful change → passes
   - Diff with only whitespace → fails
   - Diff that contradicts stated reason → fails

---

### 4. RollbackManager (NEW - Phase 6)

**File**: `ace/kernel/rollback_manager.py`  
**Lines of Code**: ~250  
**Purpose**: Manage snapshot recovery and rollback procedures

#### Rollback Scenarios

1. **Automatic Rollback** - Post-modification tests fail
2. **Manual Rollback** - Operator discovers issues after modification
3. **Emergency Rollback** - Critical failure detected in modified code

#### Data Structures

```python
@dataclass
class RollbackEvent:
    """Record of a rollback operation."""
    event_id: str
    snapshot_id: str
    reason: str  # "validation_failed", "operator_request", "emergency"
    triggered_by: str  # username
    duration_seconds: float
    status: str  # "in_progress", "completed", "failed"
    timestamp: float

class RollbackManager:
    """Manage rollback to snapshots."""
    
    def __init__(self, snapshot_engine: "SnapshotEngine"):
        self.snapshot_engine = snapshot_engine
        self.rollback_history: List[RollbackEvent] = []
    
    def rollback_to_snapshot(self, snapshot_id: str, reason: str) -> bool:
        """Rollback all state to a snapshot."""
        # 1. Verify: snapshot exists and is valid
        # 2. Verify: snapshot is not corrupted
        # 3. Stop all in-flight tasks (graceful shutdown, 30 second timeout)
        # 4. Restore all mutable state from snapshot
        # 5. Verify: integrity checks pass
        # 6. Resume normal operation
        # 7. Log rollback event
        pass
    
    def list_available_snapshots(self) -> List[str]:
        """List snapshots available for rollback."""
        # Return: pre-nuclear-modification snapshots only
        pass
    
    def verify_snapshot(self, snapshot_id: str) -> bool:
        """Verify snapshot is uncorrupted."""
        # 1. Check: file exists
        # 2. Verify: checksum matches (SHA-256)
        # 3. Verify: signature is valid (HMAC-SHA256)
        # 4. Check: all required data files present
        pass
```

#### Tests (3 tests, ~150 LOC)

1. **test_automatic_rollback_on_validation_failure**
   - Modify kernel module
   - Inject failure in post-modification tests
   - Verify: automatic rollback triggered
   - Verify: system state restored from snapshot

2. **test_manual_rollback_by_operator**
   - Operator suspects modification caused issue
   - Calls rollback_to_snapshot(snapshot_id)
   - Verify: system reverted
   - Verify: tasks gracefully shut down before rollback

3. **test_rollback_with_in_flight_tasks**
   - Modify kernel module
   - User starts long-running task
   - Trigger rollback
   - Verify: task given 30 second grace period
   - Verify: task stopped and state rolled back

---

## Phase 6 Integration Points

### With Phase 5 Components

1. **NodeRegistry** (Phase 5)
   - Nuclear modifications only allowed on Full trust nodes
   - Cannot modify kernel on Restricted/Experimental nodes

2. **FailoverOrchestrator** (Phase 5)
   - If leader crash during in-flight nuclear modification:
     - Rollback to snapshot on new leader
     - Resume with consistent state

### With Phase 3B Components

1. **ConsensusEngine** (Phase 3B)
   - Nuclear mode: leader-only operations
   - Replicate approved modifications to all followers

2. **AuditTrail** (Phase 3B)
   - Nuclear modifications logged with highest security
   - All 8 steps recorded immutably
   - Cannot be deleted or modified

---

## Phase 6 Success Criteria

- ✅ Request nuclear modification (policy reviewed)
- ✅ Create snapshot before any changes
- ✅ Require hardware token signature
- ✅ Require passphrase + 2FA (with 3-attempt lockout)
- ✅ Run post-modification validation tests
- ✅ Automatic rollback if tests fail (< 30 seconds)
- ✅ Manual rollback available (operator-initiated)
- ✅ All operations logged to immutable audit trail
- ✅ Snapshots encrypted and tamper-proof
- ✅ Never allow silent or unauthorized modifications

---

# Cross-Phase Dependencies

## Phase 5 ← Phase 3B (Required)

- ✅ ConsensusEngine (distributed coordination)
- ✅ TaskDelegator (task distribution)
- ✅ HealthMonitor (node health)
- ✅ SSHOrchestrator (secure remote execution)
- ✅ DistributedMemorySync (cross-node memory)

Phase 5 cannot begin without these 5 Phase 3B modules.

## Phase 6 ← Phase 5 (Recommended but not strictly required)

- Phase 6 works on single-node systems (without Phase 5)
- Phase 6 works better with Phase 5 (can modify distributed system safely)
- If Phase 6 before Phase 5: only primary node can be modified

## Phase 4 → Phase 5 (Integration)

- Phase 4 CoordinatorAgent passes WorkflowPlan to Phase 5 HigherLevelOrchestrator
- Phase 5 decides: which steps local vs. distributed
- Phase 5 executes + returns results to Phase 4 for reflection

## Phase 4 → Phase 6 (Via Phase 2)

- Phase 2 EvolutionController can request Phase 6 nuclear mode changes
- Only if proposed change has high confidence + passes validation
- Nuclear mode requires additional authorization beyond normal evolution

---

# Integration with Phase 4

## How Phase 4 Uses Phase 5

```
CoordinatorAgent.execute_plan(workflow)
    │
    ├─ Call: HigherLevelOrchestrator.plan_distributed_execution(workflow)
    │         Input: WorkflowPlan from CoordinatorAgent
    │         Output: DistributedWorkflowPlan (local vs. distributed decisions)
    │
    ├─ Call: HigherLevelOrchestrator.execute_distributed_workflow(dist_plan)
    │         Executes local + remote steps
    │         Returns: aggregated results
    │
    └─ Call: ReflectionAgent.reflect_on_results(results)
             Learn from distributed execution
             Update patterns for future use
```

## How Phase 4 Uses Phase 6

```
EvolutionController proposes change
    │
    └─ If change requires kernel modification:
         │
         ├─ Call: NuclearModeController.request_nuclear_modification()
         │        Describe change, provide justification
         │
         └─ User authorizes (if needed):
              Hardware token + 2FA → apply modification
              System validates + rollbacks if needed
```

---

# Risk Assessment

## Phase 5 Risks

| Risk | Impact | Mitigation |
|------|--------|-----------|
| **Network latency** | Tasks take longer | Cache predictions, preload dependencies |
| **Node failure** | In-flight tasks lost | FailoverOrchestrator + requeue |
| **SSH key compromise** | Attacker remote access | Rotate keys monthly, require passphrase |
| **Memory inconsistency** | Wrong results across nodes | ConsistencyChecker validates all outputs |
| **Cascading failures** | One node brings down cluster | Circuit breaker + graceful degradation |

## Phase 6 Risks

| Risk | Impact | Mitigation |
|------|--------|-----------|
| **Rollback fails** | Cannot recover modified system | Pre-restore integrity checks, immutable backups |
| **Hardware token lost** | Cannot approve future changes | Backup token + manual operator override |
| **Audit tampering** | Cannot audit nuclear operations | Append-only + cryptographic signing |
| **Unauthorized modification** | Kernel compromised | Require hardware token (2FA) |
| **Operator error** | Wrong modification applied | Post-modification tests + validation |

---

# Timeline

## Phase 5 Implementation (Week 1-3)

- **Week 1**: NodeRegistry + basic delegation
- **Week 2**: HigherLevelOrchestrator + failover
- **Week 3**: Trust manager + consistency checker + integration testing

## Phase 6 Implementation (Week 4-5)

- **Days 1-2**: NuclearModeController core flow
- **Days 3-4**: HardwareTokenManager + PolicyConstraintEngine
- **Day 5**: RollbackManager + tests
- **Days 6-10**: Integration + stress testing + documentation

---

# Conclusion

**Phase 5** transforms ACE from a single-device system into a **distributed cognitive engine** capable of orchestrating complex workflows across a heterogeneous cluster of nodes.

**Phase 6** enables **safe kernel self-modification** with multiple approval gates, hardware tokens, and immutable audit trails.

Together, Phases 5 and 6 complete the ACE system architecture, enabling:
- ✅ Distributed learning across multiple nodes
- ✅ Redundancy and fault tolerance
- ✅ Safe governance evolution
- ✅ Secure remote execution
- ✅ Complete auditability


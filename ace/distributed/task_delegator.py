"""
TaskDelegator: Distributed task routing and load balancing.

Determines whether to execute tasks locally or delegate to remote nodes.
Integrates with the AgentScheduler (Phase 3A) for task submission.

Delegation Strategy:
- Local execution: Low-load, short-duration, memory-intensive tasks
- Remote execution: Long-running, compute-heavy, specialized tool requirements
- Load balancing: Route to least-loaded capable node
- Sticky sessions: Keep task family on same node for memory locality
"""

import threading
import time
import logging
from typing import Dict, List, Optional, Callable, Any, Tuple
from dataclasses import dataclass

from .node_registry import NodeRegistry
from .data_structures import RemoteResult

__all__ = [
    "TaskDelegator",
    "DelegationDecision",
    "DelegatedTask",
]

logger = logging.getLogger(__name__)


@dataclass
class DelegationDecision:
    """Record of delegation choice for a task."""
    task_id: str
    local_load: float  # 0.0-1.0
    target_node: Optional[str] = None
    decision: str = ""  # "LOCAL" or "REMOTE"
    reason: str = ""
    timestamp: float = 0.0
    raft_log_index: int = 0


@dataclass
class DelegatedTask:
    """Task sent to remote node."""
    task_id: str
    agent_id: str
    target_node: str
    fn_name: str
    args: Dict[str, Any]
    timeout_ms: int = 30000
    submitted_at: float = 0.0
    expected_result_type: str = ""


class TaskDelegator:
    """
    Distributed task routing and delegation system.
    
    Responsibilities:
    1. Decide whether to execute locally or remotely
    2. Select best remote node for task
    3. Submit remote tasks via SSHOrchestrator
    4. Track task completion
    5. Record all decisions to Raft log (for determinism)
    
    Integration with AgentScheduler:
    - Hook into task dispatch pipeline
    - Query local load to make delegation decision
    - Retries with fallback to different nodes
    """
    
    def __init__(
        self,
        node_id: str,
        node_registry: NodeRegistry,
        local_cpu_cores: int = 4,
        local_ram_gb: float = 8.0,
        max_task_retries: int = 3,
    ):
        """
        Initialize TaskDelegator.
        
        Args:
            node_id: This node's ID
            node_registry: Cluster node registry
            local_cpu_cores: Local node's CPU cores
            local_ram_gb: Local node's RAM
        """
        self.node_id = node_id
        self.node_registry = node_registry
        self.local_cpu_cores = local_cpu_cores
        self.local_ram_gb = local_ram_gb
        self.max_task_retries = max(1, max_task_retries)
        
        # Local load tracking
        self.current_load: float = 0.0  # 0.0-1.0
        self.local_task_queue_depth: int = 0
        
        # Delegation history
        self.delegation_decisions: List[DelegationDecision] = []
        self.delegated_tasks: Dict[str, DelegatedTask] = {}
        self.task_results: Dict[str, RemoteResult] = {}
        self.task_retry_counts: Dict[str, int] = {}
        
        # Sticky sessions (task_family → preferred_node)
        self.task_family_affinity: Dict[str, str] = {}
        
        # Callbacks
        self._on_delegate: Optional[Callable[[DelegatedTask], bool]] = None
        self._on_complete: Optional[Callable[[str, RemoteResult], None]] = None
        self._submit_local: Optional[Callable[[str, Dict[str, Any]], str]] = None
        
        # Thread safety
        self._lock = threading.RLock()
        
        logger.info(f"TaskDelegator initialized on {node_id}")
    
    # ==================== DELEGATION DECISION ====================
    
    def should_delegate(self, task_requirements: Dict[str, Any]) -> bool:
        """
        Decide whether to delegate task or execute locally.
        
        Decision Tree:
        1. If local node severely overloaded (>80%) → DELEGATE
        2. If task requires GPU and local doesn't have → DELEGATE
        3. If task requires specialized tool not available → DELEGATE
        4. If task estimated duration > 60s → DELEGATE
        5. If task requires storage > local available → DELEGATE
        6. Otherwise → LOCAL (default)
        
        Args:
            task_requirements: Task resource requirements
            
        Returns:
            True if should delegate, False for local execution
        """
        with self._lock:
            # Check local load
            if self.current_load > 0.8:
                return True  # Overloaded, delegate
            
            # Check GPU requirement
            if task_requirements.get("requires_gpu", False):
                return True  # No GPU available locally
            
            # Check tool requirements
            required_tools = set(task_requirements.get("requires_tools", []))
            available_tools = {"file_ops", "llm_interface"}  # Default tools
            if not required_tools.issubset(available_tools):
                return True  # Missing required tool
            
            # Check estimated duration
            estimated_duration_ms = task_requirements.get("estimated_duration_ms", 0)
            if estimated_duration_ms > 60000:  # >60 seconds
                return True  # Long-running, delegate
            
            # Check storage requirement
            required_storage_gb = task_requirements.get("required_storage_gb", 0)
            available_local_storage = 100.0  # Assume 100GB local
            if required_storage_gb > available_local_storage:
                return True  # Insufficient storage
            
            return False  # Execute locally
    
    def make_delegation_decision(
        self,
        task_id: str,
        task_requirements: Dict[str, Any],
        task_family: str = "",
    ) -> DelegationDecision:
        """
        Make delegation decision and record it.
        
        Args:
            task_id: Unique task ID
            task_requirements: Task resource requirements
            task_family: Optional task family (for sticky sessions)
            
        Returns:
            DelegationDecision with routing decision
        """
        with self._lock:
            decision = DelegationDecision(
                task_id=task_id,
                local_load=self.current_load,
                timestamp=time.time(),
            )
            
            # Check for sticky session
            if task_family and task_family in self.task_family_affinity:
                target = self.task_family_affinity[task_family]
                decision.decision = "REMOTE"
                decision.target_node = target
                decision.reason = f"Sticky session: task family {task_family}"
                logger.debug(f"Task {task_id}: sticky session to {target}")
            
            # Regular delegation decision
            elif self.should_delegate(task_requirements):
                # Find best remote node
                target = self.node_registry.find_best_node(task_requirements)
                
                if target:
                    decision.decision = "REMOTE"
                    decision.target_node = target
                    decision.reason = f"Delegated to {target} (load={self.current_load:.1%})"
                    
                    # Update sticky session for task family
                    if task_family:
                        self.task_family_affinity[task_family] = target
                    
                    logger.info(f"Task {task_id}: delegating to {target}")
                else:
                    decision.decision = "LOCAL"
                    decision.reason = "No capable remote node available, executing locally"
                    logger.warning(f"Task {task_id}: no capable remote node, falling back to local")
            
            else:
                decision.decision = "LOCAL"
                decision.reason = "Sufficient local resources, executing locally"
                logger.debug(f"Task {task_id}: executing locally")
            
            # Record decision
            self.delegation_decisions.append(decision)
            
            return decision
    
    # ==================== DELEGATION EXECUTION ====================
    
    def delegate_task(self, task: DelegatedTask) -> bool:
        """
        Submit delegated task to remote node.
        
        Args:
            task: Task to delegate
            
        Returns:
            True if submission successful
        """
        with self._lock:
            retries = self.task_retry_counts.get(task.task_id, 0)
            if retries >= self.max_task_retries:
                logger.warning(
                    "Task %s exceeded max retries (%d)",
                    task.task_id,
                    self.max_task_retries,
                )
                return False

            if not self.node_registry.assign_task(task.target_node):
                logger.warning("Node %s cannot accept more tasks", task.target_node)
                return False

            self.task_retry_counts[task.task_id] = retries + 1
            task.submitted_at = time.time()
            self.delegated_tasks[task.task_id] = task
            
            logger.info(
                f"Delegating task {task.task_id} to {task.target_node}: "
                f"{task.fn_name}({task.args})"
            )
            
            # Callback to orchestrator
            if self._on_delegate:
                self._on_delegate(task)
            
            return True
    
    def await_remote_result(
        self,
        task_id: str,
        timeout_ms: int = 30000,
    ) -> Optional[RemoteResult]:
        """
        Block until remote task completes.
        
        Args:
            task_id: Task ID to await
            timeout_ms: Timeout in milliseconds
            
        Returns:
            RemoteResult if successful, None if timeout
        """
        deadline = time.time() + (timeout_ms / 1000.0)
        poll_interval = 0.1  # 100ms polling
        
        while time.time() < deadline:
            with self._lock:
                if task_id in self.task_results:
                    return self.task_results[task_id]
            
            time.sleep(poll_interval)
        
        logger.warning(f"Task {task_id} awaiting remote result timed out after {timeout_ms}ms")
        return None
    
    def record_remote_result(
        self,
        task_id: str,
        result: RemoteResult,
    ) -> None:
        """
        Record result from remote task execution.
        
        Args:
            task_id: Task ID
            result: Execution result
        """
        with self._lock:
            self.task_results[task_id] = result
            delegated = self.delegated_tasks.pop(task_id, None)
            if delegated is not None:
                self.node_registry.release_task(delegated.target_node)
            
            logger.debug(
                f"Remote result for {task_id}: success={result.success}, "
                f"duration={result.duration_ms}ms"
            )
            
            # Callback
            if self._on_complete:
                self._on_complete(task_id, result)
    
    # ==================== LOAD TRACKING ====================
    
    def update_local_load(self, load: float) -> None:
        """
        Update local node load (from CircuitBreaker or similar).
        
        Args:
            load: Load factor (0.0-1.0)
        """
        with self._lock:
            self.current_load = min(1.0, max(0.0, load))
    
    def update_task_queue_depth(self, depth: int) -> None:
        """Update local task queue depth."""
        with self._lock:
            self.local_task_queue_depth = depth
    
    def get_current_load(self) -> float:
        """Get current local load."""
        with self._lock:
            return self.current_load
    
    # ==================== SCHEDULER INTEGRATION ====================
    
    def integrate_with_scheduler(
        self,
        submit_local_task: Callable[[str, Dict[str, Any]], str],
        submit_remote_task: Callable[[DelegatedTask], bool],
    ) -> None:
        """
        Integrate with AgentScheduler.
        
        Hooks task delegator into scheduler's task dispatch pipeline.
        
        Args:
            submit_local_task: Callback to submit to local AgentScheduler
            submit_remote_task: Callback to submit remote task
        """
        self._on_delegate = submit_remote_task
        self._submit_local = submit_local_task
        logger.info("TaskDelegator integrated with AgentScheduler")
    
    # ==================== HISTORY & ANALYTICS ====================
    
    def get_delegation_history(self, since_timestamp: float = 0.0) -> List[DelegationDecision]:
        """Get delegation decisions since timestamp."""
        with self._lock:
            return [
                d for d in self.delegation_decisions
                if d.timestamp >= since_timestamp
            ]
    
    def get_local_vs_remote_ratio(self) -> Tuple[float, float]:
        """
        Get ratio of local vs remote executions.
        
        Returns:
            (local_ratio, remote_ratio) where both sum to 1.0
        """
        with self._lock:
            total = len(self.delegation_decisions)
            if total == 0:
                return (0.0, 0.0)
            
            local_count = sum(
                1 for d in self.delegation_decisions
                if d.decision == "LOCAL"
            )
            remote_count = total - local_count
            
            return (local_count / total, remote_count / total)
    
    def get_delegation_stats(self) -> Dict[str, Any]:
        """Get comprehensive delegation statistics."""
        with self._lock:
            local_ratio, remote_ratio = self.get_local_vs_remote_ratio()
            
            remote_nodes = {}
            for decision in self.delegation_decisions:
                if decision.target_node:
                    if decision.target_node not in remote_nodes:
                        remote_nodes[decision.target_node] = 0
                    remote_nodes[decision.target_node] += 1
            
            return {
                "total_decisions": len(self.delegation_decisions),
                "local_ratio": local_ratio,
                "remote_ratio": remote_ratio,
                "delegated_tasks": len(self.delegated_tasks),
                "completed_tasks": len(self.task_results),
                "remote_node_distribution": remote_nodes,
                "current_load": self.current_load,
                "task_queue_depth": self.local_task_queue_depth,
            }

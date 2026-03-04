"""
NodeRegistry: Cluster node tracking, capability matching, and registration.

Tracks all nodes in the cluster with their:
- Capabilities (CPU, memory, GPU, storage, supported tools)
- Status (ACTIVE, DEGRADED, FAILED, QUARANTINED)
- Trust level (FULL, RESTRICTED, EXPERIMENTAL, QUARANTINE)
- Health metrics and heartbeat tracking
- Suspicion scores from ByzantineDetector

Provides capability matching algorithm to route tasks to suitable nodes.
"""

import threading
import time
import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass

from .data_structures import NodeRecord, NodeCapabilities, NodeHealthMetrics
from .types import NodeRole, NodeStatus, TrustLevel

__all__ = [
    "NodeRegistry",
    "RegistrationResult",
    "CapabilityMatch",
]

logger = logging.getLogger(__name__)


@dataclass
class RegistrationResult:
    """Result of node registration attempt."""
    success: bool
    message: str = ""
    node_id: str = ""


@dataclass
class CapabilityMatch:
    """Result of capability matching."""
    node_id: str
    match_score: float  # 0.0-1.0
    matched_capabilities: List[str]
    unmatched_requirements: List[str]


class NodeRegistry:
    """
    Central registry of all cluster nodes.
    
    Responsibilities:
    1. Track node registration/deregistration
    2. Store node capabilities and status
    3. Match tasks to capable nodes (load balancing)
    4. Update node health metrics
    5. Coordinate with ByzantineDetector for trust levels
    """
    
    def __init__(self, cluster_size: int = 1):
        """
        Initialize NodeRegistry.
        
        Args:
            cluster_size: Expected cluster size
        """
        self.cluster_size = cluster_size
        self.nodes: Dict[str, NodeRecord] = {}
        self.node_lock = threading.RLock()
        
        logger.info(f"NodeRegistry initialized for cluster size {cluster_size}")
    
    # ==================== REGISTRATION ====================
    
    def register_node(self, node_record: NodeRecord) -> RegistrationResult:
        """
        Register a new node in the cluster.
        
        Args:
            node_record: Node to register
            
        Returns:
            RegistrationResult with success status
        """
        with self.node_lock:
            if node_record.node_id in self.nodes:
                return RegistrationResult(
                    success=False,
                    message=f"Node {node_record.node_id} already registered",
                )
            
            # Set registration metadata
            node_record.joined_at = time.time()
            node_record.last_heartbeat = time.time()
            
            # Store node
            self.nodes[node_record.node_id] = node_record
            
            logger.info(
                f"Node registered: {node_record.node_id} "
                f"(role={node_record.role}, trust={node_record.trust_level})"
            )
            
            return RegistrationResult(
                success=True,
                message=f"Node {node_record.node_id} registered successfully",
                node_id=node_record.node_id,
            )
    
    def deregister_node(self, node_id: str, reason: str = "") -> bool:
        """
        Deregister a node from cluster.
        
        Args:
            node_id: Node to deregister
            reason: Reason for deregistration
            
        Returns:
            True if successful, False if node not found
        """
        with self.node_lock:
            if node_id not in self.nodes:
                logger.warning(f"Cannot deregister non-existent node {node_id}")
                return False
            
            del self.nodes[node_id]
            logger.info(f"Node deregistered: {node_id} (reason: {reason})")
            return True
    
    # ==================== NODE STATUS ====================
    
    def update_node_status(
        self,
        node_id: str,
        status: NodeStatus,
        metrics: Optional[NodeHealthMetrics] = None,
    ) -> bool:
        """
        Update node status and optional health metrics.
        
        Args:
            node_id: Node to update
            status: New status
            metrics: Optional health metrics
            
        Returns:
            True if successful
        """
        with self.node_lock:
            if node_id not in self.nodes:
                return False
            
            node = self.nodes[node_id]
            old_status = node.status
            node.status = status
            node.last_heartbeat = time.time()
            
            if metrics:
                # Store metrics (in real impl, maintain history)
                node.capabilities.network_latency_ms = metrics.network_latency_ms
            
            if old_status != status:
                logger.info(f"Node {node_id} status: {old_status.value} → {status.value}")
            
            return True
    
    def update_node_trust(
        self,
        node_id: str,
        trust_level: TrustLevel,
        reason: str = "",
    ) -> bool:
        """
        Update node trust level.
        
        Args:
            node_id: Node to update
            trust_level: New trust level
            reason: Reason for change
            
        Returns:
            True if successful
        """
        with self.node_lock:
            if node_id not in self.nodes:
                return False
            
            node = self.nodes[node_id]
            old_trust = node.trust_level
            node.trust_level = trust_level
            
            logger.info(
                f"Node {node_id} trust: {old_trust.value} → {trust_level.value} ({reason})"
            )
            
            return True
    
    def update_node_suspicion(self, node_id: str, score: float) -> bool:
        """
        Update node suspicion score (from ByzantineDetector).
        
        Args:
            node_id: Node to update
            score: Suspicion score (0.0-1.0)
            
        Returns:
            True if successful
        """
        with self.node_lock:
            if node_id not in self.nodes:
                return False
            
            self.nodes[node_id].suspicion_score = score
            return True
    
    # ==================== NODE QUERYING ====================
    
    def get_node(self, node_id: str) -> Optional[NodeRecord]:
        """Get node record by ID."""
        with self.node_lock:
            return self.nodes.get(node_id)
    
    def get_all_nodes(self) -> List[NodeRecord]:
        """Get all registered nodes."""
        with self.node_lock:
            return list(self.nodes.values())
    
    def get_active_nodes(self) -> List[str]:
        """Get list of ACTIVE node IDs."""
        with self.node_lock:
            return [
                node_id for node_id, node in self.nodes.items()
                if node.status == NodeStatus.ACTIVE
            ]
    
    def get_available_nodes(self) -> List[str]:
        """Get nodes available for task execution (ACTIVE or DEGRADED)."""
        with self.node_lock:
            return [
                node_id for node_id, node in self.nodes.items()
                if node.status in [NodeStatus.ACTIVE, NodeStatus.DEGRADED]
                and node.trust_level != TrustLevel.QUARANTINE
            ]
    
    def get_trusted_nodes(self, min_trust_level: TrustLevel = TrustLevel.FULL) -> List[str]:
        """
        Get nodes meeting minimum trust level.
        
        Args:
            min_trust_level: Minimum trust level required
            
        Returns:
            List of trusted node IDs
        """
        with self.node_lock:
            trust_hierarchy = {
                TrustLevel.FULL: 4,
                TrustLevel.RESTRICTED: 3,
                TrustLevel.EXPERIMENTAL: 2,
                TrustLevel.QUARANTINE: 0,
            }
            min_value = trust_hierarchy[min_trust_level]
            
            return [
                node_id for node_id, node in self.nodes.items()
                if trust_hierarchy[node.trust_level] >= min_value
            ]
    
    # ==================== CAPABILITY MATCHING ====================
    
    def find_capable_nodes(self, requirements: Dict[str, Any]) -> List[CapabilityMatch]:
        """
        Find nodes matching task requirements.
        
        Requirements schema:
        {
            "min_cpu_cores": int,
            "min_ram_gb": float,
            "requires_gpu": bool,
            "requires_tools": [str],  # List of tool names
            "require_trust_level": "FULL"|"RESTRICTED"|etc.
        }
        
        Args:
            requirements: Task requirements
            
        Returns:
            List of CapabilityMatch sorted by match score (highest first)
        """
        with self.node_lock:
            matches = []
            
            for node_id, node in self.nodes.items():
                if node.status not in [NodeStatus.ACTIVE, NodeStatus.DEGRADED]:
                    continue
                
                # Check trust level
                if "require_trust_level" in requirements:
                    required_trust = TrustLevel[requirements["require_trust_level"]]
                    if not self._meets_trust_requirement(node.trust_level, required_trust):
                        continue
                
                # Check capabilities
                match = self._match_capabilities(node, requirements)
                if match.match_score >= 1.0:  # Only accept nodes that fully meet hard requirements
                    matches.append(match)
            
            # Sort by match score descending (best match first)
            matches.sort(key=lambda m: m.match_score, reverse=True)
            return matches
    
    def find_best_node(self, requirements: Dict[str, Any]) -> Optional[str]:
        """
        Find single best node for task (considering load balancing).
        
        Args:
            requirements: Task requirements
            
        Returns:
            Best node_id or None if no capable node found
        """
        matches = self.find_capable_nodes(requirements)
        
        if not matches:
            return None
        
        # Among top matches, use least-loaded
        matches_sorted = sorted(
            matches[:3],  # Consider top 3 candidates
            key=lambda m: self._get_node_load(m.node_id),
        )
        
        if matches_sorted:
            return matches_sorted[0].node_id
        
        return None
    
    def _match_capabilities(
        self,
        node: NodeRecord,
        requirements: Dict[str, Any],
    ) -> CapabilityMatch:
        """
        Match node capabilities against requirements.
        
        Hard requirements (CPU, RAM, GPU if required, tools if required) must all be met.
        Returns score 0 if any hard requirement fails.
        
        Returns:
            CapabilityMatch with score and matched capabilities
        """
        matched = []
        missing = []
        
        # === HARD REQUIREMENTS - MUST ALL BE MET ===
        
        # Check CPU (HARD requirement)
        min_cpu = requirements.get("min_cpu_cores", 1)
        if node.capabilities.cpu_cores >= min_cpu:
            matched.append("cpu")
        else:
            missing.append(f"cpu (need {min_cpu}, have {node.capabilities.cpu_cores})")
            # CPU is a hard requirement - disqualify immediately
            return CapabilityMatch(
                node_id=node.node_id,
                match_score=0,
                matched_capabilities=matched,
                unmatched_requirements=missing,
            )
        
        # Check RAM (HARD requirement)
        min_ram = requirements.get("min_ram_gb", 1.0)
        if node.capabilities.ram_gb >= min_ram:
            matched.append("ram")
        else:
            missing.append(f"ram (need {min_ram}GB, have {node.capabilities.ram_gb}GB)")
            # RAM is a hard requirement - disqualify immediately
            return CapabilityMatch(
                node_id=node.node_id,
                match_score=0,
                matched_capabilities=matched,
                unmatched_requirements=missing,
            )
        
        # Check GPU (conditional hard requirement - HARD if requires_gpu=True)
        if requirements.get("requires_gpu", False):
            if node.capabilities.has_gpu:
                matched.append("gpu")
            else:
                missing.append("gpu")
                # GPU is required and missing - disqualify immediately
                return CapabilityMatch(
                    node_id=node.node_id,
                    match_score=0,
                    matched_capabilities=matched,
                    unmatched_requirements=missing,
                )
        else:
            matched.append("gpu (not required)")
        
        # Check tools (conditional hard requirement - HARD if requires_tools is non-empty)
        required_tools = requirements.get("requires_tools", [])
        available_tools = set(node.capabilities.supported_tools)
        required_tools_set = set(required_tools)
        
        available_required = required_tools_set & available_tools
        missing_tools = required_tools_set - available_tools
        
        if required_tools:
            if missing_tools:
                missing.append(f"tools {missing_tools}")
                # Required tools are missing - disqualify immediately
                return CapabilityMatch(
                    node_id=node.node_id,
                    match_score=0,
                    matched_capabilities=matched,
                    unmatched_requirements=missing,
                )
            if available_required:
                matched.append(f"tools {available_required}")
        else:
            matched.append("tools (not required)")
        
        # All hard requirements met - calculate match score based on optional criteria
        # Since all hard requirements pass, score is always 1.0 (fully capable)
        score = 1.0
        
        return CapabilityMatch(
            node_id=node.node_id,
            match_score=score,
            matched_capabilities=matched,
            unmatched_requirements=missing,
        )
    
    def _meets_trust_requirement(
        self,
        node_trust: TrustLevel,
        required_trust: TrustLevel,
    ) -> bool:
        """Check if node meets minimum trust requirement."""
        trust_hierarchy = {
            TrustLevel.FULL: 4,
            TrustLevel.RESTRICTED: 3,
            TrustLevel.EXPERIMENTAL: 2,
            TrustLevel.QUARANTINE: 0,
        }
        return trust_hierarchy[node_trust] >= trust_hierarchy[required_trust]
    
    def _get_node_load(self, node_id: str) -> float:
        """
        Get normalized load of node (0.0-1.0).
        
        In real impl, get from CircuitBreaker/HealthMonitor.
        For now, return suspicion score as proxy.
        """
        with self.node_lock:
            node = self.nodes.get(node_id)
            if not node:
                return 1.0  # Treat missing node as fully loaded
            
            # Suspicion score affects load (quarantined nodes fully loaded)
            return node.suspicion_score
    
    # ==================== CLUSTER TOPOLOGY ====================
    
    def get_cluster_size(self) -> int:
        """Get current number of registered nodes."""
        with self.node_lock:
            return len(self.nodes)
    
    def get_quorum_size(self) -> int:
        """Get quorum size for consensus (majority)."""
        with self.node_lock:
            return len(self.nodes) // 2 + 1
    
    def get_node_roles(self) -> Dict[NodeRole, List[str]]:
        """Get nodes grouped by role."""
        with self.node_lock:
            roles = {}
            for role in NodeRole:
                roles[role] = [
                    node_id for node_id, node in self.nodes.items()
                    if node.role == role
                ]
            return roles
    
    def update_node_role(self, node_id: str, role: NodeRole) -> bool:
        """Update node's Raft role (for leader election)."""
        with self.node_lock:
            if node_id not in self.nodes:
                return False
            
            old_role = self.nodes[node_id].role
            self.nodes[node_id].role = role
            
            if old_role != role:
                logger.info(f"Node {node_id} role: {old_role.value} → {role.value}")
            
            return True
    
    # ==================== HEARTBEAT TRACKING ====================
    
    def record_heartbeat(self, node_id: str) -> bool:
        """Record heartbeat from node."""
        with self.node_lock:
            if node_id not in self.nodes:
                return False
            
            self.nodes[node_id].last_heartbeat = time.time()
            return True
    
    def get_heartbeat_stale_nodes(self, timeout_sec: int = 30) -> List[str]:
        """Get nodes with stale heartbeats (indicating failure)."""
        with self.node_lock:
            current_time = time.time()
            return [
                node_id for node_id, node in self.nodes.items()
                if (current_time - node.last_heartbeat) > timeout_sec
            ]

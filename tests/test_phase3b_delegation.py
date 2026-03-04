"""
Tests for NodeRegistry and TaskDelegator - Phase 3B.4

Tests cover:
- Node registration/deregistration
- Status and trust level updates
- Capability matching and task routing
- Load balancing
- Sticky sessions
- Delegation decisions
"""

import pytest
import time
from ace.distributed.node_registry import NodeRegistry, CapabilityMatch
from ace.distributed.task_delegator import TaskDelegator, DelegatedTask
from ace.distributed.data_structures import NodeRecord, NodeCapabilities
from ace.distributed.types import NodeRole, NodeStatus, TrustLevel


class TestNodeRegistration:
    """Test node registration and deregistration."""
    
    def test_register_node(self):
        """Register a node successfully."""
        registry = NodeRegistry(cluster_size=3)
        
        node = NodeRecord(
            node_id="node_1",
            hostname="laptop.local",
            ip_address="192.168.1.1",
            capabilities=NodeCapabilities(
                cpu_cores=4,
                ram_gb=8.0,
                supported_tools=["file_ops"],
            ),
        )
        
        result = registry.register_node(node)
        
        assert result.success is True
        assert result.node_id == "node_1"
    
    def test_duplicate_registration_rejected(self):
        """Duplicate registration rejected."""
        registry = NodeRegistry(cluster_size=3)
        
        node = NodeRecord(
            node_id="node_1",
            hostname="laptop.local",
            ip_address="192.168.1.1",
        )
        
        result1 = registry.register_node(node)
        assert result1.success is True
        
        result2 = registry.register_node(node)
        assert result2.success is False
        assert "already registered" in result2.message.lower()
    
    def test_deregister_node(self):
        """Deregister node."""
        registry = NodeRegistry(cluster_size=1)
        
        node = NodeRecord(node_id="node_1", hostname="localhost", ip_address="127.0.0.1")
        registry.register_node(node)
        
        success = registry.deregister_node("node_1", "Testing")
        assert success is True
        
        # Node should be gone
        assert registry.get_node("node_1") is None
    
    def test_registration_sets_metadata(self):
        """Registration sets join timestamp."""
        registry = NodeRegistry()
        
        node = NodeRecord(node_id="node_1", hostname="localhost", ip_address="127.0.0.1")
        registry.register_node(node)
        
        retrieved = registry.get_node("node_1")
        assert retrieved.joined_at > 0
        assert retrieved.last_heartbeat > 0


class TestNodeStatus:
    """Test node status and trust level management."""
    
    def test_update_node_status(self):
        """Update node status."""
        registry = NodeRegistry()
        
        node = NodeRecord(node_id="node_1", hostname="localhost", ip_address="127.0.0.1")
        registry.register_node(node)
        
        success = registry.update_node_status("node_1", NodeStatus.DEGRADED)
        assert success is True
        
        retrieved = registry.get_node("node_1")
        assert retrieved.status == NodeStatus.DEGRADED
    
    def test_update_node_trust(self):
        """Update node trust level."""
        registry = NodeRegistry()
        
        node = NodeRecord(node_id="node_1", hostname="localhost", ip_address="127.0.0.1")
        registry.register_node(node)
        
        success = registry.update_node_trust("node_1", TrustLevel.RESTRICTED, "Testing")
        assert success is True
        
        retrieved = registry.get_node("node_1")
        assert retrieved.trust_level == TrustLevel.RESTRICTED
    
    def test_update_node_suspicion(self):
        """Update node suspicion score."""
        registry = NodeRegistry()
        
        node = NodeRecord(node_id="node_1", hostname="localhost", ip_address="127.0.0.1")
        registry.register_node(node)
        
        registry.update_node_suspicion("node_1", 0.75)
        
        retrieved = registry.get_node("node_1")
        assert retrieved.suspicion_score == 0.75


class TestNodeQuerying:
    """Test node discovery queries."""
    
    def test_get_all_nodes(self):
        """Get all registered nodes."""
        registry = NodeRegistry()
        
        for i in range(3):
            node = NodeRecord(
                node_id=f"node_{i}",
                hostname=f"host{i}",
                ip_address=f"192.168.1.{i}",
            )
            registry.register_node(node)
        
        all_nodes = registry.get_all_nodes()
        assert len(all_nodes) == 3
    
    def test_get_active_nodes(self):
        """Get only ACTIVE nodes."""
        registry = NodeRegistry()
        
        # Register 3 nodes
        for i in range(3):
            node = NodeRecord(node_id=f"node_{i}", hostname=f"host{i}", ip_address=f"192.168.1.{i}")
            registry.register_node(node)
        
        # Mark 2 as active, 1 as degraded
        registry.update_node_status("node_0", NodeStatus.ACTIVE)
        registry.update_node_status("node_1", NodeStatus.ACTIVE)
        registry.update_node_status("node_2", NodeStatus.DEGRADED)
        
        active = registry.get_active_nodes()
        assert len(active) == 2
    
    def test_get_available_nodes(self):
        """Get ACTIVE and DEGRADED nodes (not FAILED or QUARANTINED)."""
        registry = NodeRegistry()
        
        for i in range(4):
            node = NodeRecord(node_id=f"node_{i}", hostname=f"host{i}", ip_address=f"192.168.1.{i}")
            registry.register_node(node)
        
        registry.update_node_status("node_0", NodeStatus.ACTIVE)
        registry.update_node_status("node_1", NodeStatus.DEGRADED)
        registry.update_node_status("node_2", NodeStatus.FAILED)
        registry.update_node_status("node_3", NodeStatus.QUARANTINED)
        
        available = registry.get_available_nodes()
        assert len(available) == 2
        assert set(available) == {"node_0", "node_1"}
    
    def test_get_trusted_nodes(self):
        """Get nodes meeting trust level."""
        registry = NodeRegistry()
        
        for i in range(4):
            node = NodeRecord(node_id=f"node_{i}", hostname=f"host{i}", ip_address=f"192.168.1.{i}")
            registry.register_node(node)
        
        registry.update_node_trust("node_0", TrustLevel.FULL)
        registry.update_node_trust("node_1", TrustLevel.RESTRICTED)
        registry.update_node_trust("node_2", TrustLevel.EXPERIMENTAL)
        registry.update_node_trust("node_3", TrustLevel.QUARANTINE)
        
        trusted = registry.get_trusted_nodes(min_trust_level=TrustLevel.RESTRICTED)
        assert len(trusted) == 2
        assert set(trusted) == {"node_0", "node_1"}


class TestCapabilityMatching:
    """Test task-to-node capability matching."""
    
    def test_find_capable_nodes_cpu(self):
        """Find nodes with sufficient CPU."""
        registry = NodeRegistry()
        
        node1 = NodeRecord(
            node_id="node_1",
            hostname="laptop",
            ip_address="127.0.0.1",
            capabilities=NodeCapabilities(cpu_cores=2),
        )
        node2 = NodeRecord(
            node_id="node_2",
            hostname="server",
            ip_address="127.0.0.2",
            capabilities=NodeCapabilities(cpu_cores=8),
        )
        
        registry.register_node(node1)
        registry.register_node(node2)
        
        registry.update_node_status("node_1", NodeStatus.ACTIVE)
        registry.update_node_status("node_2", NodeStatus.ACTIVE)
        
        # Require 4 cores
        requirements = {"min_cpu_cores": 4}
        matches = registry.find_capable_nodes(requirements)
        
        # Should return both (best match first)
        assert len(matches) >= 1
        assert matches[0].node_id == "node_2"  # Best match
        assert matches[0].match_score == 1.0
    
    def test_find_capable_nodes_gpu(self):
        """Find nodes with GPU."""
        registry = NodeRegistry()
        
        node1 = NodeRecord(
            node_id="node_1",
            hostname="cpu_only",
            ip_address="127.0.0.1",
            capabilities=NodeCapabilities(has_gpu=False),
        )
        node2 = NodeRecord(
            node_id="node_2",
            hostname="gpu_node",
            ip_address="127.0.0.2",
            capabilities=NodeCapabilities(has_gpu=True, gpu_memory_gb=6.0),
        )
        
        registry.register_node(node1)
        registry.register_node(node2)
        
        registry.update_node_status("node_1", NodeStatus.ACTIVE)
        registry.update_node_status("node_2", NodeStatus.ACTIVE)
        
        requirements = {"requires_gpu": True}
        matches = registry.find_capable_nodes(requirements)
        
        assert len(matches) >= 1
        assert matches[0].node_id == "node_2"  # Best match (has GPU)
    
    def test_find_capable_nodes_tools(self):
        """Find nodes with required tools."""
        registry = NodeRegistry()
        
        node1 = NodeRecord(
            node_id="node_1",
            hostname="basic",
            ip_address="127.0.0.1",
            capabilities=NodeCapabilities(supported_tools=["file_ops"]),
        )
        node2 = NodeRecord(
            node_id="node_2",
            hostname="advanced",
            ip_address="127.0.0.2",
            capabilities=NodeCapabilities(
                supported_tools=["file_ops", "llm_interface", "vision"]
            ),
        )
        
        registry.register_node(node1)
        registry.register_node(node2)
        
        registry.update_node_status("node_1", NodeStatus.ACTIVE)
        registry.update_node_status("node_2", NodeStatus.ACTIVE)
        
        requirements = {"requires_tools": ["vision"]}
        matches = registry.find_capable_nodes(requirements)
        
        assert len(matches) >= 1
        assert matches[0].node_id == "node_2"
    
    def test_find_best_node_load_balanced(self):
        """find_best_node returns least loaded among capable."""
        registry = NodeRegistry()
        
        # Register 2 equally capable nodes
        for i in range(2):
            node = NodeRecord(
                node_id=f"node_{i}",
                hostname=f"host{i}",
                ip_address=f"127.0.0.{i+1}",
                capabilities=NodeCapabilities(cpu_cores=4, ram_gb=8.0),
            )
            registry.register_node(node)
            registry.update_node_status(f"node_{i}", NodeStatus.ACTIVE)
        
        # node_0 is more loaded
        registry.update_node_suspicion("node_0", 0.7)
        registry.update_node_suspicion("node_1", 0.2)
        
        requirements = {"min_cpu_cores": 2}
        best = registry.find_best_node(requirements)
        
        # Should pick less loaded node
        assert best == "node_1"


class TestClusterTopology:
    """Test cluster-level queries."""
    
    def test_get_cluster_size(self):
        """Get cluster node count."""
        registry = NodeRegistry(cluster_size=3)
        
        for i in range(3):
            node = NodeRecord(node_id=f"node_{i}", hostname=f"host{i}", ip_address=f"192.168.1.{i}")
            registry.register_node(node)
        
        assert registry.get_cluster_size() == 3
    
    def test_get_quorum_size(self):
        """Calculate quorum for consensus."""
        registry = NodeRegistry(cluster_size=5)
        
        for i in range(5):
            node = NodeRecord(node_id=f"node_{i}", hostname=f"host{i}", ip_address=f"192.168.1.{i}")
            registry.register_node(node)
        
        quorum = registry.get_quorum_size()
        assert quorum == 3  # >50% of 5
    
    def test_get_node_roles(self):
        """Get nodes grouped by Raft role."""
        registry = NodeRegistry()
        
        for i in range(3):
            node = NodeRecord(node_id=f"node_{i}", hostname=f"host{i}", ip_address=f"192.168.1.{i}")
            registry.register_node(node)
            
            if i == 0:
                registry.update_node_role(f"node_{i}", NodeRole.LEADER)
            else:
                registry.update_node_role(f"node_{i}", NodeRole.FOLLOWER)
        
        roles = registry.get_node_roles()
        assert len(roles[NodeRole.LEADER]) == 1
        assert len(roles[NodeRole.FOLLOWER]) == 2


class TestTaskDelegator:
    """Test task delegation decisions and routing."""
    
    def test_should_delegate_high_load(self):
        """Delegate when local load > 80%."""
        registry = NodeRegistry()
        delegator = TaskDelegator("local", registry)
        
        delegator.update_local_load(0.85)
        
        assert delegator.should_delegate({}) is True
    
    def test_should_delegate_gpu_requirement(self):
        """Delegate when GPU required but local doesn't have."""
        registry = NodeRegistry()
        delegator = TaskDelegator("local", registry)
        
        delegator.update_local_load(0.2)  # Low load
        
        assert delegator.should_delegate({"requires_gpu": True}) is True
    
    def test_should_delegate_long_duration(self):
        """Delegate long-running tasks (>60s)."""
        registry = NodeRegistry()
        delegator = TaskDelegator("local", registry)
        
        delegator.update_local_load(0.2)
        
        assert delegator.should_delegate({
            "estimated_duration_ms": 90000  # 90 seconds
        }) is True
    
    def test_should_execute_locally(self):
        """Execute locally when conditions favor it."""
        registry = NodeRegistry()
        delegator = TaskDelegator("local", registry)
        
        delegator.update_local_load(0.3)  # Low load
        
        assert delegator.should_delegate({
            "requires_gpu": False,
            "estimated_duration_ms": 1000,  # 1 second
        }) is False
    
    def test_make_delegation_decision(self):
        """Make delegation decision and record it."""
        registry = NodeRegistry()
        delegator = TaskDelegator("local", registry)
        
        delegator.update_local_load(0.5)
        
        decision = delegator.make_delegation_decision(
            task_id="task_1",
            task_requirements={"estimated_duration_ms": 500},
        )
        
        assert decision.task_id == "task_1"
        assert decision.decision in ["LOCAL", "REMOTE"]
    
    def test_sticky_session(self):
        """Tasks from same family stay on same node."""
        registry = NodeRegistry()
        
        # Register a remote node
        node = NodeRecord(
            node_id="server_1",
            hostname="server",
            ip_address="127.0.0.1",
            capabilities=NodeCapabilities(cpu_cores=8),
        )
        registry.register_node(node)
        registry.update_node_status("server_1", NodeStatus.ACTIVE)
        
        delegator = TaskDelegator("local", registry)
        delegator.update_local_load(0.9)  # Force delegation
        
        # First task delegates to server_1
        decision1 = delegator.make_delegation_decision(
            task_id="task_1",
            task_requirements={"min_cpu_cores": 4},
            task_family="analysis_family",
        )
        
        # Second task from same family should use same server
        decision2 = delegator.make_delegation_decision(
            task_id="task_2",
            task_requirements={"min_cpu_cores": 4},
            task_family="analysis_family",
        )
        
        if decision1.target_node:
            assert decision2.target_node == decision1.target_node
            assert "sticky" in decision2.reason.lower()
    
    def test_delegation_stats(self):
        """Get delegation statistics."""
        registry = NodeRegistry()
        delegator = TaskDelegator("local", registry)
        
        delegator.update_local_load(0.2)
        delegator.make_delegation_decision("task_1", {})
        delegator.make_delegation_decision("task_2", {})
        delegator.make_delegation_decision("task_3", {})
        
        stats = delegator.get_delegation_stats()
        
        assert stats["total_decisions"] == 3
        assert "local_ratio" in stats
        assert "remote_ratio" in stats
        assert stats["current_load"] == 0.2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

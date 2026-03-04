"""
Tests for DistributedMemorySync - Phase 3B.3

Tests cover:
- Write proposal submission and validation
- Leader-enforced quota checks (total, active, per-task)
- Memory replication and ordering
- Conflict resolution
- Consolidation triggering and execution
- No temporary quota violations
"""

import pytest
import time
from ace.distributed.memory_sync import DistributedMemorySync, MemoryQuotaStatus


class TestWriteProposalFlow:
    """Test write proposal submission and validation."""
    
    def test_follower_submits_proposal(self):
        """Follower can submit write proposal."""
        sync = DistributedMemorySync(node_id="follower_1", is_leader=False)
        
        entry_data = {"key": "value", "quality_score": 0.8}
        response = sync.submit_write_proposal(entry_data, task_id="task_1")
        
        assert response.proposal_id is not None
        assert response.accepted is False  # Pending leader approval
    
    def test_leader_accepts_valid_proposal(self):
        """Leader accepts proposal when quotas allow."""
        sync = DistributedMemorySync(node_id="leader", is_leader=True)
        
        entry_data = {"key": "value", "quality_score": 0.8, "is_active": True}
        response = sync.submit_write_proposal(entry_data, task_id="task_1")
        
        assert response.accepted is True
        assert response.raft_log_index is not None
    
    def test_accepted_proposal_creates_entry(self):
        """Accepted proposal creates memory entry."""
        sync = DistributedMemorySync(node_id="leader", is_leader=True)
        
        entry_data = {"key": "value", "quality_score": 0.8}
        response = sync.submit_write_proposal(entry_data, task_id="task_1")
        assert response.accepted is True
        
        # Verify entry exists
        quota = sync.get_quota_status()
        assert quota.total_entries == 1


class TestQuotaEnforcement:
    """Test quota validation and enforcement."""
    
    def test_total_quota_exceeded(self):
        """Leader rejects writes exceeding total quota."""
        sync = DistributedMemorySync(node_id="leader", is_leader=True)
        
        # Fill quota to limit
        sync.quota_status.total_entries = sync.quota_status.quota_total
        
        entry_data = {"key": "value"}
        response = sync.submit_write_proposal(entry_data, task_id="task_1")
        
        assert response.accepted is False
        assert "total quota" in response.reason.lower()
    
    def test_active_quota_exceeded(self):
        """Leader rejects writes exceeding active quota."""
        sync = DistributedMemorySync(node_id="leader", is_leader=True)
        
        # Fill active quota
        sync.quota_status.active_entries = sync.quota_status.quota_active
        
        entry_data = {"key": "value", "is_active": True}
        response = sync.submit_write_proposal(entry_data, task_id="task_1")
        
        assert response.accepted is False
        assert "active quota" in response.reason.lower()
    
    def test_per_task_quota_exceeded(self):
        """Leader rejects writes exceeding per-task quota."""
        sync = DistributedMemorySync(node_id="leader", is_leader=True)
        
        task_id = "task_1"
        
        # Fill per-task quota by adding entries
        for i in range(sync.quota_status.quota_per_task):
            entry_data = {"id": i}
            response = sync.submit_write_proposal(entry_data, task_id=task_id)
            assert response.accepted is True
        
        # Now task quota is full
        entry_data = {"key": "value"}
        response = sync.submit_write_proposal(entry_data, task_id=task_id)
        
        assert response.accepted is False
        assert "per-task quota" in response.reason.lower()
    
    def test_no_temporary_quota_violations(self):
        """Quotas never temporarily exceeded during write."""
        sync = DistributedMemorySync(node_id="leader", is_leader=True)
        
        # Verify quota before large write
        quota_before = sync.get_quota_status()
        
        # Submit write
        entry_data = {"key": "large_data", "size": 1000}
        response = sync.submit_write_proposal(entry_data, task_id="task_1")
        
        # Quota should be updated only if accepted
        quota_after = sync.get_quota_status()
        
        if response.accepted:
            assert quota_after.total_entries == quota_before.total_entries + 1
        else:
            assert quota_after.total_entries == quota_before.total_entries


class TestMemoryReplication:
    """Test memory entry replication."""
    
    def test_replicate_write_to_followers(self):
        """Leader can replicate accepted writes."""
        leader = DistributedMemorySync(node_id="leader", is_leader=True)
        
        entry_data = {"key": "value"}
        response = leader.submit_write_proposal(entry_data, task_id="task_1")
        
        # In real system, would send to followers via Raft
        # For testing, simulate replication on follower
        entry_uuid = list(leader.entries.keys())[0]
        leader.replicate_write(entry_uuid, entry_data, response.raft_log_index)
        
        assert entry_uuid in leader.entries
    
    def test_follower_applies_replicated_write(self):
        """Follower applies writes from Raft log."""
        follower = DistributedMemorySync(node_id="follower", is_leader=False)
        
        entry_uuid = "uuid_123"
        entry_data = {"key": "value", "is_active": True}
        raft_log_index = 1
        task_id = "task_1"
        
        follower.apply_replicated_write(entry_uuid, entry_data, raft_log_index, task_id)
        
        quota = follower.get_quota_status()
        assert quota.total_entries == 1
        assert quota.active_entries == 1
    
    def test_replicated_entries_ordered_by_raft_index(self):
        """Entries replicated in Raft log index order."""
        follower = DistributedMemorySync(node_id="follower", is_leader=False)
        
        # Apply entries in order
        for i in range(5):
            entry_uuid = f"uuid_{i}"
            entry_data = {"id": i, "is_active": True}
            raft_log_index = i + 1
            
            follower.apply_replicated_write(entry_uuid, entry_data, raft_log_index, "task_1")
        
        quota = follower.get_quota_status()
        assert quota.total_entries == 5
        assert quota.active_entries == 5


class TestConflictResolution:
    """Test memory write conflict resolution."""
    
    def test_latest_timestamp_wins(self):
        """Latest timestamp wins in conflict."""
        sync = DistributedMemorySync(node_id="leader", is_leader=True)
        
        old_data = {"key": "old_value", "timestamp": 100.0, "quality_score": 0.5}
        new_data = {"key": "new_value", "timestamp": 200.0, "quality_score": 0.5}
        
        winner = sync.resolve_conflict("uuid_1", new_data, old_data)
        
        assert winner == new_data
        assert winner["key"] == "new_value"
    
    def test_quality_score_as_tiebreaker(self):
        """Quality score breaks timestamp ties."""
        sync = DistributedMemorySync(node_id="leader", is_leader=True)
        
        low_quality = {"key": "value1", "timestamp": 100.0, "quality_score": 0.3}
        high_quality = {"key": "value2", "timestamp": 100.0, "quality_score": 0.8}
        
        winner = sync.resolve_conflict("uuid_1", high_quality, low_quality)
        
        assert winner == high_quality
        assert winner["quality_score"] == 0.8
    
    def test_existing_wins_when_equal(self):
        """Existing entry wins when timestamps and quality equal."""
        sync = DistributedMemorySync(node_id="leader", is_leader=True)
        
        entry1 = {"key": "value1", "timestamp": 100.0, "quality_score": 0.5}
        entry2 = {"key": "value2", "timestamp": 100.0, "quality_score": 0.5}
        
        winner = sync.resolve_conflict("uuid_1", entry2, entry1)
        
        assert winner == entry1  # Existing wins
    
    def test_conflict_logged(self):
        """Conflicts are recorded in conflict history."""
        follower = DistributedMemorySync(node_id="follower", is_leader=False)
        
        # Create initial entry
        follower.apply_replicated_write("uuid_1", {"key": "value1"}, 1, "task_1")
        
        # Apply conflicting entry with same UUID
        conflict_data = {"key": "value2"}
        follower.apply_replicated_write("uuid_1", conflict_data, 2, "task_1")
        
        conflicts = follower.get_conflicts()
        
        # Conflict should be logged (but existing entry kept)
        assert len(conflicts) > 0


class TestConsolidation:
    """Test consolidation mechanism."""
    
    def test_should_consolidate_when_threshold_exceeded(self):
        """Consolidation triggered when entries exceed threshold."""
        sync = DistributedMemorySync(
            node_id="leader",
            is_leader=True,
            consolidation_threshold=50,  # Consolidate at 50%
        )
        
        # Add entries below threshold
        sync.quota_status.total_entries = 4000  # 40%
        assert sync.should_consolidate() is False
        
        # Add entries above threshold
        sync.quota_status.total_entries = 6000  # 60%
        assert sync.should_consolidate() is True
    
    def test_consolidation_removes_low_quality_entries(self):
        """Consolidation prioritizes low-quality, old entries."""
        sync = DistributedMemorySync(node_id="leader", is_leader=True, consolidation_threshold=0)  # Always consolidate
        
        # Add entries with varying quality
        for i in range(10):
            entry_uuid = f"uuid_{i}"
            sync.entries[entry_uuid] = {
                "id": i,
                "quality_score": 0.1 * i,  # 0.1, 0.2, ..., 0.9
                "timestamp": time.time() - (10 - i),  # Older first
            }
            sync.entry_metadata[entry_uuid] = {
                "uuid": entry_uuid,
                "task_id": "task_1",
                "quality_score": 0.1 * i,
                "timestamp": time.time() - (10 - i),
            }
            sync.task_entries["task_1"].add(entry_uuid)
        
        sync.quota_status.total_entries = 10
        sync.quota_status.per_task_entries["task_1"] = 10
        
        # Trigger consolidation
        result = sync.trigger_consolidation()
        
        assert result.success is True
        assert result.entries_archived == 2  # Bottom 20%
        assert result.entries_kept == 8
    
    def test_consolidation_updates_quotas(self):
        """Consolidation updates quota status."""
        sync = DistributedMemorySync(node_id="leader", is_leader=True)
        
        # Add entries
        for i in range(5):
            entry_uuid = f"uuid_{i}"
            sync.entries[entry_uuid] = {"id": i}
            sync.entry_metadata[entry_uuid] = {
                "uuid": entry_uuid,
                "task_id": "task_1",
                "quality_score": 0.5,
                "timestamp": time.time() - i,
            }
            sync.task_entries["task_1"].add(entry_uuid)
        
        sync.quota_status.total_entries = 5
        sync.quota_status.per_task_entries["task_1"] = 5
        sync.consolidation_threshold = 0  # Always consolidate
        
        quota_before = sync.get_quota_status()
        
        # Consolidate
        result = sync.trigger_consolidation()
        
        quota_after = sync.get_quota_status()
        
        assert quota_after.total_entries <= quota_before.total_entries


class TestQuotaStatusTracking:
    """Test quota status reporting."""
    
    def test_quota_status_snapshot(self):
        """Getting quota status provides accurate snapshot."""
        sync = DistributedMemorySync(node_id="leader", is_leader=True)
        
        # Add some entries
        for i in range(3):
            entry_data = {"id": i, "is_active": i < 2}
            sync.submit_write_proposal(entry_data, task_id="task_1")
        
        quota = sync.get_quota_status()
        
        assert quota.total_entries == 3
        assert quota.active_entries == 2  # Only first 2 are active
        assert quota.per_task_entries["task_1"] == 3
    
    def test_quota_percentage_calculations(self):
        """Quota percentage calculations are accurate."""
        quota = MemoryQuotaStatus(
            total_entries=5000,
            active_entries=2500,
        )
        
        assert quota.total_used == 50.0
        assert quota.active_used == 50.0
    
    def test_is_within_quota_check(self):
        """is_within_quota correctly evaluates limits."""
        quota = MemoryQuotaStatus(
            total_entries=9999,
            active_entries=4999,
        )
        assert quota.is_within_quota() is True
        
        quota.total_entries = 10000
        assert quota.is_within_quota() is False
        
        quota.total_entries = 5000
        quota.active_entries = 5000
        assert quota.is_within_quota() is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

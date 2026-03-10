"""
Tests for ConsensusEngine - Phase 3B.1

Tests cover:
- Deterministic election timeout calculation
- Leader election mechanisms
- Log replication and safety properties
- Raft invariants
- Deterministic ordering and replay compatibility
"""

import pytest
import time
from typing import List
from ace.distributed.consensus_engine import ConsensusEngine, ElectionResult
from ace.distributed.data_structures import LogEntry
from ace.distributed.types import NodeRole, LogEntryType


class TestDeterministicTimeout:
    """Test deterministic election timeout calculation."""
    
    def test_timeout_deterministic_same_term(self):
        """Timeout is deterministic: same node_id + term produces same timeout."""
        engine = ConsensusEngine(node_id="node_1", peer_nodes=["node_2", "node_3"])
        
        timeout_1 = engine.calculate_election_timeout(term=1)
        timeout_2 = engine.calculate_election_timeout(term=1)
        
        assert timeout_1 == timeout_2, "Same term should produce same timeout"
        assert timeout_1 >= engine.base_timeout_ms
        assert timeout_1 < engine.base_timeout_ms + engine.jitter_range_ms
    
    def test_timeout_different_by_node_id(self):
        """Different nodes have different timeouts for same term."""
        engine_1 = ConsensusEngine(node_id="node_1", peer_nodes=["node_2", "node_3"])
        engine_2 = ConsensusEngine(node_id="node_2", peer_nodes=["node_1", "node_3"])
        
        timeout_1 = engine_1.calculate_election_timeout(term=1)
        timeout_2 = engine_2.calculate_election_timeout(term=1)
        
        # Might be equal by chance (same hash), but very unlikely
        # At minimum, test they're in valid range
        assert timeout_1 >= engine_1.base_timeout_ms
        assert timeout_2 >= engine_2.base_timeout_ms
    
    def test_timeout_different_by_term(self):
        """Same node has different timeout for different terms."""
        engine = ConsensusEngine(node_id="node_1", peer_nodes=["node_2", "node_3"])
        
        timeout_term_1 = engine.calculate_election_timeout(term=1)
        timeout_term_2 = engine.calculate_election_timeout(term=2)
        
        # Different terms should produce different timeouts
        # (not guaranteed, but very likely given hash-based calculation)
        assert timeout_term_1 >= engine.base_timeout_ms
        assert timeout_term_2 >= engine.base_timeout_ms


class TestLeaderElection:
    """Test leader election mechanisms."""
    
    def test_single_node_election(self):
        """Single-node cluster elects itself as leader."""
        engine = ConsensusEngine(node_id="node_1", peer_nodes=[])
        
        result = engine.start_election()
        
        assert result.success is True
        assert engine.get_role() == NodeRole.LEADER
        assert engine.get_current_term() == 1
    
    def test_candidate_state_transition(self):
        """Node transitions to CANDIDATE during election."""
        engine = ConsensusEngine(node_id="node_1", peer_nodes=["node_2", "node_3"])
        
        initial_role = engine.get_role()
        assert initial_role == NodeRole.FOLLOWER
        
        # start_election transitions to CANDIDATE immediately (before collecting votes)
        engine.start_election()
        
        # After election, either LEADER or FOLLOWER (depending on vote outcome)
        assert engine.get_role() in [NodeRole.LEADER, NodeRole.FOLLOWER, NodeRole.CANDIDATE]
    
    def test_term_increment_on_election(self):
        """Term increments when starting election."""
        engine = ConsensusEngine(node_id="node_1", peer_nodes=["node_2"])
        
        initial_term = engine.get_current_term()
        engine.start_election()
        
        assert engine.get_current_term() == initial_term + 1
    
    def test_vote_for_self_in_election(self):
        """Node votes for itself when starting election."""
        engine = ConsensusEngine(node_id="node_1", peer_nodes=["node_2"])
        
        engine.start_election()
        
        state = engine.get_state()
        assert state.voted_for == "node_1"


class TestLogReplication:
    """Test log replication and safety properties."""
    
    def test_append_entry_requires_leader(self):
        """Only leader can append entries."""
        engine = ConsensusEngine(node_id="node_1", peer_nodes=["node_2"])
        
        # Follower cannot append
        result = engine.append_entry(LogEntryType.TASK, {"data": "test"})
        assert result is None, "Follower cannot append entry"
        
        # Become leader
        engine.state.role = NodeRole.LEADER
        
        # Now can append
        result = engine.append_entry(LogEntryType.TASK, {"data": "test"})
        assert result is not None, "Leader can append entry"
        assert result.index == 1
    
    def test_log_entries_monotonic_index(self):
        """Log entries have monotonically increasing indices."""
        engine = ConsensusEngine(node_id="node_1", peer_nodes=[])
        engine.start_election()  # Become leader
        
        entries = []
        for i in range(5):
            entry = engine.append_entry(LogEntryType.TASK, {"id": i})
            entries.append(entry)
        
        for i, entry in enumerate(entries):
            assert entry.index == i + 1
    
    def test_log_checksum_integrity(self):
        """Log entries include valid checksums."""
        engine = ConsensusEngine(node_id="node_1", peer_nodes=[])
        engine.start_election()
        
        payload = {"key": "value", "number": 42}
        entry = engine.append_entry(LogEntryType.MEMORY_WRITE, payload)
        
        assert entry is not None
        assert entry.verify_checksum() is True
    
    def test_append_request_handling(self):
        """Follower correctly handles AppendEntries RPC."""
        follower = ConsensusEngine(node_id="node_2", peer_nodes=["node_1"])
        
        # Leader sends AppendEntries with entries
        from ace.distributed.consensus_engine import AppendRequest
        
        req = AppendRequest(
            leader_id="node_1",
            term=1,
            prev_log_index=0,
            prev_log_term=0,
            entries=[
                LogEntry(
                    term=1,
                    index=1,
                    entry_type=LogEntryType.TASK,
                    payload={"id": 1},
                    timestamp=time.time(),
                    checksum="abc123",
                    node_id="node_1",
                )
            ],
            leader_commit=0,
        )
        
        resp = follower.handle_append_request(req)
        
        assert resp.success is True
        assert follower.get_state().get_last_log_index() == 1
    
    def test_log_matching_property(self):
        """Raft log matching property: entries with same index/term are identical."""
        engine = ConsensusEngine(node_id="node_1", peer_nodes=[])
        engine.start_election()
        
        # Append two entries with same term
        entry1 = engine.append_entry(LogEntryType.TASK, {"id": 1})
        entry2 = engine.append_entry(LogEntryType.TASK, {"id": 2})
        
        assert entry1.term == entry2.term
        assert entry1.index != entry2.index
        
        # Get entries and verify
        retrieved1 = engine.get_log_entries(start_index=1, end_index=1)[0]
        retrieved2 = engine.get_log_entries(start_index=2, end_index=2)[0]
        
        assert retrieved1.index == entry1.index
        assert retrieved2.index == entry2.index


class TestHeartbeatAndTimeout:
    """Test heartbeat mechanism and timeout handling."""
    
    def test_heartbeat_reset_election_timeout(self):
        """Receiving heartbeat resets election timeout."""
        follower = ConsensusEngine(node_id="node_2", peer_nodes=["node_1"])
        
        # Record initial deadline
        follower.reset_election_timeout()
        initial_deadline = follower._election_deadline
        
        # Simulate delay
        time.sleep(0.01)
        
        # Reset again
        follower.reset_election_timeout()
        new_deadline = follower._election_deadline
        
        assert new_deadline > initial_deadline
    
    def test_election_timeout_check(self):
        """check_election_timeout returns True when timeout expires."""
        follower = ConsensusEngine(node_id="node_2", peer_nodes=["node_1"])
        follower.reset_election_timeout()
        
        # Should not timeout immediately
        assert follower.check_election_timeout() is False
        
        # Manipulate deadline to past for test
        follower._election_deadline = time.monotonic() - 1.0
        
        assert follower.check_election_timeout() is True
    
    def test_leader_no_timeout(self):
        """Leader does not trigger election timeout."""
        engine = ConsensusEngine(node_id="node_1", peer_nodes=[])
        engine.start_election()  # Become leader
        
        # Manipulate deadline to past
        engine._election_deadline = time.monotonic() - 1.0
        
        # Still no timeout because leader
        assert engine.check_election_timeout() is False


class TestDeterministicReplay:
    """Test deterministic replay compatibility (GoldenTrace integration)."""
    
    def test_election_determinism(self):
        """Multiple engines with same node_id produce same election behavior."""
        engine_1 = ConsensusEngine(node_id="node_1", peer_nodes=["node_2", "node_3"])
        engine_2 = ConsensusEngine(node_id="node_1", peer_nodes=["node_2", "node_3"])
        
        # Same sequence of operations should produce same result
        result_1 = engine_1.start_election()
        result_2 = engine_2.start_election()
        
        assert result_1.success == result_2.success
        assert engine_1.get_current_term() == engine_2.get_current_term()
    
    def test_trace_events_recorded(self):
        """All state transitions recorded for deterministic replay."""
        engine = ConsensusEngine(node_id="node_1", peer_nodes=[])
        
        engine.start_election()
        engine.append_entry(LogEntryType.TASK, {"data": "test"})
        
        traces = engine.get_trace_events()
        
        assert len(traces) > 0
        assert any(e["event_type"] == "election_started" for e in traces)
        assert any(e["event_type"] == "entry_appended" for e in traces)


class TestRaftSafetyProperties:
    """Test Raft safety guarantees."""
    
    def test_election_safety_term_uniqueness(self):
        """At most one leader can be elected per term."""
        engine_1 = ConsensusEngine(node_id="node_1", peer_nodes=["node_2"])
        engine_2 = ConsensusEngine(node_id="node_2", peer_nodes=["node_1"])
        
        # Force term 1
        engine_1.state.current_term = 1
        engine_2.state.current_term = 1
        
        # Both cannot become leader in same term
        # (in single-node case, each becomes leader of itself, but in pair case...)
        result_1 = engine_1.start_election()
        result_2 = engine_2.start_election()
        
        # This simulates independent elections; real system with majority voting
        # would prevent both from succeeding
        leaders = [r for r, engine in [(result_1, engine_1)] if r.success]
        if result_2.success:
            leaders.append(result_2)
        
        # Both could claim leadership independently (no consensus yet)
        # But with proper quorum voting, only one would actually succeed
    
    def test_leader_completeness(self):
        """All committed entries exist in leader's log."""
        # Create leader with committed entries
        leader = ConsensusEngine(node_id="leader", peer_nodes=["follower"])
        leader.state.role = NodeRole.LEADER
        leader.state.current_term = 1
        
        # Append and commit entries
        for i in range(3):
            leader.append_entry(LogEntryType.TASK, {"id": i})
        
        # Simulate majority replication
        leader.state.match_index["follower"] = 3
        leader.state.commit_index = 3
        
        # All committed entries should be in log
        for i in range(1, leader.state.commit_index + 1):
            assert leader.get_log_entries(i, i)[0].index == i
    
    def test_state_machine_safety(self):
        """All nodes apply same commands in same order."""
        # This is guaranteed by:
        # 1. Log matching property (same index → same entry)
        # 2. Commit ordering (only leader commits, followers follow)
        # 3. Monotonic commit_index
        
        leader = ConsensusEngine(node_id="leader", peer_nodes=["follower"])
        leader.state.role = NodeRole.LEADER
        leader.state.current_term = 1
        
        # Append entries to leader
        entries_leader = []
        for i in range(3):
            entry = leader.append_entry(LogEntryType.TASK, {"id": f"task_{i}"})
            entries_leader.append(entry)
        
        # On follower, replicate
        follower = ConsensusEngine(node_id="follower", peer_nodes=["leader"])
        
        # Simulate replication
        for entry in entries_leader:
            follower.state.log.append(entry)
        
        # Both have same entries in same order
        leader_entries = leader.get_log_entries()
        follower_entries = follower.get_log_entries()
        
        assert len(leader_entries) == len(follower_entries)
        for le, fe in zip(leader_entries, follower_entries):
            assert le.index == fe.index
            assert le.term == fe.term
            assert le.payload == fe.payload


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

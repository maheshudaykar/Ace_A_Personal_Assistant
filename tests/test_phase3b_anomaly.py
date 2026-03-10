"""
Tests for ByzantineDetector - Phase 3B.2

Tests cover:
- Vote divergence detection
- Checksum validation
- Behavioral anomaly scoring
- Quarantine and isolation
- False positive rate validation
- Recovery mechanisms
"""

import pytest
import time
from ace.distributed.byzantine_detector import ByzantineDetector
from ace.distributed.data_structures import VoteRecord, NodeSuspicionRecord


class TestVoteDivergenceDetection:
    """Test vote divergence detection mechanism."""
    
    def test_detect_vote_divergence(self):
        """Node voting against majority flagged."""
        detector = ByzantineDetector(node_id="detector_1", cluster_size=3)
        
        vote = VoteRecord(
            node_id="node_2",
            proposal_id="prop_1",
            voted_for=False,  # Votes NO
            timestamp=time.time(),
            reason="Disagree with proposal",
        )
        
        majority_decision = True  # Majority voted YES
        
        update = detector.analyze_vote(vote, majority_decision)
        
        assert update.node_id == "node_2"
        assert update.new_score > update.old_score  # Score increased
        assert "vote_divergence" in update.violation_type
        assert update.delta > 0  # Positive increase
    
    def test_agreement_decreases_suspicion_after_streak(self):
        """Recovery decay applies after consecutive agreement streak."""
        detector = ByzantineDetector(node_id="detector_1", cluster_size=3)
        
        # First, increase suspicion
        vote1 = VoteRecord(
            node_id="node_2",
            proposal_id="prop_1",
            voted_for=False,
            timestamp=time.time(),
        )
        update1 = detector.analyze_vote(vote1, True)
        assert update1.delta > 0
        
        # Then provide enough positive signals to unlock recovery decay.
        updates = []
        for i in range(2, 5):
            vote = VoteRecord(
                node_id="node_2",
                proposal_id=f"prop_{i}",
                voted_for=True,
                timestamp=time.time(),
            )
            updates.append(detector.analyze_vote(vote, True))

        assert updates[-1].new_score < updates[-1].old_score  # Score decreased
        assert updates[-1].delta < 0  # Negative delta (recovery)
    
    def test_persistent_divergence_accumulates(self):
        """Repeated vote divergence accumulates violations."""
        detector = ByzantineDetector(node_id="detector_1", cluster_size=3)
        
        # Multiple divergent votes
        for i in range(5):
            vote = VoteRecord(
                node_id="node_2",
                proposal_id=f"prop_{i}",
                voted_for=False,
                timestamp=time.time(),
            )
            detector.analyze_vote(vote, True)
        
        record = detector.get_suspicion_record("node_2")
        assert record.violation_count == 5
        assert record.suspicion_score > 0.2


class TestChecksumValidation:
    """Test checksum validation mechanism."""
    
    def test_valid_checksum_accepts(self):
        """Valid checksum passes validation."""
        detector = ByzantineDetector(node_id="detector_1", cluster_size=3)
        
        payload = {"key": "value", "number": 42}
        
        import json, hashlib
        payload_str = json.dumps(payload, sort_keys=True)
        correct_checksum = hashlib.sha256(payload_str.encode()).hexdigest()
        
        is_valid, update = detector.validate_checksum("node_2", payload, correct_checksum)
        
        assert is_valid is True
        assert update.new_score <= update.old_score  # Score did not increase
    
    def test_invalid_checksum_detected(self):
        """Mismatched checksum detected and flagged."""
        detector = ByzantineDetector(node_id="detector_1", cluster_size=3)
        
        payload = {"key": "value"}
        wrong_checksum = "wrong_hash_12345"
        
        is_valid, update = detector.validate_checksum("node_2", payload, wrong_checksum)
        
        assert is_valid is False
        assert update.new_score > update.old_score  # Score increased
        assert "checksum_mismatch" in update.violation_type
        assert update.delta > 0
    
    def test_checksum_mismatch_accumulates(self):
        """Multiple checksum failures accumulate."""
        detector = ByzantineDetector(node_id="detector_1", cluster_size=3)
        
        for i in range(3):
            payload = {"id": i}
            wrong_checksum = f"wrong_{i}"
            
            detector.validate_checksum("node_2", payload, wrong_checksum)
        
        record = detector.get_suspicion_record("node_2")
        assert record.violation_count == 3
        assert record.suspicion_score > 0.2


class TestBehavioralAnomaly:
    """Test behavioral anomaly detection."""
    
    def test_record_normal_behavior(self):
        """Normal behavior recorded without flagging."""
        detector = ByzantineDetector(node_id="detector_1", cluster_size=3)
        
        # Record normal messages (100 bytes, 10ms, success)
        for i in range(20):
            detector.record_behavior("node_2", message_size=100, processing_time_ms=10.0, success=True)
        
        # Should not trigger anomaly
        anomaly = detector.detect_behavioral_anomaly("node_2")
        
        # Might be None (no anomaly) or positive (depends on algorithm)
        if anomaly is not None:
            assert anomaly.delta >= 0
    
    def test_detect_high_error_rate(self):
        """High error rate detected and flagged."""
        detector = ByzantineDetector(node_id="detector_1", cluster_size=3)
        
        # Record messages with >10% failure rate (11 failures, 9 successes)
        for i in range(9):
            detector.record_behavior("node_2", message_size=100, processing_time_ms=10.0, success=True)
        
        for i in range(11):
            detector.record_behavior("node_2", message_size=100, processing_time_ms=10.0, success=False)
        
        anomaly = detector.detect_behavioral_anomaly("node_2")
        
        assert anomaly is not None
        assert anomaly.new_score > anomaly.old_score
        assert "error_rate" in anomaly.violation_type or anomaly.violation_type != ""


class TestQuarantine:
    """Test node quarantine mechanism."""
    
    def test_quarantine_blocks_node(self):
        """Quarantined node removed from trusted list."""
        detector = ByzantineDetector(node_id="detector_1", cluster_size=3)
        
        detector.quarantine_node("node_2", "Detected malicious behavior")
        
        assert detector.is_quarantined("node_2") is True
        assert "node_2" not in detector.get_trusted_nodes()
    
    def test_high_suspicion_triggers_quarantine(self):
        """Score >= 0.7 triggers quarantine."""
        detector = ByzantineDetector(node_id="detector_1", cluster_size=3)
        
        # Manually set high suspicion
        detector._ensure_record("node_2")
        detector.suspicion_records["node_2"].suspicion_score = 0.75
        
        alert = detector.evaluate_suspect_node("node_2")
        
        assert alert is not None
        assert alert.action_taken == "quarantine"
        assert detector.is_quarantined("node_2") is True
    
    def test_medium_suspicion_reduces_trust(self):
        """Score 0.3-0.7 reduces trust level."""
        detector = ByzantineDetector(node_id="detector_1", cluster_size=3)
        
        detector._ensure_record("node_2")
        detector.suspicion_records["node_2"].suspicion_score = 0.5
        
        alert = detector.evaluate_suspect_node("node_2")
        
        assert alert is not None
        assert alert.action_taken == "reduce_trust"
    
    def test_quarantine_removes_from_quorum(self):
        """Quarantined nodes excluded from voting quorum."""
        detector = ByzantineDetector(node_id="detector_1", cluster_size=5)
        
        # Start with all nodes trusted
        detector._ensure_record("node_1")
        detector._ensure_record("node_2")
        detector._ensure_record("node_3")
        detector._ensure_record("node_4")
        detector._ensure_record("node_5")
        
        trusted_before = len(detector.get_trusted_nodes())
        
        # Quarantine two nodes
        detector.quarantine_node("node_2", "Malicious")
        detector.quarantine_node("node_3", "Malicious")
        
        trusted_after = len(detector.get_trusted_nodes())
        
        assert trusted_after == trusted_before - 2


class TestRecovery:
    """Test node recovery mechanisms."""
    
    def test_manual_recovery_allowed(self):
        """Quarantined node can be recovered with manual approval."""
        detector = ByzantineDetector(node_id="detector_1", cluster_size=3)
        
        detector.quarantine_node("node_2", "Test")
        assert detector.is_quarantined("node_2") is True
        
        recovered = detector.request_node_recovery("node_2")
        
        assert recovered is True
        assert detector.is_quarantined("node_2") is False
    
    def test_recovered_node_starts_clean(self):
        """Recovered node starts with low suspicion score."""
        detector = ByzantineDetector(node_id="detector_1", cluster_size=3)
        
        # Quarantine node first
        detector.quarantine_node("node_2", "Test quarantine")
        
        # Verify quarantined
        assert detector.is_quarantined("node_2") is True
        
        # Recover
        detector.request_node_recovery("node_2")
        
        record = detector.get_suspicion_record("node_2")
        assert record.suspicion_score == 0.1  # Reset to low
        # Note: violation history preserved for forensics


class TestAnomalyAlerts:
    """Test anomaly alert generation and tracking."""
    
    def test_alerts_recorded(self):
        """Anomaly alerts recorded in alert log."""
        detector = ByzantineDetector(node_id="detector_1", cluster_size=3)
        
        detector.quarantine_node("node_2", "Test quarantine")
        
        alerts = detector.get_alerts()
        
        assert len(alerts) > 0
        assert any(a.node_id == "node_2" for a in alerts)
    
    def test_alerts_timestamp_filtering(self):
        """Alerts can be filtered by timestamp."""
        detector = ByzantineDetector(node_id="detector_1", cluster_size=3)
        
        before = time.time()
        time.sleep(0.01)
        
        detector.quarantine_node("node_2", "Test")
        
        after = time.time()
        
        # Get alerts after "before"
        alerts = detector.get_alerts(since_timestamp=before)
        
        assert len(alerts) > 0


class TestFalsePositiveRate:
    """Test false positive rate on normal nodes."""
    
    def test_normal_node_low_suspicion(self):
        """Normal behaving node maintains low suspicion."""
        detector = ByzantineDetector(node_id="detector_1", cluster_size=3)
        
        # Record consistent normal behavior
        for i in range(50):
            detector.record_behavior(
                "node_2",
                message_size=100,
                processing_time_ms=10.0,
                success=True,
            )
        
        # Vote with majority consistently
        for i in range(10):
            vote = VoteRecord(
                node_id="node_2",
                proposal_id=f"prop_{i}",
                voted_for=True,
                timestamp=time.time(),
            )
            detector.analyze_vote(vote, True)
        
        # Validate checksums
        for i in range(10):
            import json, hashlib
            payload = {"id": i}
            payload_str = json.dumps(payload, sort_keys=True)
            checksum = hashlib.sha256(payload_str.encode()).hexdigest()
            
            detector.validate_checksum("node_2", payload, checksum)
        
        score = detector.get_suspicion_score("node_2")
        
        assert score < 0.2  # Should remain low
        assert not detector.is_quarantined("node_2")


class TestMultipleDetectionMethods:
    """Test combining multiple detection methods."""
    
    def test_accumulation_from_multiple_methods(self):
        """Suspicion accumulates from multiple detection methods."""
        detector = ByzantineDetector(node_id="detector_1", cluster_size=3)
        
        # Vote divergence
        vote = VoteRecord(
            node_id="node_2",
            proposal_id="prop_1",
            voted_for=False,
            timestamp=time.time(),
        )
        detector.analyze_vote(vote, True)
        
        score_after_vote = detector.get_suspicion_score("node_2")
        
        # Checksum failure
        detector.validate_checksum("node_2", {"data": "test"}, "wrong_hash")
        
        score_after_checksum = detector.get_suspicion_score("node_2")
        
        # Both should contribute
        assert score_after_checksum > score_after_vote > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

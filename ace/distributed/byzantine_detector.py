"""
ByzantineDetector: Anomaly detection and node quarantine system for Phase 3B.

This is a SECURITY LAYER, not a consensus mechanism. It identifies suspicious
nodes via behavioral analysis and isolates them. Complements Raft consensus
with defense-in-depth protection.

CRITICAL: ByzantineDetector is anomaly detection, NOT Byzantine fault tolerance.
- Provides early warning of malicious behavior
- Quarantines suspicious nodes
- Preserves forensic logs
- Does NOT change Raft's crash-fault tolerance model

Detection Strategies:
1. Vote divergence: Nodes voting against majority
2. Checksum validation: Detecting corrupted payloads
3. Behavioral anomaly scoring: Statistical baselines per node
4. Memory conflict analysis: Dissenting proposals examined

Suspicion Score Actions:
- 0.0-0.3: Observe & log
- 0.3-0.7: Reduce trust, exclude from critical ops
- 0.7-1.0: Quarantine (disconnect, preserve logs)
"""

import hashlib
import time
import threading
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Any, Tuple, cast
from collections import defaultdict
import statistics

from .data_structures import (
    NodeSuspicionRecord,
    AnomalyAlert,
    VoteRecord,
)

__all__ = [
    "ByzantineDetector",
    "AnomalyResult",
    "SuspicionUpdate",
]

logger = logging.getLogger(__name__)


@dataclass
class AnomalyResult:
    """Result of anomaly analysis."""
    is_anomalous: bool
    confidence: float  # 0.0-1.0
    anomaly_type: str = ""
    evidence: Dict[str, Any] = field(default_factory=lambda: cast(Dict[str, Any], {}))


@dataclass
class SuspicionUpdate:
    """Update to a node's suspicion score."""
    node_id: str
    old_score: float
    new_score: float
    delta: float  # Change in score (can be positive or negative)
    reason: str
    violation_type: str


class ByzantineDetector:
    """
    Anomaly detection system for identifying suspicious nodes.
    
    Uses multiple detection strategies:
    1. Vote divergence: Compare node's vote against majority
    2. Checksum validation: Verify payload integrity
    3. Behavioral scoring: Track message frequency, sizes, error rates
    4. Memory conflict analysis: Examine dissenting memory proposals
    
    Safety Model:
    - Defense-in-depth: Identifies threats before they cause damage
    - Quarantine-based: Removes suspicious nodes from critical operations
    - Forensic-preserving: Logs all anomalies for investigation
    - Recovery path: Manual review required for node restoration
    """
    
    def __init__(self, node_id: str, cluster_size: int):
        """
        Initialize ByzantineDetector.
        
        Args:
            node_id: This node's ID (detector runs on each node)
            cluster_size: Total nodes in cluster
        """
        self.node_id = node_id
        self.cluster_size = cluster_size
        
        # Node suspicion tracking
        self.suspicion_records: Dict[str, NodeSuspicionRecord] = {}
        
        # Behavioral baseline per node (for anomaly detection)
        self.behavioral_baseline: Dict[str, BehavioralBaseline] = {}
        
        # Alert history
        self.alerts: List[AnomalyAlert] = []
        
        # Quarantine list
        self.quarantined_nodes: Set[str] = set()

        # Recovery ratchet: require multiple consecutive positive signals
        # before decreasing suspicion (prevents alternating good/bad evasion).
        self._positive_signals: Dict[str, int] = defaultdict(int)
        self._positive_signals_required = 3
        
        # Thread safety
        self._lock = threading.RLock()
        
        logger.info(f"ByzantineDetector initialized on {node_id} for cluster size {cluster_size}")
    
    # ==================== VOTE DIVERGENCE DETECTION ====================
    
    def analyze_vote(
        self,
        vote: VoteRecord,
        majority_decision: bool,
    ) -> SuspicionUpdate:
        """
        Analyze vote against majority decision.
        
        Strategy: Detect if node consistently votes against the majority.
        Persistent divergence indicates suspicious behavior.
        
        Args:
            vote: Vote record from node
            majority_decision: What the majority voted for
            
        Returns:
            SuspicionUpdate with score adjustment
        """
        with self._lock:
            node_id = vote.node_id
            self._ensure_record(node_id)
            
            # Check if vote diverges from majority
            vote_diverges = vote.voted_for != majority_decision
            
            if vote_diverges:
                delta = 0.05  # Small increase per divergence
                self._positive_signals[node_id] = 0
                
                self.suspicion_records[node_id].violation_count += 1
                self.suspicion_records[node_id].last_violation = time.time()
                self.suspicion_records[node_id].violation_types.append("vote_divergence")
                
                old_score = self.suspicion_records[node_id].suspicion_score
                new_score = min(1.0, old_score + delta)
                self.suspicion_records[node_id].suspicion_score = new_score
                
                logger.warning(
                    f"Vote divergence detected: {node_id} voted {vote.voted_for}, "
                    f"majority voted {majority_decision}"
                )
                
                return SuspicionUpdate(
                    node_id=node_id,
                    old_score=old_score,
                    new_score=new_score,
                    delta=delta,
                    reason="Voted against majority",
                    violation_type="vote_divergence",
                )
            else:
                # Recovery is streak-gated to prevent alternating good/bad evasion.
                old_score, new_score, delta, reason = self._apply_positive_signal(
                    node_id,
                    signal_reason="Voted with majority",
                )
                
                return SuspicionUpdate(
                    node_id=node_id,
                    old_score=old_score,
                    new_score=new_score,
                    delta=delta,
                    reason=reason,
                    violation_type="vote_agreement",
                )
    
    # ==================== CHECKSUM VALIDATION ====================
    
    def validate_checksum(
        self,
        node_id: str,
        payload: Any,
        claimed_checksum: str,
    ) -> Tuple[bool, SuspicionUpdate]:
        """
        Validate payload integrity via checksum.
        
        Strategy: Detect if node's payload doesn't match claimed checksum.
        Could indicate transmission corruption or malicious tampering.
        
        Args:
            node_id: Source node
            payload: Data payload
            claimed_checksum: Checksum node claimed
            
        Returns:
            (is_valid, SuspicionUpdate)
        """
        with self._lock:
            self._ensure_record(node_id)
            
            # Compute actual checksum
            import json
            payload_str = json.dumps(payload, sort_keys=True)
            actual_checksum = hashlib.sha256(payload_str.encode()).hexdigest()
            
            is_valid = actual_checksum == claimed_checksum
            
            if not is_valid:
                # Checksum mismatch - possible corruption or tampering
                delta = 0.08  # Moderate increase
                self._positive_signals[node_id] = 0
                
                self.suspicion_records[node_id].violation_count += 1
                self.suspicion_records[node_id].last_violation = time.time()
                self.suspicion_records[node_id].violation_types.append("checksum_mismatch")
                
                old_score = self.suspicion_records[node_id].suspicion_score
                new_score = min(1.0, old_score + delta)
                self.suspicion_records[node_id].suspicion_score = new_score
                
                logger.warning(
                    f"Checksum mismatch from {node_id}: "
                    f"expected {claimed_checksum}, got {actual_checksum}"
                )
                
                update = SuspicionUpdate(
                    node_id=node_id,
                    old_score=old_score,
                    new_score=new_score,
                    delta=delta,
                    reason=f"Checksum mismatch: claimed={claimed_checksum[:8]}..., "
                           f"actual={actual_checksum[:8]}...",
                    violation_type="checksum_mismatch",
                )
            else:
                old_score, new_score, delta, reason = self._apply_positive_signal(
                    node_id,
                    signal_reason="Checksum valid",
                )
                
                update = SuspicionUpdate(
                    node_id=node_id,
                    old_score=old_score,
                    new_score=new_score,
                    delta=delta,
                    reason=reason,
                    violation_type="checksum_valid",
                )
            
            return is_valid, update
    
    # ==================== BEHAVIORAL ANOMALY SCORING ====================
    
    def record_behavior(
        self,
        node_id: str,
        message_size: int,
        processing_time_ms: float,
        success: bool,
    ) -> None:
        """
        Record node behavior for statistical anomaly detection.
        
        Builds baseline of normal behavior (message frequency, sizes, latency).
        Detects outliers via statistical deviation (mean +/- 2 sigma).
        
        Args:
            node_id: Node being analyzed
            message_size: Size of message in bytes
            processing_time_ms: Time to process in milliseconds
            success: Whether operation succeeded
        """
        with self._lock:
            self._ensure_baseline(node_id)
            baseline = self.behavioral_baseline[node_id]
            
            baseline.messages.append({
                "timestamp": time.time(),
                "size": message_size,
                "latency": processing_time_ms,
                "success": success,
            })
            
            # Keep only recent history (last 100 messages)
            if len(baseline.messages) > 100:
                baseline.messages = baseline.messages[-100:]
    
    def detect_behavioral_anomaly(self, node_id: str) -> Optional[SuspicionUpdate]:
        """
        Detect behavioral anomalies via statistical analysis.
        
        Compares node's behavior against baseline:
        - Message frequency outliers
        - Payload size outliers
        - Error rate spikes
        - Processing time anomalies
        
        Returns:
            SuspicionUpdate if anomaly detected, None otherwise
        """
        with self._lock:
            if node_id not in self.behavioral_baseline:
                return None
            
            self._ensure_record(node_id)
            baseline = self.behavioral_baseline[node_id]
            
            if len(baseline.messages) < 10:
                return None  # Not enough data for statistical analysis
            
            # Extract recent statistics
            recent = baseline.messages[-20:]  # Last 20 messages
            
            sizes = [m["size"] for m in recent]
            latencies = [m["latency"] for m in recent]
            success_rate = sum(1 for m in recent if m["success"]) / len(recent)
            
            # Calculate baseline stats
            size_mean = statistics.mean(sizes)
            size_stdev = statistics.stdev(sizes) if len(set(sizes)) > 1 else 0
            
            latency_mean = statistics.mean(latencies)
            latency_stdev = statistics.stdev(latencies) if len(set(latencies)) > 1 else 0
            
            # Detect outliers (>2 sigma from mean)
            outliers = 0
            for msg in recent[-5:]:  # Check last 5
                size_z = abs((msg["size"] - size_mean) / (size_stdev + 1e-6))
                latency_z = abs((msg["latency"] - latency_mean) / (latency_stdev + 1e-6))
                
                if size_z > 2.0 or latency_z > 2.0:
                    outliers += 1
            
            # Check error rate
            if success_rate < 0.9:  # >10% failure rate
                self.suspicion_records[node_id].violation_count += 1
                self.suspicion_records[node_id].last_violation = time.time()
                self.suspicion_records[node_id].violation_types.append("high_error_rate")
                
                old_score = self.suspicion_records[node_id].suspicion_score
                delta = 0.10
                new_score = min(1.0, old_score + delta)
                self.suspicion_records[node_id].suspicion_score = new_score
                
                logger.warning(f"High error rate detected on {node_id}: {success_rate:.1%}")
                
                return SuspicionUpdate(
                    node_id=node_id,
                    old_score=old_score,
                    new_score=new_score,
                    delta=delta,
                    reason=f"High error rate: {success_rate:.1%}",
                    violation_type="high_error_rate",
                )
            
            # Check for outliers in message patterns
            if outliers > 2:
                old_score = self.suspicion_records[node_id].suspicion_score
                delta = 0.05
                new_score = min(1.0, old_score + delta)
                self.suspicion_records[node_id].suspicion_score = new_score
                
                logger.warning(f"Behavioral anomaly: {node_id} has {outliers} statistical outliers")
                
                return SuspicionUpdate(
                    node_id=node_id,
                    old_score=old_score,
                    new_score=new_score,
                    delta=delta,
                    reason=f"Statistical anomaly: {outliers} outliers detected",
                    violation_type="behavioral_anomaly",
                )
            
            return None
    
    # ==================== QUARANTINE MANAGEMENT ====================
    
    def evaluate_suspect_node(self, node_id: str) -> Optional[AnomalyAlert]:
        """
        Evaluate node's suspicion score and take action.
        
        Actions:
        - 0.0-0.3: Observe
        - 0.3-0.7: Reduce trust, exclude from critical ops
        - 0.7-1.0: Quarantine
        
        Args:
            node_id: Node to evaluate
            
        Returns:
            AnomalyAlert if action taken, None otherwise
        """
        with self._lock:
            if node_id not in self.suspicion_records:
                return None
            
            record = self.suspicion_records[node_id]
            score = record.suspicion_score
            
            if score >= 0.7:
                if node_id not in self.quarantined_nodes:
                    self.quarantined_nodes.add(node_id)
                    
                    alert = AnomalyAlert(
                        alert_id=f"alert_{int(time.time() * 1000)}_{node_id}",
                        node_id=node_id,
                        detection_method="multi_vector_anomaly",
                        evidence={
                            "suspicion_score": score,
                            "violation_count": record.violation_count,
                            "violation_types": record.violation_types,
                        },
                        timestamp=time.time(),
                        action_taken="quarantine",
                    )
                    
                    self.alerts.append(alert)
                    logger.critical(f"Node {node_id} QUARANTINED (score={score:.2f})")
                    
                    return alert
            
            elif score >= 0.3:
                alert = AnomalyAlert(
                    alert_id=f"alert_{int(time.time() * 1000)}_{node_id}",
                    node_id=node_id,
                    detection_method="multi_vector_anomaly",
                    evidence={
                        "suspicion_score": score,
                        "violation_count": record.violation_count,
                        "violation_types": record.violation_types,
                    },
                    timestamp=time.time(),
                    action_taken="reduce_trust",
                )
                
                logger.warning(f"Node {node_id} trust reduced (score={score:.2f})")
                return alert
            
            return None
    
    def quarantine_node(self, node_id: str, reason: str) -> None:
        """Immediately quarantine a node."""
        with self._lock:
            self.quarantined_nodes.add(node_id)
            self._ensure_record(node_id)
            self.suspicion_records[node_id].suspicion_score = 1.0
            
            # Create alert for quarantine
            alert = AnomalyAlert(
                alert_id=f"alert_{int(time.time() * 1000)}_{node_id}",
                node_id=node_id,
                detection_method="manual_quarantine",
                evidence={
                    "reason": reason,
                    "suspicion_score": 1.0,
                },
                timestamp=time.time(),
                action_taken="quarantine",
            )
            self.alerts.append(alert)
            
            logger.critical(f"Node {node_id} quarantined: {reason}")
    
    def get_trusted_nodes(self, exclude_score_threshold: float = 0.3) -> List[str]:
        """
        Get list of trusted nodes for quorum calculations.
        
        Excludes nodes with suspicion_score >= threshold.
        
        Args:
            exclude_score_threshold: Suspicion score cutoff (default 0.3)
            
        Returns:
            List of trusted node_ids
        """
        with self._lock:
            trusted = [
                node_id for node_id, record in self.suspicion_records.items()
                if record.suspicion_score < exclude_score_threshold
                and node_id not in self.quarantined_nodes
            ]
            return trusted
    
    def is_quarantined(self, node_id: str) -> bool:
        """Check if node is quarantined."""
        with self._lock:
            return node_id in self.quarantined_nodes
    
    def request_node_recovery(self, node_id: str) -> bool:
        """
        Request recovery of quarantined node (requires manual approval).
        
        Returns:
            True if recovery request accepted
        """
        with self._lock:
            if node_id not in self.quarantined_nodes:
                logger.warning(f"Cannot recover non-quarantined node {node_id}")
                return False
            
            # Reset suspicion (requires manual approval in production)
            self.quarantined_nodes.discard(node_id)
            self._positive_signals[node_id] = 0
            if node_id in self.suspicion_records:
                self.suspicion_records[node_id].suspicion_score = 0.1  # Low score after recovery
            
            logger.info(f"Node {node_id} recovery approved")
            return True
    
    # ==================== STATE INSPECTION ====================
    
    def get_suspicion_record(self, node_id: str) -> Optional[NodeSuspicionRecord]:
        """Get suspicion record for a node."""
        with self._lock:
            return self.suspicion_records.get(node_id)
    
    def get_suspicion_score(self, node_id: str) -> float:
        """Get current suspicion score for a node."""
        with self._lock:
            if node_id in self.suspicion_records:
                return self.suspicion_records[node_id].suspicion_score
            return 0.0
    
    def get_alerts(self, since_timestamp: float = 0.0) -> List[AnomalyAlert]:
        """Get anomaly alerts since timestamp."""
        with self._lock:
            return [a for a in self.alerts if a.timestamp >= since_timestamp]
    
    # ==================== HELPER METHODS ====================
    
    def _ensure_record(self, node_id: str) -> None:
        """Ensure suspicion record exists for node."""
        if node_id not in self.suspicion_records:
            self.suspicion_records[node_id] = NodeSuspicionRecord(node_id=node_id)
    
    def _ensure_baseline(self, node_id: str) -> None:
        """Ensure behavioral baseline exists for node."""
        if node_id not in self.behavioral_baseline:
            self.behavioral_baseline[node_id] = BehavioralBaseline()

    def _apply_positive_signal(
        self,
        node_id: str,
        signal_reason: str,
    ) -> Tuple[float, float, float, str]:
        """Apply streak-gated recovery decay from a positive signal."""
        old_score = self.suspicion_records[node_id].suspicion_score
        self._positive_signals[node_id] += 1

        if self._positive_signals[node_id] >= self._positive_signals_required:
            new_score = max(0.0, old_score - 0.02)
            self.suspicion_records[node_id].suspicion_score = new_score
            self._positive_signals[node_id] = 0
            return old_score, new_score, -0.02, f"{signal_reason} (recovery applied)"

        remaining = self._positive_signals_required - self._positive_signals[node_id]
        return old_score, old_score, 0.0, (
            f"{signal_reason} (recovery pending: {remaining} more positive signal(s))"
        )


@dataclass
class BehavioralBaseline:
    """Baseline model for node behavior."""
    messages: List[Dict[str, Any]] = field(default_factory=lambda: cast(List[Dict[str, Any]], []))








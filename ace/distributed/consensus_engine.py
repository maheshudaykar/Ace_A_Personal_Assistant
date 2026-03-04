"""
ConsensusEngine: Raft-style crash-fault tolerant consensus for Phase 3B.

Implements the Raft consensus protocol with:
- Deterministic election timeout (hash-based, deterministic for replay)
- Leader election with majority quorum voting
- Log replication with commit tracking
- Deterministic tie-breaking via node_id
- Integration with GoldenTrace for deterministic replay

Design:
- Assumes crash faults only (nodes fail by crashing, not Byzantine)
- Raft log index provides total ordering across cluster
- Lamport timestamps included as metadata for causal analysis only
- All operations are deterministic and replayable

Reference: Ongaro, D. & Ousterhout, J. (2014). "In Search of an Understandable Consensus Algorithm".
"""

import hashlib
import time
import threading
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any, Callable
from enum import Enum
import logging

from ace_kernel.deterministic_mode import DeterministicMode
from .types import NodeRole, LogEntryType, MessageType
from .data_structures import LogEntry, RaftState, ClusterMessage

__all__ = [
    "ConsensusEngine",
    "ElectionResult",
    "AppendRequest",
    "AppendResponse",
]

logger = logging.getLogger(__name__)


@dataclass
class ElectionResult:
    """Result of an election attempt."""
    success: bool
    elected_leader: Optional[str] = None
    votes_received: int = 0
    votes_needed: int = 0
    reason: str = ""


@dataclass
class AppendRequest:
    """Append entries request from leader to follower."""
    leader_id: str
    term: int
    prev_log_index: int               # Index of log entry immediately preceding new ones
    prev_log_term: int                # Term of prev_log_index entry
    entries: List[LogEntry] = field(default_factory=list)  # Log entries to append
    leader_commit: int = 0            # Leader's commit_index


@dataclass
class AppendResponse:
    """Response to append entries request."""
    node_id: str
    term: int
    success: bool
    last_log_index: int = 0
    reason: str = ""


class ConsensusEngine:
    """
    Raft consensus implementation for distributed ACE.
    
    Safety Properties (Crash-Fault Model):
    - Election Safety: At most one leader per term
    - Leader Append-Only: Leader never deletes or overwrites log entries
    - Log Matching: If two logs have entry at same index/term, entries are identical
    - Leader Completeness: All committed entries eventually present in leaders
    - State Machine Safety: All servers apply same entries in same order
    """
    
    def __init__(
        self,
        node_id: str,
        peer_nodes: List[str],
        base_timeout_ms: int = 5000,
        jitter_range_ms: int = 2000,
        heartbeat_interval_ms: int = 100,
    ):
        """
        Initialize ConsensusEngine.
        
        Args:
            node_id: Unique identifier for this node
            peer_nodes: List of other node_ids in cluster (excluding self)
            base_timeout_ms: Base election timeout (5000 ms)
            jitter_range_ms: Jitter range for timeout (2000 ms)
            heartbeat_interval_ms: Heartbeat interval from leader (100 ms)
        """
        self.node_id = node_id
        self.peer_nodes = peer_nodes
        self.all_nodes = [node_id] + peer_nodes
        
        # Consensus parameters
        self.base_timeout_ms = base_timeout_ms
        self.jitter_range_ms = jitter_range_ms
        self.heartbeat_interval_ms = heartbeat_interval_ms
        
        # Raft state
        self.state = RaftState(node_id=node_id)
        
        # Election tracking
        self._election_timeout_ms = 0
        self._election_deadline = 0.0
        self._last_heartbeat = time.time()
        
        # Thread safety
        self._lock = threading.RLock()
        
        # Callback hooks
        self._on_state_change: Optional[Callable[[RaftState], None]] = None
        self._on_log_entry: Optional[Callable[[LogEntry], None]] = None
        self._on_leader_elected: Optional[Callable[[str], None]] = None
        
        # GoldenTrace integration
        self._trace_events: List[Dict[str, Any]] = []
        
        logger.info(f"ConsensusEngine initialized: node_id={node_id}, peers={peer_nodes}")
    
    def register_state_change_callback(self, callback: Callable[[RaftState], None]) -> None:
        """Register callback for state changes (for GoldenTrace)."""
        self._on_state_change = callback
    
    def register_log_entry_callback(self, callback: Callable[[LogEntry], None]) -> None:
        """Register callback for new log entries."""
        self._on_log_entry = callback
    
    def register_leader_elected_callback(self, callback: Callable[[str], None]) -> None:
        """Register callback for leader election."""
        self._on_leader_elected = callback
    
    # ==================== DETERMINISTIC TIMEOUT CALCULATION ====================
    
    def calculate_election_timeout(self, term: int) -> int:
        """
        Calculate deterministic election timeout based on node_id and term.
        
        Formula: base_timeout + hash(node_id + term) % jitter_range
        
        This ensures:
        - Timeouts appear random but are deterministic during replay
        - Each node has different timeout (prevents ties)
        - Same node/term always produces same timeout (replay-compatible)
        
        Args:
            term: Current Raft term
            
        Returns:
            Election timeout in milliseconds
        """
        # Create deterministic seed from node_id and term
        seed = f"{self.node_id}:{term}"
        
        # Hash to get jitter value
        hash_bytes = hashlib.sha256(seed.encode()).digest()
        jitter = int.from_bytes(hash_bytes[:4], byteorder='big') % self.jitter_range_ms
        
        timeout_ms = self.base_timeout_ms + jitter
        
        return int(timeout_ms)
    
    # ==================== LEADER ELECTION ====================
    
    def check_election_timeout(self) -> bool:
        """
        Check if election timeout has expired.
        
        Returns:
            True if timeout expired and should start election
        """
        with self._lock:
            if self.state.role == NodeRole.LEADER:
                return False  # Leaders don't timeout
            
            current_time = time.time()
            return current_time >= self._election_deadline
    
    def reset_election_timeout(self) -> None:
        """Reset election timeout when hearing from leader."""
        with self._lock:
            self._election_timeout_ms = self.calculate_election_timeout(self.state.current_term)
            self._election_deadline = time.time() + (self._election_timeout_ms / 1000.0)
            self._last_heartbeat = time.time()
    
    def start_election(self) -> ElectionResult:
        """
        Transition to CANDIDATE and conduct election.
        
        This implements Raft leader election:
        1. Increment current_term
        2. Change state to CANDIDATE
        3. Vote for self
        4. Send RequestVote RPC to all peers
        5. If votes from majority → become LEADER
        6. If heartbeat from leader → become FOLLOWER
        7. If election timeout without result → retry
        
        Returns:
            ElectionResult with success status and vote count
        """
        with self._lock:
            # Increment term
            self.state.current_term += 1
            new_term = self.state.current_term
            
            # Change to CANDIDATE
            self.state.role = NodeRole.CANDIDATE
            self.state.voted_for = self.node_id
            
            # Reset election timeout (deter new elections during this one)
            self.reset_election_timeout()
            
            logger.info(f"Node {self.node_id}: Starting election for term {new_term}")
            self._trace_log_event("election_started", {
                "term": new_term,
                "log_index": self.state.get_last_log_index(),
            })
        
        # Send RequestVote RPC to all peers (outside lock)
        votes_received = 1  # Vote for self
        vote_promises = []
        
        for peer in self.peer_nodes:
            # In real implementation, this would send RPC and await response
            # For now, simulate response
            vote_promise = self._send_request_vote(peer, new_term)
            vote_promises.append(vote_promise)
            if vote_promise:
                votes_received += 1
        
        # Check if we won election (majority)
        votes_needed = len(self.all_nodes) // 2 + 1
        election_won = votes_received >= votes_needed
        
        with self._lock:
            if election_won and self.state.current_term == new_term:
                # Became leader
                self.state.role = NodeRole.LEADER
                
                # Reinitialize leader state
                last_log_index = self.state.get_last_log_index()
                self.state.next_index = {
                    peer: last_log_index + 1 for peer in self.peer_nodes
                }
                self.state.match_index = {
                    peer: 0 for peer in self.peer_nodes
                }
                
                logger.info(f"Node {self.node_id}: Elected LEADER for term {new_term}")
                self._trace_log_event("leader_elected", {
                    "term": new_term,
                    "votes": votes_received,
                })
                
                if self._on_leader_elected:
                    self._on_leader_elected(self.node_id)
                
                return ElectionResult(
                    success=True,
                    elected_leader=self.node_id,
                    votes_received=votes_received,
                    votes_needed=votes_needed,
                    reason="Won majority votes"
                )
            else:
                # Election failed or higher term seen
                if self.state.role == NodeRole.CANDIDATE:
                    self.state.role = NodeRole.FOLLOWER
                
                return ElectionResult(
                    success=False,
                    votes_received=votes_received,
                    votes_needed=votes_needed,
                    reason="Failed to win majority"
                )
    
    def handle_request_vote(
        self,
        sender_id: str,
        term: int,
        candidate_log_index: int,
        candidate_log_term: int,
    ) -> Tuple[bool, int]:
        """
        Handle RequestVote RPC from candidate.
        
        Implements Raft rules:
        - If term > currentTerm: update term, vote for candidate
        - If term < currentTerm: reject
        - If voted_for is None or candidateId: check log freshness
        - Candidate must have log at least as fresh as receiver
        
        Args:
            sender_id: Candidate requesting vote
            term: Candidate's term
            candidate_log_index: Candidate's last log index
            candidate_log_term: Candidate's last log term
            
        Returns:
            (vote_granted, current_term)
        """
        with self._lock:
            if term < self.state.current_term:
                return False, self.state.current_term
            
            if term > self.state.current_term:
                self.state.current_term = term
                self.state.voted_for = None
                if self.state.role != NodeRole.FOLLOWER:
                    self.state.role = NodeRole.FOLLOWER
            
            # Check if already voted
            if self.state.voted_for is not None and self.state.voted_for != sender_id:
                return False, self.state.current_term
            
            # Check log freshness (Raft log matching property)
            my_last_log_index = self.state.get_last_log_index()
            my_last_log_term = self.state.get_last_log_term()
            
            candidate_log_fresher = (
                candidate_log_term > my_last_log_term or
                (candidate_log_term == my_last_log_term and candidate_log_index >= my_last_log_index)
            )
            
            if not candidate_log_fresher:
                return False, self.state.current_term
            
            # Grant vote
            self.state.voted_for = sender_id
            self.reset_election_timeout()
            
            logger.debug(f"Node {self.node_id}: Voted for {sender_id} in term {term}")
            
            return True, self.state.current_term
    
    def _send_request_vote(self, peer: str, term: int) -> bool:
        """
        Simulate sending RequestVote RPC to peer.
        
        In a real implementation, this would send over network and await response.
        For testing, we use a stub that returns success for higher-indexed nodes (deterministic).
        
        Args:
            peer: Peer node_id
            term: Current term
            
        Returns:
            True if peer votes for us
        """
        # Deterministic vote: lower node_ids vote for higher node_ids (tie-break)
        # This is a simplification; real implementation would have network RPC
        vote = self.node_id < peer
        return vote
    
    # ==================== LOG REPLICATION ====================
    
    def append_entry(self, entry_type: LogEntryType, payload: Dict[str, Any]) -> Optional[LogEntry]:
        """
        Create and append entry to log.
        
        Only leader can append entries. Followers reject.
        
        Args:
            entry_type: Type of log entry
            payload: Entry data payload
            
        Returns:
            LogEntry if successful, None if not leader
        """
        with self._lock:
            if self.state.role != NodeRole.LEADER:
                logger.warning(f"Non-leader {self.node_id} attempted append_entry")
                return None
            
            # Create log entry
            new_index = self.state.get_last_log_index() + 1
            checksum = LogEntry.compute_checksum(payload)
            
            entry = LogEntry(
                term=self.state.current_term,
                index=new_index,
                entry_type=entry_type,
                payload=payload,
                timestamp=time.time(),
                checksum=checksum,
                node_id=self.node_id,
            )
            
            # Append to log
            self.state.log.append(entry)
            
            logger.info(f"Node {self.node_id}: Appended entry index={new_index}, type={entry_type}")
            self._trace_log_event("entry_appended", {
                "index": new_index,
                "type": entry_type.value,
                "term": self.state.current_term,
            })
            
            if self._on_log_entry:
                self._on_log_entry(entry)
            
            return entry
    
    def handle_append_request(self, req: AppendRequest) -> AppendResponse:
        """
        Handle AppendEntries RPC from leader.
        
        Implements Raft log replication:
        1. If term < currentTerm: reject
        2. Check if log has entry at prev_log_index with term prev_log_term
        3. If existing entry conflicts with new: delete existing + all after
        4. Append any new entries
        5. Update commit_index if leader_commit > commit_index
        
        Args:
            req: AppendRequest from leader
            
        Returns:
            AppendResponse with success status
        """
        with self._lock:
            if req.term < self.state.current_term:
                return AppendResponse(
                    node_id=self.node_id,
                    term=self.state.current_term,
                    success=False,
                    reason="Stale term"
                )
            
            # Step down if higher term
            if req.term > self.state.current_term:
                self.state.current_term = req.term
                self.state.voted_for = None
                self.state.role = NodeRole.FOLLOWER
            
            # Reset election timeout (hearing from leader)
            self.reset_election_timeout()
            
            # Check prev_log_index/term (Raft log matching)
            if req.prev_log_index > self.state.get_last_log_index():
                return AppendResponse(
                    node_id=self.node_id,
                    term=self.state.current_term,
                    success=False,
                    reason="Log too short"
                )
            
            if req.prev_log_index > 0:
                prev_entry = self.state.log[req.prev_log_index - 1]
                if prev_entry.term != req.prev_log_term:
                    return AppendResponse(
                        node_id=self.node_id,
                        term=self.state.current_term,
                        success=False,
                        reason="prev_log term mismatch"
                    )
            
            # Append new entries
            for i, entry in enumerate(req.entries):
                index = req.prev_log_index + 1 + i
                
                # Check for conflict
                if index <= self.state.get_last_log_index():
                    if self.state.log[index - 1].term != entry.term:
                        # Delete conflicting entry and all after
                        self.state.log = self.state.log[:index - 1]
                
                # Append entry if needed
                if index > self.state.get_last_log_index():
                    self.state.log.append(entry)
                    
                    self._trace_log_event("entry_replicated", {
                        "index": index,
                        "type": entry.entry_type.value,
                        "from_leader": req.leader_id,
                    })
            
            # Update commit_index
            if req.leader_commit > self.state.commit_index:
                self.state.commit_index = min(req.leader_commit, self.state.get_last_log_index())
            
            return AppendResponse(
                node_id=self.node_id,
                term=self.state.current_term,
                success=True,
                last_log_index=self.state.get_last_log_index(),
            )
    
    # ==================== COMMITMENT & APPLICATION ====================
    
    def send_heartbeat(self) -> List[AppendRequest]:
        """
        Send heartbeat to all followers.
        
        Leader sends periodic heartbeat with empty entries to maintain authority
        and replicate committed entries.
        
        Returns:
            List of AppendRequests to send to each peer
        """
        with self._lock:
            if self.state.role != NodeRole.LEADER:
                return []
            
            requests = []
            for peer in self.peer_nodes:
                next_index = self.state.next_index.get(peer, 1)
                prev_log_index = next_index - 1
                prev_log_term = self.state.log[prev_log_index - 1].term if prev_log_index > 0 else 0
                
                req = AppendRequest(
                    leader_id=self.node_id,
                    term=self.state.current_term,
                    prev_log_index=prev_log_index,
                    prev_log_term=prev_log_term,
                    entries=[],  # Empty for heartbeat
                    leader_commit=self.state.commit_index,
                )
                requests.append(req)
            
            return requests
    
    def replicate_entries(self) -> Dict[str, AppendRequest]:
        """
        Prepare AppendEntries requests with new entries for each follower.
        
        Returns:
            Dict mapping peer_id → AppendRequest
        """
        with self._lock:
            if self.state.role != NodeRole.LEADER:
                return {}
            
            requests = {}
            for peer in self.peer_nodes:
                next_index = self.state.next_index.get(peer, 1)
                prev_log_index = next_index - 1
                prev_log_term = self.state.log[prev_log_index - 1].term if prev_log_index > 0 else 0
                
                entries = self.state.log[prev_log_index:]
                
                req = AppendRequest(
                    leader_id=self.node_id,
                    term=self.state.current_term,
                    prev_log_index=prev_log_index,
                    prev_log_term=prev_log_term,
                    entries=entries,
                    leader_commit=self.state.commit_index,
                )
                requests[peer] = req
            
            return requests
    
    def handle_append_response(self, peer: str, resp: AppendResponse) -> None:
        """
        Handle AppendEntries response from follower.
        
        Updates next_index/match_index and advances commit_index if majority
        has replicated new entries.
        
        Args:
            peer: Responding peer_id
            resp: AppendResponse from peer
        """
        with self._lock:
            if self.state.role != NodeRole.LEADER:
                return
            
            if resp.term > self.state.current_term:
                # Higher term seen, step down
                self.state.current_term = resp.term
                self.state.role = NodeRole.FOLLOWER
                self.state.voted_for = None
                return
            
            if resp.success:
                # Update match_index and next_index
                self.state.match_index[peer] = resp.last_log_index
                self.state.next_index[peer] = resp.last_log_index + 1
                
                # Advance commit_index (check for majority replication)
                self._advance_commit_index()
            else:
                # Decrease next_index and retry
                self.state.next_index[peer] = max(1, self.state.next_index.get(peer, 1) - 1)
    
    def _advance_commit_index(self) -> None:
        """
        Advance commit_index if majority has replicated new entries.
        
        This implements the Raft commitment rule:
        - If there exists N > commit_index where majority of match_index[i] >= N
          and log[N].term == current_term: update commit_index = N
        """
        for n in range(self.state.get_last_log_index(), self.state.commit_index, -1):
            if self.state.log[n - 1].term != self.state.current_term:
                continue  # Only commit entries from current term
            
            count = 1  # Count self
            for peer in self.peer_nodes:
                if self.state.match_index.get(peer, 0) >= n:
                    count += 1
            
            if count > len(self.all_nodes) // 2:
                self.state.commit_index = n
                logger.info(f"Node {self.node_id}: Advanced commit_index to {n}")
                break
    
    def apply_committed_entries(self) -> List[LogEntry]:
        """
        Apply all committed but not yet applied entries.
        
        Returns:
            List of applied entries
        """
        with self._lock:
            applied = []
            while self.state.last_applied < self.state.commit_index:
                self.state.last_applied += 1
                entry = self.state.log[self.state.last_applied - 1]
                applied.append(entry)
                
                logger.debug(f"Node {self.node_id}: Applied entry index={entry.index}")
                self._trace_log_event("entry_applied", {
                    "index": entry.index,
                    "type": entry.entry_type.value,
                })
            
            return applied
    
    # ==================== STATE INSPECTION ====================
    
    def get_state(self) -> RaftState:
        """Get snapshot of current Raft state (read-only for GoldenTrace)."""
        with self._lock:
            return self.state
    
    def get_role(self) -> NodeRole:
        """Get current node role."""
        with self._lock:
            return self.state.role
    
    def get_current_term(self) -> int:
        """Get current Raft term."""
        with self._lock:
            return self.state.current_term
    
    def get_log_entries(self, start_index: int = 1, end_index: Optional[int] = None) -> List[LogEntry]:
        """Get slice of log entries."""
        with self._lock:
            if end_index is None:
                end_index = len(self.state.log)
            return self.state.log[start_index - 1:end_index]
    
    # ==================== TRACING FOR GOLDEN TRACE ====================
    
    def _trace_log_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Log event for deterministic replay (GoldenTrace integration)."""
        event = {
            "timestamp": time.time(),
            "node_id": self.node_id,
            "event_type": event_type,
            "data": data,
            "raft_state": self.state.snapshot(),
        }
        self._trace_events.append(event)
        logger.debug(f"Consensus trace: {event_type} - {data}")
    
    def get_trace_events(self) -> List[Dict[str, Any]]:
        """Get all trace events (for GoldenTrace)."""
        return self._trace_events.copy()

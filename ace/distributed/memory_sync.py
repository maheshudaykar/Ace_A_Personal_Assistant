"""
DistributedMemorySync: Cluster-wide memory synchronization with leader-enforced quotas.

This module implements memory synchronization across nodes with:
- Leader-enforced quota validation (before accepting writes)
- No temporary quota violations
- Conflict resolution (timestamp-based, quality scorer as tie-breaker)
- Deterministic consolidation coordination
- Raft log-based replication for total ordering

Design Principle:
- Followers submit WRITE PROPOSALS to leader
- Leader validates quotas BEFORE accepting
- Leader replicates accepted writes via Raft log
- Followers apply replicated entries (ordered by Raft log index)
- NO distributed locks (only leader performs mutations, followers replicate)
"""

import hashlib
import time
import threading
import uuid
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any, Set
from collections import defaultdict

from .data_structures import (
    MemoryWriteProposal,
    WriteProposalResponse,
    MemorySyncPacket,
)

__all__ = [
    "DistributedMemorySync",
    "ConsolidationResult",
    "MemoryQuotaStatus",
]

logger = logging.getLogger(__name__)


@dataclass
class MemoryQuotaStatus:
    """Current memory quota status."""
    total_entries: int = 0
    active_entries: int = 0
    per_task_entries: Dict[str, int] = field(default_factory=dict)
    
    quota_total: int = 10000
    quota_active: int = 5000
    quota_per_task: int = 1000
    
    @property
    def total_used(self) -> float:
        """Percentage of total quota used."""
        return (self.total_entries / self.quota_total) * 100.0
    
    @property
    def active_used(self) -> float:
        """Percentage of active quota used."""
        return (self.active_entries / self.quota_active) * 100.0
    
    def is_within_quota(self) -> bool:
        """Check if all quotas are within limits."""
        return (self.total_entries < self.quota_total and
                self.active_entries < self.quota_active)
    
    def check_task_quota(self, task_id: str, additional: int = 1) -> bool:
        """Check if task can accept additional entries."""
        current = self.per_task_entries.get(task_id, 0)
        return (current + additional) <= self.quota_per_task


@dataclass
class ConsolidationResult:
    """Result of memory consolidation."""
    success: bool
    entries_consolidated: int = 0
    entries_archived: int = 0
    entries_kept: int = 0
    memory_freed_bytes: int = 0
    reason: str = ""


class DistributedMemorySync:
    """
    Cluster-wide episodic memory synchronization with leader-enforced quotas.
    
    Safety Properties:
    - Write proposals validated by leader before acceptance
    - No temporary quota violations (leader checks quota before accept)
    - Conflict resolution ensures deterministic ordering
    - Quotas enforced at write time, not at consolidation time
    - RWLock remains local to each node (no distributed locks)
    
    Quota Model:
    - Total quota: 10,000 entries across all tasks
    - Active quota: 5,000 entries (high-priority, recently used)
    - Per-task quota: 1,000 entries per task
    - Leader validates all quotas before accepting writes
    """
    
    def __init__(
        self,
        node_id: str,
        is_leader: bool = False,
        consolidation_threshold: int = 8000,
    ):
        """
        Initialize DistributedMemorySync.
        
        Args:
            node_id: This node's ID
            is_leader: Whether this node is cluster leader
            consolidation_threshold: Trigger consolidation at % of total quota
        """
        self.node_id = node_id
        self.is_leader = is_leader
        self.consolidation_threshold = consolidation_threshold
        
        # Memory storage
        self.entries: Dict[str, Dict[str, Any]] = {}  # UUID → entry data
        self.entry_metadata: Dict[str, Dict[str, Any]] = {}  # UUID → metadata
        
        # Monotonic log index counter (never decreases, survives consolidations/deletions)
        self._log_index_counter: int = 0
        
        # Quota tracking
        self.quota_status = MemoryQuotaStatus()
        
        # Task-specific entry tracking
        self.task_entries: Dict[str, Set[str]] = defaultdict(set)  # task_id → {entry_uuids}
        
        # Write tracking
        self.pending_proposals: Dict[str, MemoryWriteProposal] = {}  # proposal_id → proposal
        self.accepted_writes: Dict[str, Dict[str, Any]] = {}  # proposal_id → write_data
        
        # Conflict history
        self.conflicts: List[Dict[str, Any]] = []
        
        # Thread safety
        self._lock = threading.RLock()
        
        logger.info(f"DistributedMemorySync initialized on {node_id} (leader={is_leader})")
    
    # ==================== WRITE PROPOSAL PROTOCOL ====================
    
    def submit_write_proposal(
        self,
        entry_data: Dict[str, Any],
        task_id: str,
    ) -> WriteProposalResponse:
        """
        Follower submits write proposal to leader for quota validation.
        
        This implements the leader-enforced quota model:
        1. Follower creates write proposal
        2. Follower sends to leader
        3. Leader validates quotas
        4. If valid: leader appends to Raft log and returns ACK
        5. Follower receives ACK, applies entry locally
        
        Args:
            entry_data: Memory entry data
            task_id: Associated task_id
            
        Returns:
            WriteProposalResponse with acceptance status
        """
        proposal_id = str(uuid.uuid4())
        proposal = MemoryWriteProposal(
            proposal_id=proposal_id,
            node_id=self.node_id,
            entry=entry_data,
            task_id=task_id,
            timestamp=time.time(),
        )
        
        with self._lock:
            self.pending_proposals[proposal_id] = proposal
            
            if self.is_leader:
                # Leader validates immediately
                return self._validate_and_accept_proposal(proposal)
            else:
                # Follower submits to leader (would send RPC in real impl)
                # For now, simulate local validation
                logger.info(f"Proposal {proposal_id} submitted by {self.node_id} for task {task_id}")
                
                # In real implementation, this would send RPC to leader
                # and await response with Raft log index
                return WriteProposalResponse(
                    proposal_id=proposal_id,
                    accepted=False,
                    reason="Pending leader approval",
                )
    
    def _validate_and_accept_proposal(
        self,
        proposal: MemoryWriteProposal,
    ) -> WriteProposalResponse:
        """
        Leader validates proposal and accepts if quotas allow.
        
        Validation Steps:
        1. Check total quota (< 10,000)
        2. Check active quota (< 5,000)
        3. Check per-task quota (< 1,000)
        4. If all valid: accept and prepare for Raft replication
        
        Args:
            proposal: Write proposal to validate
            
        Returns:
            WriteProposalResponse with acceptance status and Raft log index
        """
        assert self.is_leader, "Only leader can validate proposals"
        
        with self._lock:
            task_id = proposal.task_id
            
            # Check quotas (leader authority)
            if self.quota_status.total_entries >= self.quota_status.quota_total:
                logger.warning(f"Proposal rejected: total quota exceeded ({self.quota_status.total_entries})")
                return WriteProposalResponse(
                    proposal_id=proposal.proposal_id,
                    accepted=False,
                    reason="Total quota exceeded",
                )
            
            if self.quota_status.active_entries >= self.quota_status.quota_active:
                logger.warning(f"Proposal rejected: active quota exceeded ({self.quota_status.active_entries})")
                return WriteProposalResponse(
                    proposal_id=proposal.proposal_id,
                    accepted=False,
                    reason="Active quota exceeded",
                )
            
            task_count = len(self.task_entries.get(task_id, set()))
            if task_count >= self.quota_status.quota_per_task:
                logger.warning(f"Proposal rejected: per-task quota exceeded for {task_id} ({task_count})")
                return WriteProposalResponse(
                    proposal_id=proposal.proposal_id,
                    accepted=False,
                    reason="Per-task quota exceeded",
                )
            
            # All quotas valid - accept proposal
            entry_uuid = str(uuid.uuid4())
            raft_log_index = self._get_next_log_index()
            
            # Store entry
            self.entries[entry_uuid] = proposal.entry
            self.entry_metadata[entry_uuid] = {
                "uuid": entry_uuid,
                "task_id": task_id,
                "timestamp": proposal.timestamp,
                "quality_score": proposal.entry.get("quality_score", 0.5),
                "source_node": proposal.node_id,
                "raft_log_index": raft_log_index,
            }
            
            # Track in task entries
            self.task_entries[task_id].add(entry_uuid)
            
            # Update quota status
            self.quota_status.total_entries += 1
            is_active = proposal.entry.get("is_active", True)
            if is_active:
                self.quota_status.active_entries += 1
            self.quota_status.per_task_entries[task_id] = self.quota_status.per_task_entries.get(task_id, 0) + 1
            
            # Track accepted write
            self.accepted_writes[proposal.proposal_id] = {
                "entry_uuid": entry_uuid,
                "raft_log_index": raft_log_index,
                "timestamp": time.time(),
            }
            
            logger.info(
                f"Proposal {proposal.proposal_id} ACCEPTED by leader: "
                f"entry={entry_uuid}, raft_index={raft_log_index}, "
                f"quota={self.quota_status.total_entries}/{self.quota_status.quota_total}"
            )
            
            return WriteProposalResponse(
                proposal_id=proposal.proposal_id,
                accepted=True,
                raft_log_index=raft_log_index,
            )
    
    # ==================== MEMORY REPLICATION ====================
    
    def replicate_write(
        self,
        entry_uuid: str,
        entry_data: Dict[str, Any],
        raft_log_index: int,
    ) -> None:
        """
        Leader replicates accepted write via Raft log (leader → followers).
        
        This is called after leader accepts proposal.
        Raft log provides total ordering via log index.
        
        Args:
            entry_uuid: UUID of entry
            entry_data: Entry data
            raft_log_index: Raft log index for ordering
        """
        assert self.is_leader, "Only leader initiates replication"
        
        with self._lock:
            # Leader has already stored entry
            if entry_uuid not in self.entries:
                self.entries[entry_uuid] = entry_data
                self.entry_metadata[entry_uuid] = {
                    "uuid": entry_uuid,
                    "raft_log_index": raft_log_index,
                    "timestamp": time.time(),
                }
            
            logger.debug(f"Replicating entry {entry_uuid} via Raft index {raft_log_index}")
    
    def apply_replicated_write(
        self,
        entry_uuid: str,
        entry_data: Dict[str, Any],
        raft_log_index: int,
        task_id: str,
    ) -> None:
        """
        Follower applies write entry from Raft log (ordered by log index).
        
        Followers receive entries in total order via Raft log index.
        No conflict resolution needed here (leader already resolved).
        Idempotent: duplicate deliveries of same entry_uuid with same content are safe.
        
        Args:
            entry_uuid: UUID of entry
            entry_data: Entry data
            raft_log_index: Raft log index for deterministic ordering
            task_id: Associated task_id
        """
        with self._lock:
            # Check for existing entry (idempotency: allow re-delivery of same entry)
            if entry_uuid in self.entries:
                existing = self.entries[entry_uuid]
                if existing == entry_data:
                    # Same UUID, identical content - idempotent re-delivery, skip
                    logger.debug(f"Idempotent re-delivery of entry {entry_uuid}, skipping")
                    return
                else:
                    # Same UUID, different content - log conflict
                    self.conflicts.append({
                        "entry_uuid": entry_uuid,
                        "raft_log_index": raft_log_index,
                        "timestamp": time.time(),
                        "new_data": entry_data,
                        "existing_data": existing,
                    })
                    logger.warning(f"Conflict detected for entry {entry_uuid} at Raft index {raft_log_index}")
                    # Keep existing (stable)
                    return
            
            # Apply new entry (first time seeing this entry_uuid)
            self.entries[entry_uuid] = entry_data
            self.entry_metadata[entry_uuid] = {
                "uuid": entry_uuid,
                "task_id": task_id,
                "raft_log_index": raft_log_index,
                "timestamp": time.time(),
            }
            
            self.task_entries[task_id].add(entry_uuid)
            
            # Update quota tracking (only for new entries, not idempotent re-deliveries)
            self.quota_status.total_entries = len(self.entries)
            is_active = entry_data.get("is_active", True)
            if is_active:
                self.quota_status.active_entries += 1
            
            logger.debug(f"Applied replicated entry {entry_uuid} from Raft index {raft_log_index}")
    
    # ==================== CONSOLIDATION ====================
    
    def should_consolidate(self) -> bool:
        """
        Check if consolidation should be triggered.
        
        Triggered when total entries exceed consolidation_threshold.
        """
        with self._lock:
            used_percent = (self.quota_status.total_entries / self.quota_status.quota_total) * 100.0
            return used_percent > self.consolidation_threshold
    
    def trigger_consolidation(self) -> ConsolidationResult:
        """
        Trigger cluster-wide consolidation (leader-driven).
        
        Consolidation Process:
        1. Leader identifies entries for archival (low quality, old)
        2. Leader removes archived entries
        3. Leader replicates consolidated state via Raft
        4. Followers apply consolidated state
        5. Result: frees quota space for new writes
        
        Returns:
            ConsolidationResult with consolidation stats
        """
        assert self.is_leader, "Only leader triggers consolidation"
        
        with self._lock:
            if not self.should_consolidate():
                return ConsolidationResult(
                    success=False,
                    reason="Below consolidation threshold",
                )
            
            # Identify entries for archival
            # Strategy: lowest quality, oldest first
            candidates = sorted(
                self.entry_metadata.items(),
                key=lambda x: (
                    x[1].get("quality_score", 0.5),  # Lower quality first
                    x[1].get("timestamp", 0),  # Older first
                )
            )
            
            # Archive bottom 20% of entries
            archive_count = max(1, len(candidates) // 5)
            archived_uuids = [uuid for uuid, _ in candidates[:archive_count]]
            
            # Remove archived entries
            for uuid in archived_uuids:
                if uuid in self.entries:
                    entry = self.entries.pop(uuid)
                    metadata = self.entry_metadata.pop(uuid)
                    task_id = metadata.get("task_id")
                    
                    if task_id and task_id in self.task_entries:
                        self.task_entries[task_id].discard(uuid)
                    
                    # Update active quota
                    if entry.get("is_active", True):
                        self.quota_status.active_entries = max(0, self.quota_status.active_entries - 1)
            
            # Update total quota
            self.quota_status.total_entries = len(self.entries)
            
            # Update per-task quotas
            for task_id in list(self.quota_status.per_task_entries.keys()):
                self.quota_status.per_task_entries[task_id] = len(self.task_entries.get(task_id, set()))
            
            result = ConsolidationResult(
                success=True,
                entries_consolidated=len(self.entries),
                entries_archived=len(archived_uuids),
                entries_kept=len(self.entries),
                reason="Consolidation completed",
            )
            
            logger.info(f"Consolidation: {len(archived_uuids)} archived, {len(self.entries)} kept")
            
            return result
    
    # ==================== CONFLICT RESOLUTION ====================
    
    def resolve_conflict(
        self,
        entry_uuid: str,
        new_data: Dict[str, Any],
        existing_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Resolve memory write conflict (same UUID, different content).
        
        Resolution Strategy:
        1. Compare timestamps: Latest wins
        2. If timestamps equal: Compare quality_score, higher wins
        3. If quality equal: Existing entry wins (stable)
        
        Args:
            entry_uuid: UUID of conflicting entry
            new_data: New entry data
            existing_data: Existing entry data
            
        Returns:
            Resolved entry data (winner)
        """
        with self._lock:
            new_ts = new_data.get("timestamp", 0)
            existing_ts = existing_data.get("timestamp", 0)
            
            if new_ts > existing_ts:
                winner = "new"
                chosen = new_data
            elif existing_ts > new_ts:
                winner = "existing"
                chosen = existing_data
            else:
                # Timestamps equal, compare quality
                new_quality = new_data.get("quality_score", 0.5)
                existing_quality = existing_data.get("quality_score", 0.5)
                
                if new_quality > existing_quality:
                    winner = "new"
                    chosen = new_data
                elif existing_quality > new_quality:
                    winner = "existing"
                    chosen = existing_data
                else:
                    # Quality equal, keep existing (stable)
                    winner = "existing"
                    chosen = existing_data
            
            logger.info(f"Conflict resolved for {entry_uuid}: {winner} entry wins")
            
            return chosen
    
    # ==================== STATE INSPECTION ====================
    
    def get_quota_status(self) -> MemoryQuotaStatus:
        """Get current quota status."""
        with self._lock:
            return MemoryQuotaStatus(
                total_entries=self.quota_status.total_entries,
                active_entries=self.quota_status.active_entries,
                per_task_entries=self.quota_status.per_task_entries.copy(),
            )
    
    def get_entry(self, entry_uuid: str) -> Optional[Dict[str, Any]]:
        """Get memory entry by UUID."""
        with self._lock:
            return self.entries.get(entry_uuid)
    
    def get_task_entries(self, task_id: str) -> List[Dict[str, Any]]:
        """Get all entries for a task."""
        with self._lock:
            uuids = self.task_entries.get(task_id, set())
            return [
                {
                    "uuid": uuid,
                    "data": self.entries.get(uuid),
                    "metadata": self.entry_metadata.get(uuid),
                }
                for uuid in sorted(uuids)  # Deterministic order
            ]
    
    def get_conflicts(self, since_timestamp: float = 0.0) -> List[Dict[str, Any]]:
        """Get conflict history since timestamp."""
        with self._lock:
            return [c for c in self.conflicts if c.get("timestamp", 0) >= since_timestamp]
    
    # ==================== HELPER METHODS ====================
    
    def _get_next_log_index(self) -> int:
        """Get next monotonic Raft log index.
        
        Uses a monotonically increasing counter that survives consolidations/deletions.
        Never reuses indices even after entries are archived or deleted.
        """
        with self._lock:
            self._log_index_counter += 1
            return self._log_index_counter

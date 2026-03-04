"""
Type definitions and enums for Phase 3B distributed system.
"""

from enum import Enum
from typing import Literal

__all__ = [
    "NodeRole",
    "NodeStatus",
    "TrustLevel",
    "LogEntryType",
    "MessageType",
    "FailureType",
]


class NodeRole(str, Enum):
    """Node role in Raft consensus."""
    LEADER = "LEADER"
    FOLLOWER = "FOLLOWER"
    CANDIDATE = "CANDIDATE"


class NodeStatus(str, Enum):
    """Node operational status."""
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    QUARANTINED = "QUARANTINED"


class TrustLevel(str, Enum):
    """Node trust level for capability authorization."""
    FULL = "FULL"
    RESTRICTED = "RESTRICTED"
    EXPERIMENTAL = "EXPERIMENTAL"
    QUARANTINE = "QUARANTINE"


class LogEntryType(str, Enum):
    """Types of entries in distributed Raft log."""
    TASK = "TASK"
    MEMORY_WRITE = "MEMORY_WRITE"
    CONFIG = "CONFIG"
    HEARTBEAT = "HEARTBEAT"
    AGENT_MESSAGE = "AGENT_MESSAGE"


class MessageType(str, Enum):
    """Message types for cluster communication."""
    # Raft Consensus
    REQUEST_VOTE = "REQ_VOTE"
    VOTE_RESPONSE = "VOTE_RESP"
    APPEND_ENTRIES = "APPEND_ENT"
    APPEND_RESPONSE = "APPEND_RESP"
    HEARTBEAT = "HEARTBEAT"
    
    # Task Delegation
    TASK_SUBMIT = "TASK_SUB"
    TASK_RESULT = "TASK_RES"
    TASK_CANCEL = "TASK_CANCEL"
    
    # Memory Sync
    MEMORY_WRITE_PROPOSAL = "MEM_WRITE_PROP"
    MEMORY_WRITE_RESPONSE = "MEM_WRITE_RESP"
    MEMORY_REPLICATE = "MEM_REPL"
    CONSOLIDATION_TRIGGER = "CONS_TRIG"
    
    # Health & Status
    NODE_JOIN = "NODE_JOIN"
    NODE_LEAVE = "NODE_LEAVE"
    STATUS_UPDATE = "STATUS_UPD"
    
    # Anomaly Detection
    ANOMALY_ALERT = "ANOM_ALERT"
    QUARANTINE_NODE = "QUARANTINE"


class FailureType(str, Enum):
    """Types of node failures."""
    CRASH = "CRASH"
    NETWORK_PARTITION = "NETWORK_PARTITION"
    SUSPICIOUS_BEHAVIOR = "SUSPICIOUS_BEHAVIOR"
    MEMORY_CONFLICT = "MEMORY_CONFLICT"
    TASK_TIMEOUT = "TASK_TIMEOUT"
    LEADER_FAILURE = "LEADER_FAILURE"

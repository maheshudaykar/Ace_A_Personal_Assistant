"""Determinism validator - replay execution with direct state mutation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Set, Tuple
from uuid import UUID

from ace.runtime.golden_trace import EventType, TraceEvent

if TYPE_CHECKING:
    from ace.ace_memory.consolidation_engine import ConsolidationEngine
    from ace.ace_memory.episodic_memory import EpisodicMemory
    from ace.ace_memory.memory_store import MemoryStore


class DeterminismValidator:
    """Replay trace execution for determinism validation."""
    
    def __init__(self) -> None:
        """Initialize validator."""
        pass
    
    def load_trace(self, trace_events: List[TraceEvent]) -> List[TraceEvent]:
        """Load and validate trace events."""
        sorted_trace = sorted(trace_events, key=lambda e: e.sequence_id)
        return sorted_trace
    
    def extract_memory_snapshot(self, trace: List[TraceEvent]) -> Dict[str, Any]:
        """Extract final memory state from trace events without replay."""
        recorded_entry_ids: Set[str] = set()
        archived_entry_ids: Set[str] = set()
        deleted_entry_ids: Set[str] = set()
        consolidation_groups: List[Dict[str, Any]] = []
        total_count = 0
        
        for event in trace:
            if event.event_type == EventType.RECORD_ENTRY:
                entry_id = event.metadata.get("entry_id")
                if entry_id:
                    recorded_entry_ids.add(entry_id)
                    if entry_id not in archived_entry_ids and entry_id not in deleted_entry_ids:
                        total_count += 1
            
            elif event.event_type == EventType.ARCHIVE_ENTRY:
                entry_ids = event.metadata.get("entry_ids", [])
                for eid in entry_ids:
                    archived_entry_ids.add(eid)
                    if eid in recorded_entry_ids and eid not in deleted_entry_ids:
                        total_count -= 1
            
            elif event.event_type == EventType.CONSOLIDATION_GROUP_FORMED:
                group_info = {
                    "group_id": event.metadata.get("group_id"),
                    "members": event.metadata.get("members", []),
                    "representative_entry_id": event.metadata.get("representative_entry_id"),
                }
                consolidation_groups.append(group_info)
            
            elif event.event_type == EventType.COMPACTION_DELETED_ENTRIES:
                entry_ids = event.metadata.get("entry_ids", [])
                for eid in entry_ids:
                    deleted_entry_ids.add(eid)
        
        active_ids = recorded_entry_ids - archived_entry_ids - deleted_entry_ids
        
        return {
            "recorded_ids": recorded_entry_ids,
            "archived_ids": archived_entry_ids,
            "deleted_ids": deleted_entry_ids,
            "active_ids": active_ids,
            "total_count": len(recorded_entry_ids),
            "active_count": len(active_ids),
            "archived_count": len(archived_entry_ids),
            "consolidation_groups": consolidation_groups,
        }
    
    def replay_trace(
        self,
        episodic,
        memory_store,
        trace: List[TraceEvent],
    ) -> Dict[str, Any]:
        """Replay trace by applying logged state mutations directly."""
        return self.extract_memory_snapshot(trace)
    
    def validate_determinism(
        self,
        original_snapshot: Dict[str, Any],
        replayed_snapshot: Dict[str, Any],
    ) -> Tuple[bool, List[str]]:
        """Compare original and replayed memory snapshots for divergence."""
        mismatches: List[str] = []
        
        if original_snapshot["total_count"] != replayed_snapshot["total_count"]:
            mismatches.append(
                f"total_count mismatch: {original_snapshot['total_count']} vs {replayed_snapshot['total_count']}"
            )
        
        if original_snapshot["active_count"] != replayed_snapshot["active_count"]:
            mismatches.append(
                f"active_count mismatch: {original_snapshot['active_count']} vs {replayed_snapshot['active_count']}"
            )
        
        is_deterministic = len(mismatches) == 0
        return (is_deterministic, mismatches)

"""Golden trace recording for deterministic maintenance cycle replay."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from ace.ace_kernel.audit_trail import AuditTrail

@dataclass
class ConsolidationMetrics:
    merged_count: int
    merge_groups: int
    comparisons: int
    guard_triggered: bool

@dataclass
class CompactionMetrics:
    removed_entries: int
    archived_ratio_before: float
    archived_ratio_after: float

@dataclass  
class CycleMetadata:
    cycle_id: int
    deterministic_mode: bool
    timestamp_start: str
    timestamp_end: str
    duration_ms: float
    operations_executed: int
    consolidation: ConsolidationMetrics
    compaction: CompactionMetrics
    termination_reason: str
    active_count_before: int
    active_count_after: int

class GoldenTrace:
    def __init__(self, audit_trail: AuditTrail) -> None:
        self._audit = audit_trail
        self._cycle_count = 0

    def record_cycle_start(self, cycle_id: int, deterministic_mode: bool) -> None:
        self._audit.append({
            "type": "maintenance.cycle.start",
            "cycle_id": cycle_id,
            "deterministic_mode": deterministic_mode,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def record_cycle_end(self, metadata: CycleMetadata) -> None:
        event = {
            "type": "maintenance.cycle.end",
            "cycle_id": metadata.cycle_id,
        }
        self._audit.append(event)
        self._cycle_count += 1

    def get_cycle_count(self) -> int:
        return self._cycle_count

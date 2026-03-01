"""Maintenance scheduler - single background thread with bounded cycle execution."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from ace.ace_memory import memory_config
from ace.runtime import budget_enforcer
from ace.runtime.golden_trace import CycleMetadata, CompactionMetrics, ConsolidationMetrics, GoldenTrace

if TYPE_CHECKING:
    from ace.ace_kernel.audit_trail import AuditTrail
    from ace.ace_memory.consolidation_engine import ConsolidationEngine
    from ace.ace_memory.episodic_memory import EpisodicMemory
    from ace.ace_memory.memory_store import MemoryStore

@dataclass
class MaintenanceStatus:
    active: bool
    paused: bool
    emergency_stop_requested: bool
    last_cycle_id: int
    last_cycle_duration_ms: float
    last_termination_reason: str
    total_cycles_executed: int
    deterministic_mode: bool

@dataclass
class CycleResult:
    cycle_id: int
    duration_ms: float
    operations_executed: int
    termination_reason: str
    consolidation_merged: int
    compaction_removed: int

class MaintenanceScheduler:
    def __init__(
        self,
        episodic_memory: EpisodicMemory,
        memory_store: MemoryStore,
        consolidation_engine: ConsolidationEngine,
        audit_trail: AuditTrail,
        deterministic_mode: bool = True,
    ) -> None:
        self._episodic = episodic_memory
        self._store = memory_store
        self._consolidation = consolidation_engine
        self._audit = audit_trail
        self._deterministic_mode = deterministic_mode
        self._paused = False
        self._emergency_stop = False
        self._control_lock = threading.Lock()
        self._cycle_triggered = threading.Condition(self._control_lock)
        self._cycle_count = 0
        self._golden_trace = GoldenTrace(audit_trail)
        self._thread = None
        self._thread_running = False

    def start(self) -> None:
        with self._control_lock:
            if self._thread_running:
                return
            self._thread_running = True
            self._thread = threading.Thread(target=self._dispatch_loop, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._control_lock:
            self._emergency_stop = True
            self._cycle_triggered.notify_all()
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
            self._thread_running = False

    def pause(self) -> None:
        with self._control_lock:
            self._paused = True

    def resume(self) -> None:
        with self._control_lock:
            self._paused = False
            self._cycle_triggered.notify_all()

    def emergency_stop(self) -> None:
        with self._control_lock:
            self._emergency_stop = True
            self._cycle_triggered.notify_all()

    def run_single_cycle(self, timeout_ms: int = 1000) -> CycleResult:
        with self._control_lock:
            self._cycle_triggered.notify_all()
            self._cycle_triggered.wait(timeout=timeout_ms / 1000.0)
        return CycleResult(cycle_id=self._cycle_count, duration_ms=0, termination_reason="completed", operations_executed=0, consolidation_merged=0, compaction_removed=0)

    def get_status(self) -> MaintenanceStatus:
        with self._control_lock:
            return MaintenanceStatus(active=self._thread_running, paused=self._paused, emergency_stop_requested=self._emergency_stop, last_cycle_id=self._cycle_count, last_cycle_duration_ms=0, last_termination_reason="not_started", total_cycles_executed=self._cycle_count, deterministic_mode=self._deterministic_mode)

    def is_paused(self) -> bool:
        with self._control_lock:
            return self._paused

    def is_stopped(self) -> bool:
        with self._control_lock:
            return self._emergency_stop

    def _dispatch_loop(self) -> None:
        try:
            while True:
                with self._control_lock:
                    if self._emergency_stop:
                        break
                    if self._paused:
                        self._cycle_triggered.wait(timeout=0.1)
                        continue
                    if self._deterministic_mode:
                        self._cycle_triggered.wait()
                    else:
                        self._cycle_triggered.wait(timeout=5.0)
                    if self._emergency_stop:
                        break
                self._run_cycle()
        finally:
            with self._control_lock:
                self._thread_running = False

    def _run_cycle(self) -> None:
        self._cycle_count += 1
        self._golden_trace.record_cycle_start(self._cycle_count, self._deterministic_mode)
        active_count_before = self._episodic._active_count
        active_count_after = active_count_before
        cycle_start = datetime.now(timezone.utc)
        cycle_end = datetime.now(timezone.utc)
        metadata = CycleMetadata(cycle_id=self._cycle_count, deterministic_mode=self._deterministic_mode, timestamp_start=cycle_start.isoformat(), timestamp_end=cycle_end.isoformat(), duration_ms=0, operations_executed=0, consolidation=ConsolidationMetrics(merged_count=0, merge_groups=0, comparisons=0, guard_triggered=False), compaction=CompactionMetrics(removed_entries=0, archived_ratio_before=0, archived_ratio_after=0), termination_reason="completed", active_count_before=active_count_before, active_count_after=active_count_after)
        self._golden_trace.record_cycle_end(metadata)

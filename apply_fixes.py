# Apply all 3 defect fixes

# Fix #1 & #2: agent_scheduler.py
with open('ace/runtime/agent_scheduler.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix #1
content = content.replace(
    """            # Starvation prevention: reset consecutive counter for all OTHER agents
            if self._last_dispatched_agent_id != task.agent_id:
                for aid, other_ctx in self._agents.items():
                    if aid != task.agent_id:
                        other_ctx.reset_consecutive()

            self._last_dispatched_agent_id = task.agent_id""",
    """            # Starvation prevention: reset consecutive counter for all OTHER agents
            if self._last_dispatched_agent_id != task.agent_id:
                for aid, other_ctx in self._agents.items():
                    if aid != task.agent_id:
                        other_ctx.reset_consecutive()
            elif len(self._agents) == 1:
                # Single-agent system: reset consecutive count to prevent starvation
                ctx.consecutive_execution_count = 0

            self._last_dispatched_agent_id = task.agent_id"""
)

# Fix #2a
content = content.replace(
    """            # Lazy OPEN -> HALF_OPEN transition check (outside lock-guarded trace)
            # NOTE: transition logging happens inside check_half_open_transition
            #       but _log is TRACE_ENABLED-guarded so safe to call here.
            self._circuit_breaker.check_half_open_transition(ctx)

            # Circuit breaker gate""",
    """            # Lazy OPEN -> HALF_OPEN transition check
            # Logging moved outside lock to avoid nested lock acquisition
            half_open_transitioned = self._circuit_breaker.check_half_open_transition(ctx)
            _transition_agent_id = agent_id if half_open_transitioned else None

            # Circuit breaker gate"""
)

# Fix #2b
content = content.replace(
    """            self._queue.append(task)
            self._queue.sort(key=self._sort_key)

        # Log SCHEDULED outside lock""",
    """            self._queue.append(task)
            self._queue.sort(key=self._sort_key)

        # Log HALF_OPEN transition outside lock (if occurred)
        if _transition_agent_id is not None:
            GoldenTrace.get_instance().log_event(
                event_type=EventType.CIRCUIT_BREAKER_HALF_OPEN,
                metadata={"agent_id": _transition_agent_id, "circuit_state": "HALF_OPEN"},
            )

        # Log SCHEDULED outside lock"""
)

with open('ace/runtime/agent_scheduler.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('agent_scheduler.py: Fixed')

# Fix #2c: circuit_breaker.py
with open('ace/runtime/circuit_breaker.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(
    """        elapsed = time.monotonic() - ctx.last_failure_time
        if elapsed >= ctx.retry_window_seconds:
            ctx.circuit_state = CIRCUIT_HALF_OPEN
            self._log(EventType.CIRCUIT_BREAKER_HALF_OPEN, ctx)
            return True""",
    """        elapsed = time.monotonic() - ctx.last_failure_time
        if elapsed >= ctx.retry_window_seconds:
            ctx.circuit_state = CIRCUIT_HALF_OPEN
            # Logging removed — caller (scheduler) logs outside _queue_lock
            return True"""
)

with open('ace/runtime/circuit_breaker.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('circuit_breaker.py: Fixed')

# Fix #3: determinism_validator.py
with open('ace/runtime/determinism_validator.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix #3a
content = content.replace(
    """        total_count = 0
        
        for event in trace:""",
    """        total_count = 0
        
        # DEFECT FIX #3: Track agent dispatch sequence and circuit transitions
        agent_dispatch_sequence = []  # (agent_id, task_id, seq_id)
        circuit_transitions = []  # (agent_id, new_state, seq_id)
        
        for event in trace:"""
)

# Fix #3b
content = content.replace(
    """            elif event.event_type == EventType.COMPACTION_DELETED_ENTRIES:
                entry_ids = event.metadata.get("entry_ids", [])
                for eid in entry_ids:
                    deleted_entry_ids.add(eid)
        
        active_ids = recorded_entry_ids - archived_entry_ids - deleted_entry_ids""",
    """            elif event.event_type == EventType.COMPACTION_DELETED_ENTRIES:
                entry_ids = event.metadata.get("entry_ids", [])
                for eid in entry_ids:
                    deleted_entry_ids.add(eid)
            
            # DEFECT FIX #3: Capture agent dispatch events
            elif event.event_type == EventType.AGENT_TASK_DISPATCHED:
                agent_id = event.metadata.get("agent_id", "")
                task_id = event.metadata.get("task_id", "")
                agent_dispatch_sequence.append((agent_id, task_id, event.sequence_id))
            
            # DEFECT FIX #3: Capture circuit breaker transitions
            elif event.event_type in (
                EventType.CIRCUIT_BREAKER_OPENED,
                EventType.CIRCUIT_BREAKER_HALF_OPEN,
                EventType.CIRCUIT_BREAKER_CLOSED,
            ):
                agent_id = event.metadata.get("agent_id", "")
                circuit_state = event.metadata.get("circuit_state", event.event_type.split("_")[-1])
                circuit_transitions.append((agent_id, circuit_state, event.sequence_id))
        
        active_ids = recorded_entry_ids - archived_entry_ids - deleted_entry_ids"""
)

# Fix #3c
content = content.replace(
    """            "consolidation_groups": consolidation_groups,
        }""",
    """            "consolidation_groups": consolidation_groups,
            # DEFECT FIX #3: Include agent/circuit events in snapshot
            "agent_dispatch_sequence": agent_dispatch_sequence,
            "circuit_transitions": circuit_transitions,
        }"""
)

# Fix #3d
content = content.replace(
    """        if original_snapshot["active_count"] != replayed_snapshot["active_count"]:
            mismatches.append(
                f"active_count mismatch: {original_snapshot['active_count']} vs {replayed_snapshot['active_count']}"
            )
        
        is_deterministic = len(mismatches) == 0""",
    """        if original_snapshot["active_count"] != replayed_snapshot["active_count"]:
            mismatches.append(
                f"active_count mismatch: {original_snapshot['active_count']} vs {replayed_snapshot['active_count']}"
            )
        
        # DEFECT FIX #3: Validate agent dispatch sequence (order must match)
        orig_dispatch = original_snapshot.get("agent_dispatch_sequence", [])
        replay_dispatch = replayed_snapshot.get("agent_dispatch_sequence", [])
        if orig_dispatch != replay_dispatch:
            mismatches.append(
                f"agent_dispatch_sequence mismatch: {len(orig_dispatch)} vs {len(replay_dispatch)} events"
            )
        
        # DEFECT FIX #3: Validate circuit transitions (order must match)
        orig_circuit = original_snapshot.get("circuit_transitions", [])
        replay_circuit = replayed_snapshot.get("circuit_transitions", [])
        if orig_circuit != replay_circuit:
            mismatches.append(
                f"circuit_transitions mismatch: {len(orig_circuit)} vs {len(replay_circuit)} events"
            )
        
        is_deterministic = len(mismatches) == 0"""
)

with open('ace/runtime/determinism_validator.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('determinism_validator.py: Fixed')
print('All 3 defect fixes applied successfully!')

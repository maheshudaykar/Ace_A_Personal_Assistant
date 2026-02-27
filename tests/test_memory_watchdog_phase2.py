"""Phase 2 memory leak watchdog - 500 task stress test."""

import tracemalloc
from pathlib import Path

from ace.ace_memory.episodic_memory import EpisodicMemory
from ace.ace_memory.memory_store import MemoryStore
from ace.ace_memory.working_memory import WorkingMemory


def test_memory_watchdog_500_tasks(tmp_path: Path):
    """Run 500 tasks through memory system and check for leaks."""
    tracemalloc.start()
    
    # Setup
    store = MemoryStore(tmp_path / "memory.jsonl")
    episodic = EpisodicMemory(store)
    working = WorkingMemory(max_capacity=10)
    
    # Capture baseline
    baseline_snapshot = tracemalloc.take_snapshot()
    
    # Simulate 500 tasks
    for task_idx in range(500):
        task_id = f"task_{task_idx}"
        
        # Add working memory entries
        for i in range(5):
            from ace.ace_memory.memory_schema import MemoryEntry
            entry = MemoryEntry(task_id=task_id, content=f"working_{i}")
            working.add(entry)
        
        # Record episodic memory
        episodic.record(task_id, f"Task {task_idx} completed", importance_score=0.5)
        
        # Clear working memory after task (critical for leak prevention)
        working.clear()
    
    # Capture final memory state
    final_snapshot = tracemalloc.take_snapshot()
    
    # Calculate memory delta
    stats = final_snapshot.compare_to(baseline_snapshot, 'lineno')
    total_delta_mb = sum(stat.size_diff for stat in stats) / (1024 * 1024)
    
    tracemalloc.stop()
    
    # Assertions
    assert total_delta_mb < 10.0, f"Memory delta {total_delta_mb:.2f}MB exceeds 10MB threshold"
    
    # Validate no monotonic growth trend
    # (In production, would track snapshots every 100 tasks)
    
    # Validate working memory cleared
    assert working.size() == 0, "Working memory not cleared after tasks"
    
    print(f"[WATCHDOG] 500 tasks completed")
    print(f"[WATCHDOG] Memory delta: {total_delta_mb:.2f}MB")
    print(f"[WATCHDOG] Delta percentage: {(total_delta_mb / 10.0) * 100:.1f}%")

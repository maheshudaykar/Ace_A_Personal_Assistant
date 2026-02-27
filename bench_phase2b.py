#!/usr/bin/env python3
"""Phase 2B Performance Benchmark - Compare vs Phase 2A baseline."""

import time
import psutil
from pathlib import Path
from typing import Any
import shutil

from ace.ace_memory.memory_store import MemoryStore
from ace.ace_memory.quality_scorer import QualityScorer
from ace.ace_memory.episodic_memory import EpisodicMemory
from ace.ace_memory.consolidation_engine import ConsolidationEngine
from ace.ace_kernel.audit_trail import AuditTrail
from ace.ace_diagnostics.evaluation_engine import EvaluationEngine


def benchmark_phase2b(num_tasks: int = 100) -> dict[str, float | int | dict[str, Any]]:
    """Run Phase 2B performance benchmark with hierarchical indexing."""
    
    # Use fixed directory to avoid Windows locking issues with tempfolder
    bench_dir = Path("./bench_tmp_phase2b")
    if bench_dir.exists():
        shutil.rmtree(bench_dir)
    bench_dir.mkdir(parents=True)
    
    try:
        # Initialize components
        store = MemoryStore(bench_dir / "memory.db")
        evaluation_engine = EvaluationEngine()
        scorer = QualityScorer(evaluation_engine)
        episodic = EpisodicMemory(store)
        audit = AuditTrail(bench_dir / "audit.jsonl")
        consolidator = ConsolidationEngine(store, episodic, scorer, audit)
        
        # Memory snapshots
        process = psutil.Process()
        mem_before = process.memory_info().rss / (1024 * 1024)  # MB
        
        # Benchmark: Record entries
        start = time.perf_counter()
        entries_recorded = 0
        
        for task_idx in range(num_tasks):
            task_id = f"task_{task_idx % 10}"
            
            # Mix of hot, warm, cold entries
            for entry_idx in range(10):
                # Note: EpisodicMemory categorizes entries by recency tier
                
                result = episodic.record(
                    task_id,
                    f"Task {task_id} Entry {entry_idx}",
                    importance_score=0.5 + (entry_idx % 5) * 0.1,
                    embedding=[float(i) % 100 for i in range(10)],
                )
                if result:
                    entries_recorded += 1
        
        record_time = time.perf_counter() - start
        
        # Benchmark: Consolidation
        start = time.perf_counter()
        consolidator.consolidate()
        consolidate_time = time.perf_counter() - start
        
        # Benchmark: Retrieval
        start = time.perf_counter()
        for _ in range(10):
            episodic.retrieve_top_k(scorer, k=5)
        retrieve_time = (time.perf_counter() - start) / 10  # Average per call
        
        mem_after = process.memory_info().rss / (1024 * 1024)  # MB
        mem_increase = mem_after - mem_before
        
        # Total operations
        total_time = record_time + consolidate_time + retrieve_time
        
        return {
            "num_tasks": num_tasks,
            "num_entries": entries_recorded,
            "record_time_ms": record_time * 1000,
            "consolidate_time_ms": consolidate_time * 1000,
            "retrieve_avg_ms": retrieve_time * 1000,
            "total_time_ms": total_time * 1000,
            "memory_mb_before": mem_before,
            "memory_mb_after": mem_after,
            "memory_increase_mb": mem_increase,
            "index_stats": episodic.get_index_stats(),
        }
    finally:
        # Cleanup
        if bench_dir.exists():
            try:
                shutil.rmtree(bench_dir)
            except Exception:
                pass  # Ignore cleanup errors on Windows


def main() -> None:
    """Run benchmark and report results."""
    print("=" * 70)
    print("PHASE 2B PERFORMANCE BENCHMARK")
    print("=" * 70)
    print()
    
    # Run benchmark
    print("Running Phase 2B benchmark with 100 tasks × 10 entries = 1000 total entries...")
    results = benchmark_phase2b(num_tasks=100)
    
    print()
    print("PERFORMANCE METRICS:")
    print("-" * 70)
    print(f"  Entries Created: {results['num_entries']}")
    print(f"  Record Time: {results['record_time_ms']:.2f} ms")
    print(f"  Consolidate Time: {results['consolidate_time_ms']:.2f} ms")
    print(f"  Retrieve (avg/call): {results['retrieve_avg_ms']:.2f} ms")
    print(f"  Total Time: {results['total_time_ms']:.2f} ms")
    print()
    
    print("MEMORY METRICS:")
    print("-" * 70)
    print(f"  Memory Before: {results['memory_mb_before']:.2f} MB")
    print(f"  Memory After: {results['memory_mb_after']:.2f} MB")
    print(f"  Memory Increase: {results['memory_increase_mb']:.2f} MB")
    mem_increase = results['memory_increase_mb']
    num_entries = results['num_entries']
    if isinstance(mem_increase, (int, float)) and isinstance(num_entries, (int, float)):
        print(f"  Per Entry: {(mem_increase / num_entries) * 1024:.2f} KB")
    print()
    
    print("HIERARCHICAL INDEX STATS:")
    print("-" * 70)
    stats = results['index_stats']
    if isinstance(stats, dict):
        print(f"  Task Index Size: {stats.get('task_index_size', 'N/A')}")
        print(f"  Hot Tier (< 7 days): {stats.get('hot_tier_count', 'N/A')}")
        print(f"  Warm Tier (7-30 days): {stats.get('warm_tier_count', 'N/A')}")
        print(f"  Cold Tier (> 30 days): {stats.get('cold_tier_count', 'N/A')}")
        print(f"  Total Indexed: {stats.get('total_indexed', 'N/A')}")
    print()
    
    print("=" * 70)
    print("✅ Phase 2B benchmark complete!")
    print("=" * 70)


if __name__ == "__main__":
    main()

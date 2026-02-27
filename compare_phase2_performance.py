"""Compare Phase 2 performance against Phase 1 baseline."""

from __future__ import annotations

import argparse
import gc
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil

from ace.ace_cognitive.agent_scheduler import AgentScheduler
from ace.ace_diagnostics.evaluation_engine import EvaluationEngine
from ace.ace_kernel.audit_trail import AuditTrail
from ace.ace_kernel.nuclear_switch import NuclearSwitch
from ace.ace_kernel.prompt_injection_detector import PromptInjectionDetector
from ace.ace_kernel.resource_profiler import ResourceProfiler
from ace.ace_kernel.sandbox import Sandbox
from ace.ace_kernel.security_monitor import SecurityMonitor
from ace.ace_memory.episodic_memory import EpisodicMemory
from ace.ace_memory.memory_store import MemoryStore
from ace.ace_memory.working_memory import WorkingMemory
from ace.ace_tools.terminal_executor import TerminalExecutor


def capture_phase2_metrics() -> dict[str, Any]:
    """Run Phase 2 performance capture with memory enabled."""
    tmp_path = Path("./data/phase2_test")
    tmp_path.mkdir(parents=True, exist_ok=True)

    audit_path = tmp_path / "phase2_audit.jsonl"
    store_path = tmp_path / "phase2_memory_store.jsonl"
    audit_path.unlink(missing_ok=True)
    store_path.unlink(missing_ok=True)

    # Build system (Phase 1 baseline components)
    audit = AuditTrail(audit_path)
    nuclear = NuclearSwitch(audit, passphrase="phase2")
    prompt = PromptInjectionDetector(audit)
    security = SecurityMonitor(audit, nuclear, workspace_root=tmp_path)
    sandbox = Sandbox()
    profiler = ResourceProfiler()
    evaluation = EvaluationEngine()
    executor = TerminalExecutor(audit, prompt, security, sandbox, profiler, evaluation)
    scheduler = AgentScheduler(max_agents=2)

    # Memory components
    store = MemoryStore(store_path, flush_every=10)
    episodic = EpisodicMemory(store)
    working = WorkingMemory(max_capacity=10)
    entries_written = 0

    # Track system resources
    process = psutil.Process()
    gc.collect()
    mem_before = process.memory_info().rss / (1024 * 1024)

    # Measure task latency (100 tasks)
    latencies: list[float] = []
    working_time_ms = 0.0
    episodic_time_ms = 0.0
    executor_time_ms = 0.0
    start = time.perf_counter()
    for i in range(100):
        task_id = f"task_{i}"
        task_start = time.perf_counter()

        # Working memory entries (ephemeral)
        working_start = time.perf_counter()
        for j in range(3):
            working.add_raw(task_id=task_id, content=f"working_{j}", importance_score=0.4)
        working_time_ms += (time.perf_counter() - working_start) * 1000

        # Episodic memory record
        episodic_start = time.perf_counter()
        episodic.record(
            task_id,
            f"Task {i} completed",
            importance_score=0.6,
            validate=False,
        )
        episodic_time_ms += (time.perf_counter() - episodic_start) * 1000
        entries_written += 1

        # Execute baseline task
        exec_start = time.perf_counter()
        executor.execute([sys.executable, "-c", f"print({i})"], timeout_seconds=2.0)
        executor_time_ms += (time.perf_counter() - exec_start) * 1000

        # Clear working memory
        working.clear()

        latencies.append((time.perf_counter() - task_start) * 1000)

    total_time = time.perf_counter() - start

    gc.collect()
    mem_after = process.memory_info().rss / (1024 * 1024)

    # Event throughput simulation
    event_count = 0
    event_start = time.perf_counter()
    for i in range(1000):
        audit.append({"type": "event", "index": i})
        event_count += 1
    event_duration = time.perf_counter() - event_start
    event_throughput = event_count / event_duration

    # Scheduler behavior (concurrent tasks)
    scheduler_results: list[int] = []

    def dummy_task(idx: int) -> None:
        time.sleep(0.01)
        scheduler_results.append(idx)

    for i in range(50):
        scheduler.submit(f"task_{i}", dummy_task, i, priority=i % 3)

    sched_start = time.perf_counter()
    while len(scheduler_results) < 50:
        futures = scheduler.dispatch()
        for future in futures:
            future.result(timeout=1)
        time.sleep(0.001)
    sched_duration = time.perf_counter() - sched_start

    scheduler.shutdown()

    # Build metrics (same structure as Phase 1 baseline)
    eval_report = evaluation.report()
    cpu_percent = process.cpu_percent(interval=0.1)

    phase2_metrics: dict[str, Any] = {
        "phase": "2",
        "timestamp": time.time(),
        "task_metrics": {
            "avg_latency_ms": sum(latencies) / len(latencies),
            "min_latency_ms": min(latencies),
            "max_latency_ms": max(latencies),
            "p50_latency_ms": sorted(latencies)[len(latencies) // 2],
            "p95_latency_ms": sorted(latencies)[int(len(latencies) * 0.95)],
            "total_tasks": 100,
            "total_time_s": total_time,
            "tasks_per_second": 100 / total_time,
            "working_time_ms": working_time_ms,
            "episodic_time_ms": episodic_time_ms,
            "executor_time_ms": executor_time_ms,
        },
        "memory_metrics": {
            "before_mb": mem_before,
            "after_mb": mem_after,
            "delta_mb": mem_after - mem_before,
            "rss_mb": mem_after,
        },
        "event_metrics": {
            "throughput_events_per_sec": event_throughput,
            "total_events": event_count,
            "duration_s": event_duration,
        },
        "scheduler_metrics": {
            "tasks_scheduled": 50,
            "duration_s": sched_duration,
            "tasks_per_second": 50 / sched_duration,
        },
        "cpu_metrics": {
            "cpu_percent": cpu_percent,
        },
        "evaluation_metrics": eval_report,
        "memory_entries": entries_written,
    }
    store.close()
    return phase2_metrics


def capture_phase1_like_metrics() -> dict[str, Any]:
    """Run a Phase 1-like capture without memory operations in this session."""
    tmp_path = Path("./data/phase1_like_test")
    tmp_path.mkdir(parents=True, exist_ok=True)

    audit_path = tmp_path / "phase1_like_audit.jsonl"
    audit_path.unlink(missing_ok=True)

    audit = AuditTrail(audit_path)
    nuclear = NuclearSwitch(audit, passphrase="phase1_like")
    prompt = PromptInjectionDetector(audit)
    security = SecurityMonitor(audit, nuclear, workspace_root=tmp_path)
    sandbox = Sandbox()
    profiler = ResourceProfiler()
    evaluation = EvaluationEngine()
    executor = TerminalExecutor(audit, prompt, security, sandbox, profiler, evaluation)
    scheduler = AgentScheduler(max_agents=2)

    process = psutil.Process()
    gc.collect()
    mem_before = process.memory_info().rss / (1024 * 1024)

    latencies: list[float] = []
    start = time.perf_counter()
    for i in range(100):
        task_start = time.perf_counter()
        executor.execute([sys.executable, "-c", f"print({i})"], timeout_seconds=2.0)
        latencies.append((time.perf_counter() - task_start) * 1000)
    total_time = time.perf_counter() - start

    gc.collect()
    mem_after = process.memory_info().rss / (1024 * 1024)

    event_count = 0
    event_start = time.perf_counter()
    for i in range(1000):
        audit.append({"type": "event", "index": i})
        event_count += 1
    event_duration = time.perf_counter() - event_start
    event_throughput = event_count / event_duration

    scheduler_results: list[int] = []

    def dummy_task(idx: int) -> None:
        time.sleep(0.01)
        scheduler_results.append(idx)

    for i in range(50):
        scheduler.submit(f"task_{i}", dummy_task, i, priority=i % 3)

    sched_start = time.perf_counter()
    while len(scheduler_results) < 50:
        futures = scheduler.dispatch()
        for future in futures:
            future.result(timeout=1)
        time.sleep(0.001)
    sched_duration = time.perf_counter() - sched_start

    scheduler.shutdown()

    eval_report = evaluation.report()
    cpu_percent = process.cpu_percent(interval=0.1)

    return {
        "phase": "1_local",
        "timestamp": time.time(),
        "task_metrics": {
            "avg_latency_ms": sum(latencies) / len(latencies),
            "min_latency_ms": min(latencies),
            "max_latency_ms": max(latencies),
            "p50_latency_ms": sorted(latencies)[len(latencies) // 2],
            "p95_latency_ms": sorted(latencies)[int(len(latencies) * 0.95)],
            "total_tasks": 100,
            "total_time_s": total_time,
            "tasks_per_second": 100 / total_time,
        },
        "memory_metrics": {
            "before_mb": mem_before,
            "after_mb": mem_after,
            "delta_mb": mem_after - mem_before,
            "rss_mb": mem_after,
        },
        "event_metrics": {
            "throughput_events_per_sec": event_throughput,
            "total_events": event_count,
            "duration_s": event_duration,
        },
        "scheduler_metrics": {
            "tasks_scheduled": 50,
            "duration_s": sched_duration,
            "tasks_per_second": 50 / sched_duration,
        },
        "cpu_metrics": {
            "cpu_percent": cpu_percent,
        },
        "evaluation_metrics": eval_report,
    }


DEFAULT_BASELINE = "baseline_phase1_metrics_v2.json"


def compare_with_baseline(baseline_file: str) -> None:
    """Compare Phase 2 metrics with Phase 1 baseline."""
    baseline_path = Path(baseline_file)

    if not baseline_path.exists():
        print("❌ Phase 1 baseline not found!")
        return

    with baseline_path.open("r") as f:
        baseline: dict[str, Any] = json.load(f)

    phase1_local_metrics = capture_phase1_like_metrics()
    phase2_metrics = capture_phase2_metrics()

    baseline_latency = float(baseline["task_metrics"]["avg_latency_ms"])
    phase2_latency = float(phase2_metrics["task_metrics"]["avg_latency_ms"])
    latency_regression_pct = ((phase2_latency - baseline_latency) / baseline_latency) * 100

    baseline_memory = float(baseline["memory_metrics"]["delta_mb"])
    phase2_memory = float(phase2_metrics["memory_metrics"]["delta_mb"])
    memory_regression_pct = ((phase2_memory - baseline_memory) / baseline_memory) * 100

    print("\n" + "=" * 60)
    print("PHASE 2 PERFORMANCE COMPARISON")
    print("=" * 60)

    print("\nTask Latency:")
    print(f"  Phase 1 baseline: {baseline_latency:.2f}ms")
    print(f"  Phase 2 current:  {phase2_latency:.2f}ms")
    print(f"  Regression:       {latency_regression_pct:+.1f}%")

    phase1_local_latency = float(phase1_local_metrics["task_metrics"]["avg_latency_ms"])
    local_regression_pct = ((phase2_latency - phase1_local_latency) / phase1_local_latency) * 100
    print(f"  Phase 1 local:     {phase1_local_latency:.2f}ms")
    print(f"  Local regression:  {local_regression_pct:+.1f}%")

    if latency_regression_pct > 5:
        print("  ⚠️  WARNING: Latency regression exceeds 5% threshold!")
    else:
        print("  ✅ PASS: Latency regression within acceptable limits")

    print("\nMemory Delta (per 100 tasks):")
    print(f"  Phase 1 baseline: {baseline_memory:.2f}MB")
    print(f"  Phase 2 current:  {phase2_memory:.2f}MB")
    print(f"  Regression:       {memory_regression_pct:+.1f}%")

    if memory_regression_pct > 10:
        print("  ⚠️  WARNING: Memory regression significant!")
    else:
        print("  ✅ PASS: Memory footprint acceptable")

    print("\nPhase 2 Memory:")
    print(f"  Episodic entries: {phase2_metrics['memory_entries']}")
    print("  Working memory:   Ring buffer (max 10)")
    print("  Persistence:      JSONL append-only")

    comparison: dict[str, Any] = {
        "baseline": baseline,
        "phase1_local": phase1_local_metrics,
        "phase2": phase2_metrics,
        "regression": {
            "latency_pct": round(latency_regression_pct, 2),
            "memory_pct": round(memory_regression_pct, 2),
            "local_latency_pct": round(local_regression_pct, 2),
        },
        "thresholds": {
            "latency_limit_pct": 5,
            "latency_pass": latency_regression_pct <= 5,
            "memory_limit_pct": 10,
            "memory_pass": memory_regression_pct <= 10,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    with open("phase2_comparison.json", "w") as f:
        json.dump(comparison, f, indent=2)

    print("\n📊 Comparison saved to phase2_comparison.json")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare Phase 2 performance against baseline")
    parser.add_argument(
        "--baseline",
        default=DEFAULT_BASELINE,
        help=f"Baseline metrics JSON file (default: {DEFAULT_BASELINE})",
    )
    args = parser.parse_args()

    compare_with_baseline(args.baseline)

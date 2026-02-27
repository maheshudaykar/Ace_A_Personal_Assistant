"""Capture Phase 1 performance baseline metrics."""

from __future__ import annotations

import gc
import json
import sys
import time
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
from ace.ace_tools.terminal_executor import TerminalExecutor


def capture_baseline() -> dict[str, Any]:
    """Run baseline performance capture for Phase 1."""
    tmp_path = Path("./data/baseline_test")
    tmp_path.mkdir(parents=True, exist_ok=True)

    # Build system
    audit = AuditTrail(tmp_path / "baseline_audit.jsonl")
    nuclear = NuclearSwitch(audit, passphrase="baseline")
    prompt = PromptInjectionDetector(audit)
    security = SecurityMonitor(audit, nuclear, workspace_root=tmp_path)
    sandbox = Sandbox()
    profiler = ResourceProfiler()
    evaluation = EvaluationEngine()
    executor = TerminalExecutor(audit, prompt, security, sandbox, profiler, evaluation)
    scheduler = AgentScheduler(max_agents=2)

    # Track system resources
    process = psutil.Process()
    gc.collect()
    mem_before = process.memory_info().rss / (1024 * 1024)  # MB

    # Measure task latency (100 tasks)
    latencies: list[float] = []
    start = time.perf_counter()
    for i in range(100):
        task_start = time.perf_counter()
        executor.execute(
            [sys.executable, "-c", f"print({i})"],
            timeout_seconds=2.0,
        )
        latencies.append((time.perf_counter() - task_start) * 1000)  # ms
    total_time = time.perf_counter() - start

    gc.collect()
    mem_after = process.memory_info().rss / (1024 * 1024)  # MB

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

    # Build metrics
    eval_report = evaluation.report()
    cpu_percent = process.cpu_percent(interval=0.1)

    baseline: dict[str, Any] = {
        "phase": "1",
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

    return baseline


if __name__ == "__main__":
    print("Capturing Phase 1 baseline metrics...")
    baseline = capture_baseline()
    
    output_path = Path("baseline_phase1_metrics.json")
    with output_path.open("w") as f:
        json.dump(baseline, f, indent=2)
    
    print(f"✅ Baseline saved to {output_path}")
    print(f"   Avg task latency: {baseline['task_metrics']['avg_latency_ms']:.2f}ms")
    print(f"   Memory delta: {baseline['memory_metrics']['delta_mb']:.2f}MB")
    print(f"   Event throughput: {baseline['event_metrics']['throughput_events_per_sec']:.0f} events/sec")
    print(f"   Scheduler throughput: {baseline['scheduler_metrics']['tasks_per_second']:.1f} tasks/sec")

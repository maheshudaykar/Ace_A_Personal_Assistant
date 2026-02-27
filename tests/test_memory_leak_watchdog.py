"""Memory leak watchdog test - 500 tasks with tracking."""

from __future__ import annotations

import gc
import sys
from pathlib import Path

import psutil
from ace.ace_diagnostics.evaluation_engine import EvaluationEngine
from ace.ace_kernel.audit_trail import AuditTrail
from ace.ace_kernel.nuclear_switch import NuclearSwitch
from ace.ace_kernel.prompt_injection_detector import PromptInjectionDetector
from ace.ace_kernel.resource_profiler import ResourceProfiler
from ace.ace_kernel.sandbox import Sandbox
from ace.ace_kernel.security_monitor import SecurityMonitor
from ace.ace_tools.terminal_executor import TerminalExecutor


def test_memory_leak_watchdog_500_tasks(tmp_path: Path) -> None:
    """Run 500 tasks and track memory every 50 tasks to detect leaks."""
    # Build system
    audit = AuditTrail(tmp_path / "watchdog_audit.jsonl")
    nuclear = NuclearSwitch(audit, passphrase="watchdog")
    prompt = PromptInjectionDetector(audit)
    security = SecurityMonitor(audit, nuclear, workspace_root=tmp_path)
    sandbox = Sandbox()
    profiler = ResourceProfiler()
    evaluation = EvaluationEngine()
    executor = TerminalExecutor(audit, prompt, security, sandbox, profiler, evaluation)

    process = psutil.Process()
    memory_samples: list[tuple[int, float]] = []

    # Force GC before starting
    gc.collect()
    baseline_mem = process.memory_info().rss / (1024 * 1024)  # MB
    memory_samples.append((0, baseline_mem))

    # Run 500 tasks, sampling every 50
    for i in range(1, 501):
        executor.execute(
            [sys.executable, "-c", f"x = {i} * 2; print(x)"],
            timeout_seconds=2.0,
        )

        if i % 50 == 0:
            gc.collect()
            mem_mb = process.memory_info().rss / (1024 * 1024)
            memory_samples.append((i, mem_mb))

    # Force final GC
    gc.collect()
    final_mem = process.memory_info().rss / (1024 * 1024)
    memory_samples.append((500, final_mem))

    # Calculate memory growth
    mem_delta = final_mem - baseline_mem
    mem_growth_rate = mem_delta / baseline_mem

    # Assert memory growth is reasonable
    # Allow up to 20MB growth for 500 tasks (accounting for Python overhead)
    assert mem_delta < 20.0, (
        f"Memory leak detected: {mem_delta:.2f}MB growth after 500 tasks. "
        f"Samples: {memory_samples}"
    )

    # Assert growth rate is under 50%
    assert mem_growth_rate < 0.5, (
        f"Memory growth rate too high: {mem_growth_rate:.1%}. "
        f"Started at {baseline_mem:.2f}MB, ended at {final_mem:.2f}MB"
    )

    # Verify audit chain integrity after 500 tasks
    assert audit.verify_chain() is True

    print(f"\n✅ Memory watchdog PASSED:")
    print(f"   Baseline: {baseline_mem:.2f}MB")
    print(f"   Final: {final_mem:.2f}MB")
    print(f"   Delta: {mem_delta:.2f}MB")
    print(f"   Growth: {mem_growth_rate:.1%}")
    print(f"   Samples: {memory_samples}")

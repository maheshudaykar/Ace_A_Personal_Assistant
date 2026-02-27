"""Terminal tool execution wrapper enforcing full security chain."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from ace.ace_diagnostics.evaluation_engine import EvaluationEngine, TaskMetrics
from ace.ace_kernel.audit_trail import AuditTrail
from ace.ace_kernel.prompt_injection_detector import PromptInjectionDetector, ScanResult
from ace.ace_kernel.resource_profiler import ResourceProfile, ResourceProfiler
from ace.ace_kernel.sandbox import Sandbox, SandboxResult
from ace.ace_kernel.security_monitor import SecurityDecision, SecurityMonitor


@dataclass(frozen=True)
class ExecutionOutcome:
    """Outcome of a tool execution attempt."""

    allowed: bool
    reason: str
    security: SecurityDecision
    prompt_scan: ScanResult
    resource_profile: ResourceProfile
    result: Optional[SandboxResult]


class TerminalExecutor:
    """Enforce the full execution chain for tool calls."""

    def __init__(
        self,
        audit_trail: AuditTrail,
        prompt_detector: PromptInjectionDetector,
        security_monitor: SecurityMonitor,
        sandbox: Sandbox,
        resource_profiler: ResourceProfiler,
        evaluation_engine: EvaluationEngine,
    ) -> None:
        self._audit = audit_trail
        self._prompt = prompt_detector
        self._security = security_monitor
        self._sandbox = sandbox
        self._resources = resource_profiler
        self._evaluation = evaluation_engine

    def execute(
        self,
        command: Sequence[str],
        timeout_seconds: float,
        input_text: str = "",
        write_paths: Iterable[str] | None = None,
        network_hosts: Iterable[str] | None = None,
        requires_sudo: bool = False,
        tokens_used: int = 0,
    ) -> ExecutionOutcome:
        """Execute a command through the full security chain."""
        prompt_scan = self._prompt.scan(input_text)
        resource_profile = self._resources.profile()

        security = self._security.evaluate_tool_call(
            command,
            write_paths=write_paths,
            network_hosts=network_hosts,
            requires_sudo=requires_sudo,
        )

        if prompt_scan.flagged:
            self._audit.append(
                {
                    "type": "tool.blocked",
                    "reason": "prompt_injection",
                    "command": list(command),
                }
            )
            self._record_metrics(command, success=False, cpu_time_ms=0, tokens_used=tokens_used)
            return ExecutionOutcome(
                allowed=False,
                reason="prompt_injection",
                security=security,
                prompt_scan=prompt_scan,
                resource_profile=resource_profile,
                result=None,
            )

        if not security.allowed:
            self._audit.append(
                {
                    "type": "tool.blocked",
                    "reason": "security_policy",
                    "command": list(command),
                    "details": security.reasons,
                }
            )
            self._record_metrics(command, success=False, cpu_time_ms=0, tokens_used=tokens_used)
            return ExecutionOutcome(
                allowed=False,
                reason="security_policy",
                security=security,
                prompt_scan=prompt_scan,
                resource_profile=resource_profile,
                result=None,
            )

        start = time.perf_counter()
        result = self._sandbox.run(command, timeout_seconds=timeout_seconds)
        elapsed_ms = int((time.perf_counter() - start) * 1000)

        self._audit.append(
            {
                "type": "tool.executed",
                "command": list(command),
                "exit_code": result.exit_code,
                "timed_out": result.timed_out,
                "elapsed_ms": elapsed_ms,
                "mode": resource_profile.mode,
            }
        )

        success = result.exit_code == 0 and not result.timed_out
        self._record_metrics(command, success=success, cpu_time_ms=elapsed_ms, tokens_used=tokens_used)
        return ExecutionOutcome(
            allowed=True,
            reason="executed",
            security=security,
            prompt_scan=prompt_scan,
            resource_profile=resource_profile,
            result=result,
        )

    def _record_metrics(self, command: Sequence[str], success: bool, cpu_time_ms: int, tokens_used: int) -> None:
        task_id = f"tool:{command[0]}:{uuid.uuid4().hex[:8]}"
        metrics = TaskMetrics(
            task_id=task_id,
            success=success,
            steps=1,
            tool_successes=1 if success else 0,
            tool_failures=0 if success else 1,
            cpu_time_ms=cpu_time_ms,
            tokens_used=tokens_used,
        )
        self._evaluation.record_task(metrics)

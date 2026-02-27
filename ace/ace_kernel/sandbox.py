"""Execution sandbox with timeout enforcement."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import List, Sequence


@dataclass(frozen=True)
class SandboxResult:
    """Result of a sandboxed command execution."""

    command: List[str]
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool


class Sandbox:
    """Run subprocesses with timeout and kill on overrun."""

    def run(
        self,
        command: Sequence[str],
        timeout_seconds: float,
    ) -> SandboxResult:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        cmd_list = list(command)
        process = subprocess.Popen(
            cmd_list,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
            return SandboxResult(
                command=cmd_list,
                exit_code=process.returncode or 0,
                stdout=stdout or "",
                stderr=stderr or "",
                timed_out=False,
            )
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            return SandboxResult(
                command=cmd_list,
                exit_code=-1,
                stdout=stdout or "",
                stderr=stderr or "",
                timed_out=True,
            )
        finally:
            self._terminate_if_running(process)

    @staticmethod
    def _terminate_if_running(process: subprocess.Popen[str]) -> None:
        if process.poll() is None:
            process.kill()
            process.communicate()

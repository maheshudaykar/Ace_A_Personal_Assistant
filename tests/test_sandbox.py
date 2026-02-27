"""Tests for sandbox execution and timeout."""

from __future__ import annotations

import sys

from ace.ace_kernel.sandbox import Sandbox


def test_sandbox_runs_command() -> None:
    sandbox = Sandbox()
    result = sandbox.run([sys.executable, "-c", "print('ok')"], timeout_seconds=2.0)

    assert result.timed_out is False
    assert result.exit_code == 0
    assert "ok" in result.stdout


def test_sandbox_times_out() -> None:
    sandbox = Sandbox()
    result = sandbox.run(
        [sys.executable, "-c", "import time; time.sleep(5)"]
        ,
        timeout_seconds=0.1,
    )

    assert result.timed_out is True
    assert result.exit_code == -1

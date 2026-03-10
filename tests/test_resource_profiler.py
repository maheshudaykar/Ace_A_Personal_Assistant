"""Tests for resource profiler mode selection."""

from __future__ import annotations

from ace.ace_kernel.resource_profiler import ResourceProfiler


def test_minimal_mode() -> None:
    profiler = ResourceProfiler()
    profile = profiler.enforce_limits(ram_mb=512, vram_mb=0)

    assert profile.mode == "minimal"
    assert profile.max_agents == 2


def test_balanced_mode() -> None:
    profiler = ResourceProfiler()
    profile = profiler.enforce_limits(ram_mb=4096, vram_mb=0)

    assert profile.mode == "balanced"
    assert profile.max_agents == 2


def test_performance_mode() -> None:
    profiler = ResourceProfiler()
    profile = profiler.enforce_limits(ram_mb=8192, vram_mb=8192)

    assert profile.mode == "performance"
    assert profile.max_agents == 4

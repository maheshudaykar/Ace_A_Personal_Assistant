"""Resource profiler for execution mode selection and limits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import os

try:
    import psutil  # type: ignore
except ImportError:
    psutil = None  # type: ignore


@dataclass(frozen=True)
class ResourceProfile:
    """Detected resources and selected execution mode."""

    cpu_cores: int
    ram_mb: int
    gpu_vram_mb: int
    mode: str
    max_agents: int


class ResourceProfiler:
    """Detect system resources and select execution mode."""

    def __init__(self, max_ram_mb: int = 6 * 1024, max_vram_mb: int = 5 * 1024) -> None:
        self._max_ram_mb = max_ram_mb
        self._max_vram_mb = max_vram_mb

    def profile(self) -> ResourceProfile:
        """Profile system and select mode."""
        cpu_cores = self._cpu_count()
        ram_mb = self._ram_mb()
        vram_mb = self._detect_vram_mb()

        mode, max_agents = self._select_mode(ram_mb, vram_mb)
        return ResourceProfile(
            cpu_cores=cpu_cores,
            ram_mb=min(ram_mb, self._max_ram_mb),
            gpu_vram_mb=min(vram_mb, self._max_vram_mb),
            mode=mode,
            max_agents=max_agents,
        )

    def _select_mode(self, ram_mb: int, vram_mb: int) -> tuple[str, int]:
        if vram_mb > 0 and ram_mb >= 6 * 1024:
            return "performance", 4
        if ram_mb >= 2 * 1024:
            return "balanced", 2
        return "minimal", 2

    def _detect_vram_mb(self) -> int:
        # Placeholder: GPU detection can be added later without changing interface.
        return 0

    def enforce_limits(self, ram_mb: int, vram_mb: int) -> ResourceProfile:
        """Enforce max RAM/VRAM limits for scheduling decisions."""
        mode, max_agents = self._select_mode(ram_mb, vram_mb)
        return ResourceProfile(
            cpu_cores=self._cpu_count(),
            ram_mb=min(ram_mb, self._max_ram_mb),
            gpu_vram_mb=min(vram_mb, self._max_vram_mb),
            mode=mode,
            max_agents=max_agents,
        )

    def _cpu_count(self) -> int:
        if psutil is not None:
            return psutil.cpu_count(logical=True) or 1
        return os.cpu_count() or 1

    def _ram_mb(self) -> int:
        if psutil is not None:
            return int(psutil.virtual_memory().total / (1024 * 1024))
        return 2048

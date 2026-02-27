"""Meta monitor for tracking performance deltas."""

from __future__ import annotations

from typing import Dict


class MetaMonitor:
    """Track performance deltas from evaluation and scheduler stats."""

    def __init__(self) -> None:
        self._last_metrics: Dict[str, float] | None = None
        self._last_delta: Dict[str, float] = {}

    def update(self, metrics: Dict[str, float]) -> Dict[str, float]:
        """Update with new metrics and return delta from last snapshot."""
        if self._last_metrics is None:
            self._last_metrics = dict(metrics)
            self._last_delta = {key: 0.0 for key in metrics}
            return dict(self._last_delta)

        delta: Dict[str, float] = {}
        for key, value in metrics.items():
            prev = self._last_metrics.get(key, 0.0)
            delta[key] = value - prev
        self._last_metrics = dict(metrics)
        self._last_delta = dict(delta)
        return dict(delta)

    @property
    def last_delta(self) -> Dict[str, float]:
        return dict(self._last_delta)

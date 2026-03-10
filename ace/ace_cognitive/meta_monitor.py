"""Meta monitor for tracking performance deltas."""

from __future__ import annotations

from collections import deque
from typing import Dict, List


class MetaMonitor:
    """Track performance deltas from evaluation and scheduler stats.

    Retains a bounded history window so callers can observe trends in
    planning efficiency, tool success rate and error recovery speed
    (metrics recommended by research evaluation frameworks).
    """

    def __init__(self, history_limit: int = 100) -> None:
        self._last_metrics: Dict[str, float] | None = None
        self._last_delta: Dict[str, float] = {}
        self._history: deque[Dict[str, float]] = deque(maxlen=max(history_limit, 1))

    def update(self, metrics: Dict[str, float]) -> Dict[str, float]:
        """Update with new metrics and return delta from last snapshot."""
        if self._last_metrics is None:
            self._last_metrics = dict(metrics)
            self._last_delta = dict.fromkeys(metrics, 0.0)
            self._history.append(dict(metrics))
            return dict(self._last_delta)

        delta: Dict[str, float] = {}
        for key, value in metrics.items():
            prev = self._last_metrics.get(key, 0.0)
            delta[key] = value - prev
        self._last_metrics = dict(metrics)
        self._last_delta = dict(delta)
        self._history.append(dict(metrics))
        return dict(delta)

    @property
    def last_delta(self) -> Dict[str, float]:
        return dict(self._last_delta)

    def get_history(self) -> List[Dict[str, float]]:
        """Return the full metrics history window."""
        return list(self._history)

    def get_trend(self, key: str) -> List[float]:
        """Return historical values for a specific metric key."""
        return [snapshot[key] for snapshot in self._history if key in snapshot]

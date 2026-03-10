"""ExperimentEngine: controlled hypothesis testing in sandboxed execution."""

from __future__ import annotations

import hashlib
import math
import statistics
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ace.runtime.golden_trace import GoldenTrace

__all__ = [
    "Hypothesis",
    "ExperimentRun",
    "ExperimentResult",
    "Experiment",
    "ExperimentEngine",
]


def _experiment_run_list_default() -> List["ExperimentRun"]:
    return []


@dataclass
class Hypothesis:
    hypothesis_id: str
    statement: str
    baseline_config: Dict[str, Any]
    experimental_config: Dict[str, Any]
    metric_to_measure: str = "throughput"


@dataclass
class ExperimentRun:
    run_id: str
    config_name: str
    metrics: Dict[str, float]
    duration_ms: float
    success: bool
    error: Optional[str] = None


@dataclass
class ExperimentResult:
    experiment_id: str
    accepted: bool
    p_value: float
    effect_size: float
    baseline_mean: float
    experimental_mean: float
    confidence_interval: Dict[str, float]
    decision_reason: str
    insight: Optional[str] = None


@dataclass
class Experiment:
    experiment_id: str
    hypothesis: Hypothesis
    trials: int = 5
    status: str = "pending"
    created_at: float = field(default_factory=time.time)
    runs: List[ExperimentRun] = field(default_factory=_experiment_run_list_default)
    outcome: Optional[ExperimentResult] = None


class ExperimentEngine:
    """Run bounded experiments with deterministic governance limits."""

    def __init__(
        self,
        sandbox_executor: Callable[[Dict[str, Any]], Dict[str, float]],
        max_concurrent_experiments: int = 2,
        max_trials_per_experiment: int = 20,
        max_runtime_ms: int = 120_000,
        p_value_threshold: float = 0.05,
        effect_size_threshold: float = 0.2,
    ) -> None:
        if max_concurrent_experiments <= 0:
            raise ValueError("max_concurrent_experiments must be positive")
        if not (0.0 < p_value_threshold < 1.0):
            raise ValueError("p_value_threshold must be in (0, 1)")
        if effect_size_threshold < 0.0:
            raise ValueError("effect_size_threshold must be non-negative")
        self.sandbox_executor = sandbox_executor
        self.max_concurrent_experiments = max_concurrent_experiments
        self.max_trials_per_experiment = max_trials_per_experiment
        self.max_runtime_ms = max_runtime_ms
        self.p_value_threshold = p_value_threshold
        self.effect_size_threshold = effect_size_threshold

        self._trace = GoldenTrace.get_instance()
        self._lock = threading.Lock()
        self._in_flight = 0
        self._experiments: Dict[str, Experiment] = {}

    def create_experiment(self, statement: str, baseline: Dict[str, Any], experimental: Dict[str, Any], metric: str = "throughput", trials: int = 5) -> Experiment:
        trials = min(max(trials, 1), self.max_trials_per_experiment)
        hash_src = f"{statement}|{baseline}|{experimental}|{metric}".encode("utf-8")
        hypothesis = Hypothesis(
            hypothesis_id=hashlib.sha256(hash_src).hexdigest()[:16],
            statement=statement,
            baseline_config=dict(baseline),
            experimental_config=dict(experimental),
            metric_to_measure=metric,
        )
        exp_id = hashlib.sha256(f"{hypothesis.hypothesis_id}:{time.time():.6f}".encode("utf-8")).hexdigest()[:16]
        exp = Experiment(experiment_id=exp_id, hypothesis=hypothesis, trials=trials)
        self._experiments[exp_id] = exp
        return exp

    def run_experiment(self, experiment: Experiment) -> ExperimentResult:
        start = time.time()
        self._acquire_slot()
        try:
            experiment.status = "running"
            metric_name = experiment.hypothesis.metric_to_measure
            baseline_values: List[float] = []
            experimental_values: List[float] = []

            for i in range(experiment.trials):
                self._enforce_runtime_budget(start)
                baseline_values.append(self._run_trial(experiment, "baseline", i, experiment.hypothesis.baseline_config, metric_name))
                self._enforce_runtime_budget(start)
                experimental_values.append(self._run_trial(experiment, "experimental", i, experiment.hypothesis.experimental_config, metric_name))

            result = self._analyze(experiment.experiment_id, baseline_values, experimental_values)
            experiment.outcome = result
            experiment.status = "completed"
            self._trace.log_event(
                "experiment.completed",
                {
                    "experiment_id": experiment.experiment_id,
                    "accepted": result.accepted,
                    "effect_size": result.effect_size,
                    "p_value": result.p_value,
                },
            )
            return result
        except Exception as exc:
            experiment.status = "failed"
            self._trace.log_event(
                "experiment.failed",
                {"experiment_id": experiment.experiment_id, "error": str(exc)},
            )
            raise
        finally:
            self._release_slot()

    def get_experiment(self, experiment_id: str) -> Optional[Experiment]:
        return self._experiments.get(experiment_id)

    def _run_trial(
        self,
        experiment: Experiment,
        config_name: str,
        trial_index: int,
        config: Dict[str, Any],
        metric_name: str,
    ) -> float:
        trial_start = time.time()
        payload = dict(config)
        payload["_trial_index"] = trial_index
        payload["_seed"] = trial_index

        metrics = self.sandbox_executor(payload)
        metric_value = float(metrics.get(metric_name, 0.0))

        run = ExperimentRun(
            run_id=hashlib.sha256(f"{experiment.experiment_id}:{config_name}:{trial_index}".encode("utf-8")).hexdigest()[:16],
            config_name=config_name,
            metrics={metric_name: metric_value},
            duration_ms=(time.time() - trial_start) * 1000.0,
            success=True,
        )
        experiment.runs.append(run)
        self._trace.log_event(
            "experiment.trial",
            {
                "experiment_id": experiment.experiment_id,
                "config": config_name,
                "trial": trial_index,
                "metric": metric_value,
            },
        )
        return metric_value

    def _analyze(self, experiment_id: str, baseline: List[float], experimental: List[float]) -> ExperimentResult:
        baseline_mean = statistics.mean(baseline)
        experimental_mean = statistics.mean(experimental)
        baseline_std = statistics.pstdev(baseline) if len(baseline) > 1 else 0.0

        if math.isclose(baseline_std, 0.0, abs_tol=1e-9):
            effect_size = (
                0.0
                if math.isclose(baseline_mean, 0.0, abs_tol=1e-9)
                else (experimental_mean - baseline_mean) / max(abs(baseline_mean), 1e-9)
            )
        else:
            effect_size = (experimental_mean - baseline_mean) / baseline_std

        # Clamp effect size to reasonable bounds to prevent numerical instability.
        effect_size = max(-100.0, min(100.0, effect_size))

        # Deterministic pseudo p-value: monotonic with effect magnitude and sample size.
        sample_factor = max(len(baseline), 1)
        p_value = min(1.0, max(0.0, 1.0 / (1.0 + abs(effect_size) * sample_factor)))

        accepted = (
            (experimental_mean > baseline_mean)
            and (p_value < self.p_value_threshold or abs(effect_size) >= self.effect_size_threshold)
        )
        reason = (
            f"Significant improvement (p={p_value:.4f}, d={effect_size:.2f})"
            if accepted
            else f"No significant gain (p={p_value:.4f}, d={effect_size:.2f})"
        )

        delta = experimental_mean - baseline_mean
        margin = 0.1 * abs(delta) if not math.isclose(delta, 0.0, abs_tol=1e-9) else 0.0
        ci = {"low": delta - margin, "high": delta + margin}

        return ExperimentResult(
            experiment_id=experiment_id,
            accepted=accepted,
            p_value=p_value,
            effect_size=effect_size,
            baseline_mean=baseline_mean,
            experimental_mean=experimental_mean,
            confidence_interval=ci,
            decision_reason=reason,
            insight="Prefer experimental configuration" if accepted else "Keep baseline configuration",
        )

    def _acquire_slot(self) -> None:
        with self._lock:
            if self._in_flight >= self.max_concurrent_experiments:
                raise RuntimeError("maximum concurrent experiments reached")
            self._in_flight += 1

    def _release_slot(self) -> None:
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)

    def _enforce_runtime_budget(self, start_time: float) -> None:
        elapsed_ms = (time.time() - start_time) * 1000.0
        if elapsed_ms > self.max_runtime_ms:
            raise TimeoutError("experiment runtime budget exceeded")

from ace.runtime.experiment_engine import ExperimentEngine


def _executor(payload):
    trial = payload["_trial_index"]
    if payload.get("mode") == "experimental":
        return {"throughput": 120.0 + trial}
    return {"throughput": 100.0 + trial}


def test_experiment_engine_runs_and_accepts_improvement() -> None:
    engine = ExperimentEngine(sandbox_executor=_executor, max_concurrent_experiments=1)
    exp = engine.create_experiment(
        statement="experimental mode improves throughput",
        baseline={"mode": "baseline"},
        experimental={"mode": "experimental"},
        metric="throughput",
        trials=4,
    )
    result = engine.run_experiment(exp)

    assert result.experimental_mean > result.baseline_mean
    assert exp.status == "completed"


def test_experiment_engine_enforces_concurrency_limit() -> None:
    engine = ExperimentEngine(sandbox_executor=_executor, max_concurrent_experiments=1)
    engine._in_flight = 1
    exp = engine.create_experiment("x", {"mode": "baseline"}, {"mode": "experimental"})

    try:
        engine.run_experiment(exp)
        assert False, "Expected RuntimeError"
    except RuntimeError:
        assert True

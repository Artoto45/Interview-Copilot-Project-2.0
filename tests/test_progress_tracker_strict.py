from tests.run_progress_strict_stress import _build_verdict, _run_strict


def test_progress_tracker_strict_regression_thresholds():
    metrics = _run_strict(cases=500, seed=20260303)
    passed, reasons = _build_verdict(metrics)
    assert passed, f"Strict regression failed: {reasons}"


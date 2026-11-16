from loadtest.evaluate import evaluate_step
from loadtest.stats import Row


def row(name, p95, requests=100, failures=0):
    return Row(name=name, requests=requests, failures=failures, p50=p95, p95=p95, max=p95)


CAL = {
    "Step_06_first_build": row("Step_06_first_build", 3500),
    "Step_14_full_test_suite": row("Step_14_full_test_suite", 4100),
}


def step(build=3600, suite=4200, failures=0, wake=None):
    rows = {
        "Step_06_first_build": row("Step_06_first_build", build),
        "Step_14_full_test_suite": row("Step_14_full_test_suite", suite),
        "Aggregated": row("Aggregated", 4000, requests=1000, failures=failures),
    }
    if wake is not None:
        rows["WakeFirstTouch"] = row("WakeFirstTouch", wake)
    return rows


def test_evaluate_step_passes_within_limits():
    assert evaluate_step(step(), CAL, "pod").passed


def test_evaluate_step_fails_on_slowdown():
    v = evaluate_step(step(build=5300), CAL, "pod")
    assert not v.passed
    assert any("Step_06_first_build" in r for r in v.reasons)


def test_evaluate_step_fails_on_failure_ratio():
    v = evaluate_step(step(failures=10), CAL, "pod")
    assert not v.passed
    assert any("failure ratio" in r for r in v.reasons)


def test_evaluate_step_checks_wake_on_substrate_only():
    assert not evaluate_step(step(wake=2100), CAL, "substrate").passed
    assert evaluate_step(step(wake=1900), CAL, "substrate").passed
    assert evaluate_step(step(), CAL, "pod").passed


def test_evaluate_step_missing_row_fails():
    rows = step(wake=500)
    del rows["Step_14_full_test_suite"]
    v = evaluate_step(rows, CAL, "substrate")
    assert not v.passed
    assert any("missing" in r for r in v.reasons)
    v = evaluate_step(step(), CAL, "substrate")  # no WakeFirstTouch row
    assert not v.passed


def test_evaluate_step_ignores_jitter_on_short_steps():
    cal = {"Step_12_write_new_tests": row("Step_12_write_new_tests", 43)}
    rows = {"Step_12_write_new_tests": row("Step_12_write_new_tests", 81),
            "Aggregated": row("Aggregated", 100, requests=1000)}
    assert evaluate_step(rows, cal, "pod").passed
    rows["Step_12_write_new_tests"] = row("Step_12_write_new_tests", 400)
    assert not evaluate_step(rows, cal, "pod").passed


def test_evaluate_step_fails_when_sessions_slow_down():
    # Calibration: one session completes 200 steps in the window.
    ok = {k: row(k, 3600, requests=1000) for k in CAL}
    ok["Aggregated"] = row("Aggregated", 4000, requests=2000)
    assert evaluate_step(ok, CAL, "substrate_any", users=10).passed  # 200 per session

    slow = {k: row(k, 3600, requests=700) for k in CAL}
    slow["Aggregated"] = row("Aggregated", 4000, requests=1400)
    v = evaluate_step(slow, CAL, "pod", users=10)  # 140 per session < 0.8 x 200
    assert not v.passed
    assert any("steps per session" in r for r in v.reasons)

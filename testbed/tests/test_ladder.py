from loadtest.ladder import capacity, hold_seconds, swarm_fields


def test_hold_seconds():
    assert hold_seconds(1) == 2 * (69 + 30) + 60
    assert hold_seconds(6) == 2 * (69 * 6 + 30) + 60


def test_capacity_stops_at_first_failure():
    steps = [{"users": 10, "passed": True}, {"users": 20, "passed": True},
             {"users": 40, "passed": False}, {"users": 80, "passed": True}]
    assert capacity(steps) == 20
    assert capacity([{"users": 10, "passed": False}]) == 0


def test_swarm_fields():
    assert swarm_fields("substrate", 3) == {
        "lifecycle_mode": "async", "resume_mode": "implicit", "agentsession_think_scale": "3"}
    assert swarm_fields("pod", 1)["lifecycle_mode"] == "none"


def test_summarize_dir(tmp_path):
    import json
    import shutil
    from pathlib import Path

    from loadtest.ladder import summarize_dir

    fixture = Path(__file__).parent / "fixtures" / "stats.csv"
    run = tmp_path / "pod-ts1-r1"
    run.mkdir()
    for name in ("calibration", "step-10", "step-20"):
        shutil.copy(fixture, run / f"{name}.csv")
    summary = summarize_dir(run, "pod", 1.0, 1)
    # The same CSV as calibration and as a 10-session step means each session
    # did a tenth of the steps, so the throughput rule fails step 10 and the
    # summary stops there.
    assert [s["users"] for s in summary["steps"]] == [10]
    assert summary["capacity"] == 0
    assert json.loads((run / "summary.json").read_text())["capacity"] == 0


def test_prepare_stops_locust_before_sweeping(monkeypatch):
    from loadtest import cluster, ladder

    order = []

    class FakeLocust:
        def stop(self):
            order.append("stop")

    monkeypatch.setattr(cluster, "sweep", lambda: order.append("sweep"))
    monkeypatch.setattr(cluster, "assert_clean", lambda: order.append("assert_clean"))
    ladder.prepare(FakeLocust())
    assert order == ["stop", "sweep", "assert_clean"]

from pathlib import Path

from loadtest.stats import read_stats

FIXTURE = Path(__file__).parent / "fixtures" / "stats.csv"


def test_read_stats_rows():
    rows = read_stats(FIXTURE)
    step = rows["Step_01_read_task"]
    assert (step.requests, step.failures, step.p50, step.p95, step.max) == (15, 0, 97.0, 120.0, 130.0)
    assert rows["Aggregated"].failures == 2


def test_read_stats_handles_na():
    row = read_stats(FIXTURE)["CreateSandbox"]
    assert row.requests == 0
    assert row.p95 is None

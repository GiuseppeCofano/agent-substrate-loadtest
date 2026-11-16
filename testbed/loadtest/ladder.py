"""Runs calibration and a step ladder for one platform and LLM-wait level."""

import argparse
import json
import subprocess
import time
from pathlib import Path

from loadtest import cluster
from loadtest.evaluate import evaluate_step
from loadtest.locust_api import Locust
from loadtest.stats import read_stats

SPAWN_RATE = 2.0
SCRIPT_THINK_S = 69
SCRIPT_WORK_S = 30
WARMUP_S = 60
SPAWN_TIMEOUT_S = 600


def hold_seconds(think_scale: float) -> int:
    """Two full session lengths plus the warm-up the stats reset discards."""
    session = SCRIPT_THINK_S * think_scale + SCRIPT_WORK_S
    return int(2 * session + WARMUP_S)


def capacity(steps: list[dict]) -> int:
    best = 0
    for s in steps:
        if not s["passed"]:
            break
        best = s["users"]
    return best


def swarm_fields(platform: str, think_scale: float) -> dict[str, str]:
    fields = {"agentsession_think_scale": f"{think_scale:g}"}
    if platform == "substrate":
        fields.update(lifecycle_mode="async", resume_mode="implicit")
    else:
        fields.update(lifecycle_mode="none")
    return fields


def run_step(locust: Locust, users: int, fields: dict[str, str], hold: int, out: Path, name: str) -> None:
    locust.swarm(users, SPAWN_RATE, fields)
    deadline = time.monotonic() + SPAWN_TIMEOUT_S
    # A platform at capacity may never reach the user count (B1 pods Pending);
    # the step is then measured on what ran and fails on its failure ratio.
    while locust.user_count() < users and time.monotonic() < deadline:
        time.sleep(5)
    time.sleep(WARMUP_S)
    locust.reset_stats()
    time.sleep(hold - WARMUP_S)
    locust.save_stats(out / f"{name}.csv")
    locust.save_failures(out / f"{name}-failures.csv")


def size_warm_pool(users: int) -> None:
    cluster.kubectl(["kubectl", "-n", "benchmark-sandboxes", "patch", "sandboxwarmpool", "glutton-pool",
                     "--type=merge", "-p", json.dumps({"spec": {"replicas": users}})])
    cluster.kubectl(["kubectl", "-n", "benchmark-sandboxes", "wait", "sandboxwarmpool/glutton-pool",
                     f"--for=jsonpath={{.status.readyReplicas}}={users}", "--timeout=600s"])


def summarize_dir(out: Path, platform: str, think_scale: float, repeat: int) -> dict:
    """Rebuilds summary.json from a run directory's saved CSVs, for a run that
    stopped after measuring its steps."""
    calibration = read_stats(out / "calibration.csv")
    users = sorted(int(p.stem.split("-")[1]) for p in out.glob("step-*.csv") if not p.stem.endswith("-failures"))
    steps = []
    for u in users:
        v = evaluate_step(read_stats(out / f"step-{u}.csv"), calibration, platform, users=u)
        steps.append({"users": u, "passed": v.passed, "reasons": v.reasons})
        if not v.passed:
            break
    summary = {"platform": platform, "think_scale": think_scale, "repeat": repeat,
               "steps": steps, "capacity": capacity(steps), "rebuilt_from_csv": True}
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def prepare(locust: Locust) -> None:
    """Leaves the cluster with no sessions: a swarm left running by an
    interrupted ladder keeps creating actors the sweep could not delete."""
    locust.stop()
    cluster.sweep()
    cluster.assert_clean()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--platform", choices=["substrate", "pod", "warmpool"], required=True)
    p.add_argument("--think-scale", type=float, required=True)
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--steps", default="10,20,40,80,160,320,640")
    p.add_argument("--out", default="results/runs")
    a = p.parse_args()

    out = Path(a.out) / f"{a.platform}-ts{a.think_scale:g}-r{a.repeat}"
    out.mkdir(parents=True, exist_ok=False)
    locust = Locust()
    prepare(locust)
    fields = swarm_fields(a.platform, a.think_scale)
    hold = hold_seconds(a.think_scale)

    if a.platform == "warmpool":
        size_warm_pool(1)
    run_step(locust, 1, fields, hold, out, "calibration")
    cluster.check_placement(cluster.kubectl, a.platform)
    calibration = read_stats(out / "calibration.csv")

    steps = []
    for users in (int(s) for s in a.steps.split(",")):
        name = f"step-{users}"
        if a.platform == "warmpool":
            try:
                size_warm_pool(users)
            except subprocess.CalledProcessError:
                steps.append({"users": users, "passed": False,
                              "reasons": ["warm pool cannot hold this many sandboxes"]})
                break
        run_step(locust, users, fields, hold, out, name)
        v = evaluate_step(read_stats(out / f"{name}.csv"), calibration, a.platform, users=users)
        steps.append({"users": users, "passed": v.passed, "reasons": v.reasons})
        print(f"{a.platform} ts={a.think_scale:g} users={users}: {'PASS' if v.passed else 'FAIL'} {v.reasons}",
              flush=True)
        if not v.passed:
            break
    locust.stop()
    cluster.sweep()
    summary = {"platform": a.platform, "think_scale": a.think_scale, "repeat": a.repeat,
               "steps": steps, "capacity": capacity(steps)}
    (out / "summary.json").write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

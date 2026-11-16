"""Exports the Cloud Monitoring data behind every ladder step to CSV files, so
the numbers survive Cloud Monitoring's retention and can be published.

For each step-N.csv under the given run directories, the measured window is
the 474 s before the file's mtime (stats reset to CSV write, two session
lengths at think scale 3). Writes, next to the step CSVs, a cloud-monitoring/
directory with:
  step-N-substrate-histograms.csv  Substrate histograms summed over the window
  step-N-substrate-gauges.csv      Substrate gauges and counters, per minute
  step-N-disks.csv                 Compute Engine disk rates, per minute and device
  step-N-node-cpu.csv              node CPU allocatable utilization, per minute

Usage: python -m loadtest.export_metrics results/disks/lssd4/substrate-ts3-r1 [...]
"""

import os
import argparse
import csv
import datetime
import json
import subprocess
from pathlib import Path

import requests

PROJECT = os.environ["PROJECT_ID"]
WINDOW_S = 474
INSTANCE_PREFIX = "gke-substrate-smoke-agents-"
PROM = "prometheus.googleapis.com/"
HISTOGRAMS = [
    "ate.actor.restore.duration/histogram",
    "ate.actor.checkpoint.duration/histogram",
    "ate.actor.lifecycle.operation.duration/histogram",
    "ate.scheduler.assignment.duration/histogram",
    "atelet.snapshot.size/histogram",
    "atelet.snapshot.upload.duration/histogram",
    "atenet.router.parking.wait.duration/histogram",
    "atenet.router.route.duration/histogram",
]
GAUGES = [  # (metric, aligner)
    ("atelet.snapshot.undurable.age.max/gauge", "ALIGN_MAX"),
    ("atenet.router.parking.active/gauge", "ALIGN_MAX"),
    ("ate.workerpool.workers/gauge", "ALIGN_MEAN"),
    ("ate.actor.crashes/counter", "ALIGN_DELTA"),
]
DISK = [
    "compute.googleapis.com/instance/disk/write_bytes_count",
    "compute.googleapis.com/instance/disk/read_bytes_count",
    "compute.googleapis.com/instance/disk/write_ops_count",
    "compute.googleapis.com/instance/disk/read_ops_count",
    "compute.googleapis.com/instance/disk/throttled_write_bytes_count",
]
NODE_CPU = "kubernetes.io/node/cpu/allocatable_utilization"
DROP = {"instance", "service_instance_id", "pod", "node", "job", "otel_scope_name", "otel_scope_version",
        "top_level_controller_type", "top_level_controller_name"}


_TOKEN: list = [0.0, ""]


def token() -> str:
    """Access token, refreshed every 20 minutes."""
    now = datetime.datetime.now().timestamp()
    if now - _TOKEN[0] > 1200:
        _TOKEN[:] = [now, subprocess.run(["gcloud", "auth", "print-access-token"], check=True,
                                         capture_output=True, text=True).stdout.strip()]
    return _TOKEN[1]


def iso(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts, datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def series(flt: str, start: str, end: str, aligner: str) -> list[dict]:
    out, page = [], None
    while True:
        params = {"filter": flt, "interval.startTime": start, "interval.endTime": end,
                  "aggregation.alignmentPeriod": "60s", "aggregation.perSeriesAligner": aligner}
        if page:
            params["pageToken"] = page
        r = requests.get(f"https://monitoring.googleapis.com/v3/projects/{PROJECT}/timeSeries",
                         params=params, headers={"Authorization": f"Bearer {token()}"}, timeout=120)
        if r.status_code == 404:
            return out
        r.raise_for_status()
        body = r.json()
        out.extend(body.get("timeSeries", []))
        page = body.get("nextPageToken")
        if not page:
            return out


def labels(s: dict) -> dict:
    return {k: v for k, v in s["metric"].get("labels", {}).items() if k not in DROP}


def bound(bounds: list, counts: list, q: float) -> str:
    total, seen = sum(counts), 0
    for i, n in enumerate(counts):
        seen += n
        if total and seen >= q * total:
            return f"<={bounds[i]:g}" if i < len(bounds) else f">{bounds[-1]:g}"
    return ""


def histograms(start: str, end: str) -> list[list]:
    rows = []
    for metric in HISTOGRAMS:
        merged: dict[str, list] = {}
        for s in series(f'metric.type="{PROM}{metric}"', start, end, "ALIGN_DELTA"):
            key = json.dumps(labels(s), sort_keys=True)
            for pt in s.get("points", []):
                d = pt["value"]["distributionValue"]
                bounds = d.get("bucketOptions", {}).get("explicitBuckets", {}).get("bounds", [])
                counts = [int(c) for c in d.get("bucketCounts", [])]
                b, c = merged.setdefault(key, [bounds, [0] * (len(bounds) + 1)])
                for i, n in enumerate(counts):
                    c[i] += n
        for key, (b, c) in sorted(merged.items()):
            if sum(c):
                rows.append([metric.split("/")[0], key, sum(c), bound(b, c, 0.5), bound(b, c, 0.95),
                             json.dumps(b), json.dumps(c)])
    return rows


def per_minute(flt: str, start: str, end: str, aligner: str, who) -> list[list]:
    rows = []
    for s in series(flt, start, end, aligner):
        for pt in s.get("points", []):
            v = pt["value"]
            val = v.get("doubleValue", v.get("int64Value", 0))
            rows.append([pt["interval"]["endTime"], *who(s), val])
    return sorted(rows)


def write(path: Path, header: list, rows: list) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def export(run: Path) -> None:
    out = run / "cloud-monitoring"
    out.mkdir(exist_ok=True)
    for step in sorted(run.glob("step-*.csv")):
        if step.name.endswith("-failures.csv"):
            continue
        name = step.stem
        if (out / f"{name}-node-cpu.csv").exists():
            continue
        end_ts = step.stat().st_mtime
        start, end = iso(end_ts - WINDOW_S), iso(end_ts)
        write(out / f"{name}-substrate-histograms.csv",
              ["metric", "labels", "count", "p50_bucket", "p95_bucket", "bounds", "bucket_counts"],
              histograms(start, end))
        gauges = []
        for metric, aligner in GAUGES:
            gauges += [[t, metric.split("/")[0], lab, v] for t, lab, v in per_minute(
                f'metric.type="{PROM}{metric}"', start, end, aligner,
                lambda s: [json.dumps(labels(s), sort_keys=True)])]
        write(out / f"{name}-substrate-gauges.csv", ["minute_end", "metric", "labels", "value"], gauges)
        disks = []
        for metric in DISK:
            flt = f'metric.type="{metric}" AND metric.labels.instance_name = starts_with("{INSTANCE_PREFIX}")'
            disks += [[t, metric.rsplit("/", 1)[1], inst, dev, v] for t, inst, dev, v in per_minute(
                flt, start, end, "ALIGN_RATE",
                lambda s: [s["metric"]["labels"].get("instance_name"), s["metric"]["labels"].get("device_name")])]
        write(out / f"{name}-disks.csv", ["minute_end", "metric_per_s", "instance", "device", "value"], disks)
        flt = (f'metric.type="{NODE_CPU}" AND resource.labels.node_name = starts_with("{INSTANCE_PREFIX}")')
        cpu = per_minute(flt, start, end, "ALIGN_MEAN", lambda s: [s["resource"]["labels"].get("node_name")])
        write(out / f"{name}-node-cpu.csv", ["minute_end", "node", "allocatable_utilization"], cpu)
        print(f"{run}/{name}: window {start} .. {end}, {len(disks)} disk points, {len(cpu)} cpu points")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("runs", nargs="+", type=Path)
    for run in p.parse_args().runs:
        export(run)


if __name__ == "__main__":
    main()

"""Reads node disk metrics from Cloud Monitoring for a time window.

Usage: python -m loadtest.diskmetrics --start 2026-11-07T16:40:00Z --end 2026-11-07T17:27:00Z \
           --instance-prefix gke-substrate-smoke-agents-substrate
"""

import os
import argparse
import subprocess
from collections import defaultdict

import requests

PROJECT = os.environ["PROJECT_ID"]
METRICS = [
    "compute.googleapis.com/instance/disk/write_bytes_count",
    "compute.googleapis.com/instance/disk/write_ops_count",
    "compute.googleapis.com/instance/disk/throttled_write_bytes_count",
    "compute.googleapis.com/instance/disk/throttled_write_ops_count",
    "compute.googleapis.com/instance/disk/read_bytes_count",
]


def token() -> str:
    return subprocess.run(["gcloud", "auth", "print-access-token"], check=True,
                          capture_output=True, text=True).stdout.strip()


def series(metric: str, start: str, end: str, prefix: str) -> list[dict]:
    flt = (f'metric.type="{metric}" AND metric.labels.instance_name = starts_with("{prefix}")')
    out, page = [], None
    while True:
        params = {"filter": flt, "interval.startTime": start, "interval.endTime": end,
                  "aggregation.alignmentPeriod": "60s", "aggregation.perSeriesAligner": "ALIGN_RATE"}
        if page:
            params["pageToken"] = page
        r = requests.get(f"https://monitoring.googleapis.com/v3/projects/{PROJECT}/timeSeries",
                         params=params, headers={"Authorization": f"Bearer {token()}"}, timeout=60)
        if r.status_code == 404:  # metric not collected in this project
            return out
        r.raise_for_status()
        body = r.json()
        out.extend(body.get("timeSeries", []))
        page = body.get("nextPageToken")
        if not page:
            return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--instance-prefix", required=True)
    a = p.parse_args()
    for metric in METRICS:
        per_instance = defaultdict(list)
        for s in series(metric, a.start, a.end, a.instance_prefix):
            name = s["metric"]["labels"].get("instance_name", "?")
            device = s["metric"]["labels"].get("device_name", "?")
            for pt in s.get("points", []):
                per_instance[(name[-4:], device)].append(pt["value"].get("doubleValue", 0.0))
        short = metric.rsplit("/", 1)[1]
        for (inst, dev), vals in sorted(per_instance.items()):
            if not vals:
                continue
            vals.sort()
            p50 = vals[len(vals) // 2]
            mx = vals[-1]
            unit = "MB/s" if "bytes" in short else "ops/s"
            scale = 1e6 if "bytes" in short else 1
            print(f"{short:30s} node …{inst} {dev[-18:]:18s} p50 {p50 / scale:8.1f} max {mx / scale:8.1f} {unit}")


if __name__ == "__main__":
    main()

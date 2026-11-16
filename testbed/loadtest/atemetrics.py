"""Reads Substrate's own latency histograms from Cloud Monitoring (managed
OpenTelemetry) for a time window, as p50/p95 per label combination.

Usage: python -m loadtest.atemetrics --start 2026-11-07T19:35:00Z --end 2026-11-07T20:18:00Z
"""

import os
import argparse
import subprocess

import requests

PROJECT = os.environ["PROJECT_ID"]
METRICS = [
    "prometheus.googleapis.com/ate.actor.restore.duration/histogram",
    "prometheus.googleapis.com/ate.actor.checkpoint.duration/histogram",
    "prometheus.googleapis.com/ate.scheduler.assignment.duration/histogram",
]


def token() -> str:
    return subprocess.run(["gcloud", "auth", "print-access-token"], check=True,
                          capture_output=True, text=True).stdout.strip()


def percentile(buckets: list[float], counts: list[int], q: float) -> float | None:
    """Upper bound of the bucket holding quantile q; buckets are explicit bounds."""
    total = sum(counts)
    if total == 0:
        return None
    target = q * total
    seen = 0
    for i, c in enumerate(counts):
        seen += c
        if seen >= target:
            return buckets[i] if i < len(buckets) else float("inf")
    return float("inf")


def query(metric: str, start: str, end: str) -> list[dict]:
    params = {"filter": f'metric.type="{metric}"', "interval.startTime": start, "interval.endTime": end,
              "aggregation.alignmentPeriod": "3600s", "aggregation.perSeriesAligner": "ALIGN_DELTA"}
    r = requests.get(f"https://monitoring.googleapis.com/v3/projects/{PROJECT}/timeSeries",
                     params=params, headers={"Authorization": f"Bearer {token()}"}, timeout=60)
    r.raise_for_status()
    return r.json().get("timeSeries", [])


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    a = p.parse_args()
    for metric in METRICS:
        merged: dict[tuple, list] = {}
        for s in query(metric, a.start, a.end):
            labels = {k: v for k, v in s["metric"].get("labels", {}).items()
                      if k not in ("instance", "service_instance_id", "pod", "node")}
            key = tuple(sorted(labels.items()))
            for pt in s.get("points", []):
                dist = pt["value"]["distributionValue"]
                bounds = dist.get("bucketOptions", {}).get("explicitBuckets", {}).get("bounds", [])
                counts = [int(c) for c in dist.get("bucketCounts", [])]
                if key not in merged:
                    merged[key] = [bounds, [0] * max(len(counts), len(bounds) + 1)]
                for i, c in enumerate(counts):
                    merged[key][1][i] += c
        print(metric.split("/")[1])
        for key, (bounds, counts) in sorted(merged.items(), key=lambda kv: -sum(kv[1][1])):
            n = sum(counts)
            if n == 0:
                continue
            p50, p95 = percentile(bounds, counts, 0.5), percentile(bounds, counts, 0.95)
            print(f"  n={n:6d} p50<={p50} p95<={p95}  {dict(key)}")


if __name__ == "__main__":
    main()

"""Per-step view of Substrate's histograms: sums the per-minute deltas inside
each ladder step's measured window (file mtimes give the window ends).

Usage: python -m loadtest.stepmetrics
"""

import os
import subprocess
from collections import defaultdict

import requests

PROJECT = os.environ["PROJECT_ID"]
BASE = "prometheus.googleapis.com/"
# (label, step end time, window seconds): the measured window is the stats
# reset to the CSV write, two session lengths at think scale 3 (474 s).
WINDOW_S = 474
STEPS = [
    ("pd-balanced 20", "2026-11-07T17:07:21Z"),
    ("pd-balanced 40", "2026-11-07T17:16:25Z"),
    ("pd-balanced 80", "2026-11-07T17:25:39Z"),
    ("local-ssd   20", "2026-11-07T18:48:13Z"),
    ("local-ssd   40", "2026-11-07T18:57:17Z"),
]
METRICS = {
    "restore": "ate.actor.restore.duration/histogram",
    "size": "atelet.snapshot.size/histogram",
    "upload": "atelet.snapshot.upload.duration/histogram",
    "parking": "atenet.router.parking.wait.duration/histogram",
}


def token() -> str:
    return subprocess.run(["gcloud", "auth", "print-access-token"], check=True,
                          capture_output=True, text=True).stdout.strip()


def iso(ts: float) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(ts, datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(t: str) -> float:
    import datetime
    return datetime.datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.UTC).timestamp()


def merged(metric: str, start: str, end: str, keep: tuple[str, ...]) -> dict[tuple, tuple[list, list]]:
    params = {"filter": f'metric.type="{BASE}{metric}"', "interval.startTime": start, "interval.endTime": end,
              "aggregation.alignmentPeriod": "60s", "aggregation.perSeriesAligner": "ALIGN_DELTA"}
    r = requests.get(f"https://monitoring.googleapis.com/v3/projects/{PROJECT}/timeSeries",
                     params=params, headers={"Authorization": f"Bearer {token()}"}, timeout=60)
    r.raise_for_status()
    out: dict[tuple, tuple[list, list]] = {}
    for s in r.json().get("timeSeries", []):
        labels = s["metric"].get("labels", {})
        key = tuple(labels.get(k, "") for k in keep)
        for pt in s.get("points", []):
            d = pt["value"]["distributionValue"]
            bounds = d.get("bucketOptions", {}).get("explicitBuckets", {}).get("bounds", [])
            counts = [int(c) for c in d.get("bucketCounts", [])]
            b, c = out.setdefault(key, (bounds, [0] * (len(bounds) + 1)))
            for i, n in enumerate(counts):
                c[i] += n
    return out


def pct(bounds: list, counts: list, q: float) -> str:
    total = sum(counts)
    if not total:
        return "-"
    seen = 0
    for i, n in enumerate(counts):
        seen += n
        if seen >= q * total:
            return f"<={bounds[i]:g}" if i < len(bounds) else f">{bounds[-1]:g}"
    return "?"


def main() -> None:
    for label, end in STEPS:
        e = parse(end)
        start, stop = iso(e - WINDOW_S), iso(e)
        print(f"== {label} sessions ({start[11:19]}-{stop[11:19]})")
        rest = merged(METRICS["restore"], start, stop, ("ate.snapshot.kind", "ate.snapshot.phase"))
        for kind in ("local", "latest"):
            tot = rest.get((kind, "total"))
            if tot and sum(tot[1]):
                dl = rest.get((kind, "download"))
                extra = f" download p50 {pct(*dl, 0.5)} p95 {pct(*dl, 0.95)} s" if dl and sum(dl[1]) else ""
                print(f"  restore {kind:6s} n={sum(tot[1]):5d}  total p50 {pct(*tot, 0.5)} p95 {pct(*tot, 0.95)} s{extra}")
        for name in ("size", "upload", "parking"):
            for key, (b, c) in merged(METRICS[name], start, stop, ()).items():
                if sum(c):
                    unit = "bytes" if name == "size" else "s"
                    print(f"  {name:8s} n={sum(c):5d}  p50 {pct(b, c, 0.5)} p95 {pct(b, c, 0.95)} {unit}")


if __name__ == "__main__":
    main()

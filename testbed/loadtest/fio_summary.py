"""Summarizes infra/fio.sh output: throughput and latency per job.

Usage: python -m loadtest.fio_summary results/disks/*/fio.log
"""

import json
import sys
from pathlib import Path


def jobs(path: Path) -> dict[str, dict]:
    text = path.read_text()
    out = {}
    for block in text.split("== ")[1:]:
        name, _, body = block.partition("\n")
        start = body.find("{")
        if name.strip() == "done" or start < 0:
            continue
        out[name.strip()] = json.loads(body[start:body.rfind("}") + 1])["jobs"][0]
    return out


def summarize(job: dict) -> str:
    side = "write" if job["write"]["io_bytes"] else "read"
    s = job[side]
    mbs = s["bw_bytes"] / 1e6
    pct = s["clat_ns"].get("percentile", {})
    p50 = pct.get("50.000000", 0) / 1e6
    p99 = pct.get("99.000000", 0) / 1e6
    return f"{mbs:8.0f} MB/s  {s['iops']:8.0f} IOPS  lat p50 {p50:7.2f} ms  p99 {p99:7.2f} ms"


def main() -> None:
    for arg in sys.argv[1:]:
        p = Path(arg)
        print(f"== {p.parent.name}")
        for name, job in jobs(p).items():
            print(f"  {name:12s} {summarize(job)}")


if __name__ == "__main__":
    main()

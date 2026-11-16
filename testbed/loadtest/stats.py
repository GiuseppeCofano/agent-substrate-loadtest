"""Reads Locust's stats CSV export."""

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Row:
    name: str
    requests: int
    failures: int
    p50: float | None
    p95: float | None
    max: float | None


def _num(value: str) -> float | None:
    if value in ("", "N/A"):
        return None
    return float(value)


def read_stats(path: str | Path) -> dict[str, Row]:
    """Returns the export's rows keyed by name; "Aggregated" is the total."""
    rows = {}
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            rows[r["Name"]] = Row(
                name=r["Name"],
                requests=int(r["Request Count"]),
                failures=int(r["Failure Count"]),
                p50=_num(r["50%"]),
                p95=_num(r["95%"]),
                max=_num(r["Max Response Time"]),
            )
    return rows

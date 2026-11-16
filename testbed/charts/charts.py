# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib>=3.8"]
# ///
"""Regenerates the two disk-matrix charts from the published data.

Usage (from the repository root): uv run testbed/charts/charts.py
Writes charts/capacity-vs-throughput.png and charts/suspend-p95-40.png.
"""

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FixedLocator, NullFormatter  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "disk-matrix"
OUT = ROOT / "charts"
YARDSTICK = 40  # data/yardstick-one-pod-per-session/ladder/summary.json

FAMILIES = {  # family: (colour, marker, config prefix)
    "pd-balanced": ("#2A7AD6", "o", "n2-pd-balanced"),
    "pd-ssd": ("#E8663A", "s", "n2-pd-ssd"),
    "Local SSD": ("#19A97B", "D", "n2-local-ssd"),
    "Hyperdisk Balanced": ("#E6A100", "^", "n4-hyperdisk"),
}
LABELS = {
    "n2-pd-balanced-100gb": "pd-balanced 100 GB (default)", "n2-pd-balanced-1tb": "pd-balanced 1 TB",
    "n2-pd-ssd-100gb": "pd-ssd 100 GB", "n2-pd-ssd-1tb": "pd-ssd 1 TB",
    "n2-local-ssd-x1": "Local SSD x1", "n2-local-ssd-x2-raid0": "Local SSD x2",
    "n2-local-ssd-x4-raid0": "Local SSD x4", "n4-hyperdisk-balanced-140": "Hyperdisk 140",
    "n4-hyperdisk-balanced-300": "Hyperdisk 300", "n4-hyperdisk-balanced-600": "Hyperdisk 600",
    "n4-hyperdisk-balanced-1200": "Hyperdisk 1,200",
}
OFFSETS = {  # label offsets in points, chosen so labels clear each other
    "n2-pd-balanced-100gb": (8, 8), "n2-pd-balanced-1tb": (8, -16), "n2-pd-ssd-100gb": (-60, 10),
    "n2-pd-ssd-1tb": (-40, 10), "n2-local-ssd-x1": (8, -16), "n2-local-ssd-x2-raid0": (2, -18),
    "n2-local-ssd-x4-raid0": (-25, -18), "n4-hyperdisk-balanced-140": (-30, -18),
    "n4-hyperdisk-balanced-300": (-10, -18), "n4-hyperdisk-balanced-600": (-90, -4),
    "n4-hyperdisk-balanced-1200": (-50, 10),
}


def family(cfg: str) -> str:
    return next(f for f, (_, _, prefix) in FAMILIES.items() if cfg.startswith(prefix))


def configs() -> list[dict]:
    with (DATA / "configs.csv").open() as f:
        return list(csv.DictReader(f))


def style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_facecolor("white")


def capacity_chart(rows):
    fig, ax = plt.subplots(figsize=(10, 5.6), dpi=140)
    fig.patch.set_facecolor("white")
    style(ax)
    for fam, (colour, marker, _) in FAMILIES.items():
        pts = [r for r in rows if family(r["config"]) == fam]
        ax.scatter([float(r["fio_seq_write_MBps"]) for r in pts], [int(r["capacity_sessions"]) for r in pts],
                   color=colour, marker=marker, s=60, label=fam, zorder=3)
    for r in rows:
        ax.annotate(LABELS[r["config"]], (float(r["fio_seq_write_MBps"]), int(r["capacity_sessions"])),
                    textcoords="offset points", xytext=OFFSETS[r["config"]], fontsize=9, color="#444")
    ax.axhline(YARDSTICK, color="#555", linestyle="--", linewidth=1.2, zorder=1)
    ax.text(2000, YARDSTICK + 1.5, "one pod per session (measured): 40", ha="right", fontsize=9, color="#444")
    ax.set_xscale("log")
    ax.xaxis.set_major_locator(FixedLocator([150, 300, 600, 1200]))
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.set_xlim(110, 2100)
    ax.set_ylim(0, 100)
    ax.set_yticks([0, 20, 40, 60, 80, 100])
    ax.grid(axis="y", color="#e5e5e5", zorder=0)
    ax.set_xlabel("Sequential write throughput of the node disk (MB/s, fio, log scale)")
    ax.set_ylabel("Capacity (concurrent sessions)")
    ax.set_title("Substrate capacity steps up with disk write throughput", loc="left", fontsize=13)
    ax.legend(loc="upper left", frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(OUT / "capacity-vs-throughput.png", facecolor="white")


def suspend_p95(cfg: str) -> float:
    with (DATA / cfg / "ladder" / "step-40.csv").open() as f:
        for row in csv.DictReader(f):
            if row["Name"] == "SuspendActorAsync":
                return float(row["95%"]) / 1000
    raise ValueError(f"no SuspendActorAsync for {cfg}")


def suspend_chart(rows):
    bars = sorted(((r["config"], suspend_p95(r["config"])) for r in rows), key=lambda b: b[1])
    fig, ax = plt.subplots(figsize=(10, 5.2), dpi=140)
    fig.patch.set_facecolor("white")
    style(ax)
    for i, (cfg, secs) in enumerate(bars):
        ax.barh(i, secs, color=FAMILIES[family(cfg)][0], height=0.6, zorder=2)
        ax.text(secs + 0.4, i, f"{secs:.1f} s", va="center", fontsize=9, color="#444")
    ax.set_yticks(range(len(bars)))
    ax.set_yticklabels([LABELS[c] for c, _ in bars], fontsize=9)
    ax.grid(axis="x", color="#e5e5e5", zorder=0)
    ax.set_xlabel("Suspend latency, p95 (seconds)")
    ax.set_title("At 40 sessions, a slow disk turns a suspend into half a minute", loc="left", fontsize=13)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c, _, _ in FAMILIES.values()]
    ax.legend(handles, FAMILIES.keys(), loc="lower right", frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(OUT / "suspend-p95-40.png", facecolor="white")


def main():
    OUT.mkdir(exist_ok=True)
    rows = configs()
    capacity_chart(rows)
    suspend_chart(rows)
    print(f"wrote {OUT}/capacity-vs-throughput.png and suspend-p95-40.png")


if __name__ == "__main__":
    main()

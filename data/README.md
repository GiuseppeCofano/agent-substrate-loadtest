# Data

All runs: GKE 1.37.1-gke.3020000, zonal `europe-west4-a`. The measured pool has
3 nodes with 16 vCPU each (`n2-standard-16`, or `n4-standard-16` for
Hyperdisk), and 45 worker slots of 1 vCPU (15 per node). The load is Substrate's
`agentsession` scenario at think scale 3, which means about 10 s of simulated
LLM wait per step and the agent idle about 87% of the time. Times are UTC.

## Run layout

A *ladder* is one calibration plus increasing load steps:

- **Calibration**: a single session, measured the same way as the steps.
- **Steps**: 10, 20, 40, 80 concurrent sessions, then 160 when 80 passes.
- **Each step**: sessions start at 2 per second. After 60 s of warm-up the
  statistics are reset, then the step is measured for 474 s (two full script
  cycles). The step's CSV is written at the end of that window, so the window
  is the 474 s before the file's modification time.
- **Pass rules**: a step passes when all four hold:
  1. each script step's p95 is ≤ 1.5× calibration, or less than 250 ms above it;
  2. failures are below 1%;
  3. steps per session are ≥ 80% of calibration;
  4. the p95 of `WakeFirstTouch` is ≤ 2 s (Substrate only).
- **Capacity**: the last step that passes.

## Files in a ladder folder

| File | Content |
|---|---|
| `calibration.csv`, `step-<N>.csv` | Locust statistics, one row per request type. Columns: request count, failure count, median, average, min, max, then percentiles 50% to 100%, all in ms. |
| `*-failures.csv` | Failed requests grouped by error: `Method,Name,Error,Occurrences`. |
| `summary.json` | Pass or fail per step with the failing rules, and the resulting capacity. |
| `cloud-monitoring/` | Exported from Cloud Monitoring for the step's measured window (see below). |

Request types in the step CSVs:

| Name | What it measures |
|---|---|
| `Step_01_read_task` … `Step_20_commit_and_summarize` | The 20 script steps of the simulated coding agent. Each is real CPU, memory, disk and network work inside the sandbox. |
| `SuspendActorAsync` | Substrate suspend call: checkpoint of the sandbox to the node disk. |
| `WakeFirstTouch` | First request after a suspend, including the resume. This is the wake latency in the post. |
| `TimeToWake` | Summary row for the same wakes. |
| `SessionStart`, `CreateActor`, `CreateAtespace` | Session setup. Mostly zero in steps, because statistics are reset after warm-up. |
| `CreateSandbox`, `DeleteSandbox` | Yardstick only: creating and deleting the session's pod. |

## Files in `cloud-monitoring/`

These files were exported by `testbed/loadtest/export_metrics.py`. Each one covers
the step's measured window.

| File | Content |
|---|---|
| `step-<N>-substrate-histograms.csv` | Substrate histograms (`ate.*`, `atelet.*`, `atenet.*`) summed over the window, one row per label combination. Columns: count, the p50 and p95 bucket bounds, the bucket bounds and the bucket counts. Restores are labelled by `ate.snapshot.kind`: `local` is on the same node, `latest` came from object storage on another node. Scheduler outcomes are labelled by `ate.scheduler.outcome`: `assigned` or `no_capacity`. |
| `step-<N>-substrate-gauges.csv` | Per minute: undurable snapshot age, router requests parked, workers per state, actor crashes. |
| `step-<N>-disks.csv` | Per minute, per node and per device: Compute Engine disk read and write bytes and ops per second, and throttled write bytes. Local SSDs appear as `local-ssd-0..3`. |
| `step-<N>-node-cpu.csv` | Per minute, per node: CPU allocatable utilization (0–1). |

Substrate's histogram buckets are coarse (… 1, 2.5, 5, 10 s …). A p95 of `<=10`
means the 95th percentile falls in the bucket that ends at 10 s.

## `disk-matrix/`

`configs.csv` lists every configuration with:

- the machine and the disk;
- the exact node pool flags;
- the router parking budget;
- the fio sequential write result;
- the capacity, and the result of the extra 120-session step.

| Folder or file | Content |
|---|---|
| `<config>/fio.log` | fio JSON per job, each block headed `== <job>`. Jobs: `seqwrite1` (1 MiB sequential writes, one stream), `seqwrite4` (four streams), `seqread1`, `randwrite4k` and `randread4k` (queue depth 1). |
| `<config>/setup.log` | Node pool creation, the mount, and the atelet and worker restart. |
| `<config>/ladder/` | The Substrate ladder. |
| `<config>/step-120/` | A fresh calibration and one 120-session step. Only for the configurations that reached 80. |
| `n2-local-ssd-x2-raid0/ladder-router-budget-5s/` | The same ladder with the router's default 5 s parking budget, kept for comparison. |
| `runner-logs/` | Timestamped logs of the unattended runner (`matrix.log` for the matrix, `step120.log` for the 120-session steps). |

Two configurations ran before the parking budget was raised to 20 s:
`n2-pd-balanced-100gb` and `n2-local-ssd-x1`. Their ladders are evaluated with
the same rules.

## `yardstick-one-pod-per-session/`

The same ladder with one GKE Sandbox (gVisor) pod per session instead of
Substrate. It ran on 3 × `n2-standard-16` with the default disk and 45 slots of
1 vCPU. Capacity is 40. At 80 sessions, pods wait for free slots.

## `diagnostics/restore-overlap-local-ssd-x1/`

This is a 40-session ladder step on one Local SSD, with atelet logs streamed live
from all three nodes (`live/atelet-*.log.gz`). Each restore and checkpoint logs a
timing breakdown. Counting the operations in flight on the same node at each
restore's start gives the restore-overlap table in the post. `top-nodes.txt`
and `top-workers.txt` hold `kubectl top` samples taken every minute.

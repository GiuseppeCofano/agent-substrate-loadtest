# Agent Substrate on GKE: storage load test data

Measured data and testbed scripts behind the post *From 20 to 120 agent sessions
on three GKE nodes: tuning Agent Substrate's storage*.

The test ran [Agent Substrate](https://github.com/agent-substrate/substrate)
v0.6.0 on GKE 1.37 (`europe-west4-a`, November 2026). The load was a simulated
coding agent at about 10 s of simulated LLM wait per step. The same three
16-vCPU nodes ran with 11 different node-storage configurations, and each
configuration went through a load ladder.

## Layout

```
data/
  disk-matrix/                  one folder per storage configuration
    configs.csv                 index: machine, disk, node pool flags, fio result, capacity
    <config>/
      fio.log                   fio run on an idle node before the ladder
      setup.log                 node pool creation and mount
      ladder/                   Substrate load ladder: calibration + steps 10..160
        step-<N>.csv            load generator statistics for N concurrent sessions
        cloud-monitoring/       Substrate, disk and node CPU metrics for each step's window
      step-120/                 extra 120-session step (configurations that reached 80)
    disk-rates-120-sessions.txt per-node disk read/write rates at 120 sessions
    runner-logs/                the unattended runner's logs
  yardstick-one-pod-per-session/  the same ladder with one GKE Sandbox pod per session
  diagnostics/
    restore-overlap-local-ssd-x1/ live atelet logs used for the restore-overlap analysis
testbed/
  infra/        cluster, node pool, disk and run scripts (bash, kubectl, gcloud)
  loadtest/     ladder driver, pass/fail evaluation, metric exporters (Python)
  tests/        tests for loadtest/
  charts/       regenerates the post's disk charts from data/
```

`data/README.md` describes every file format. `testbed/README.md` explains how
the runs were produced and how to repeat them.

## Where each number in the post comes from

| Claim in the post | Source |
|---|---|
| Capacity per disk configuration (20 / 40 / 80 sessions) | `data/disk-matrix/configs.csv`, each `<config>/ladder/summary.json` |
| fio sequential write, parallel write and 4 KiB latency | `data/disk-matrix/<config>/fio.log` |
| Default disk pinned at 176.2 MB/s at 40 sessions | `data/disk-matrix/n2-pd-balanced-100gb/ladder/cloud-monitoring/step-40-disks.csv` |
| Suspend p95 at 40 sessions per disk | `<config>/ladder/step-40.csv`, row `SuspendActorAsync` |
| 120-session comparison (wake, suspend, work done, failures) | `<config>/step-120/step-120.csv` and `summary.json` |
| Per-node disk rates at 120 sessions | `data/disk-matrix/disk-rates-120-sessions.txt`, `<config>/step-120/cloud-monitoring/step-120-disks.csv` |
| 160 sessions on Local SSD x4: no free worker, cross-node restores, parking | `n2-local-ssd-x4-raid0/ladder/cloud-monitoring/step-160-substrate-histograms.csv` |
| Node CPU at 80 / 120 / 160 sessions | `cloud-monitoring/step-<N>-node-cpu.csv` |
| Restore p95 against overlapping operations (Local SSD x1) | `data/diagnostics/restore-overlap-local-ssd-x1/live/atelet-*.log.gz` |
| Yardstick: one pod per session holds 40 | `data/yardstick-one-pod-per-session/ladder/summary.json` |
| Yardstick writes about 0.6 MB/s per node | `data/yardstick-one-pod-per-session/ladder/cloud-monitoring/step-40-disks.csv` |

## Caveats

- One run per configuration, at one load level.
- Substrate's histogram buckets are coarse (1, 2.5, 5, 10 s), so percentiles
  taken from Cloud Monitoring are bucket bounds.
- The snapshot size of about 300 MB is an estimate: disk write rate divided by
  checkpoint rate.
- Project IDs, account names and home paths are replaced with placeholders
  (`PROJECT_ID`, `PROJECT_NUMBER`, `~`).

## Substrate changes used

The load generator needed changes on top of v0.6.0. They are on the
`loadtest-baselines` branch of
[GiuseppeCofano/substrate](https://github.com/GiuseppeCofano/substrate/tree/loadtest-baselines),
at commit `a850c1c1`:

- pod and warm pool baselines for the `agentsession` benchmark;
- `setup-gcp` flags for Secure Boot and private nodes;
- the upstream fix that makes the benchmark reach the router over mTLS.

## License

Apache License 2.0, see [LICENSE](LICENSE).

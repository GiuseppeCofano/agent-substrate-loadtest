# Testbed

These are the scripts that produced `data/`. They are published as they were
run, with project identifiers replaced, so read them as a record and as a
starting point rather than as a turnkey installer.

## Prerequisites

- **GCP project and tools**: a GCP project with GKE, Compute Engine, Cloud
  Storage, Artifact Registry and Cloud Monitoring enabled. `gcloud`, `kubectl`,
  Docker, Go and [ko](https://ko.build) on the machine that builds.
- **Substrate checkout**: the `loadtest-baselines` branch of
  [GiuseppeCofano/substrate](https://github.com/GiuseppeCofano/substrate/tree/loadtest-baselines)
  (commit `a850c1c1`, based on v0.6.0), checked out as `substrate/` next to
  `testbed/`. It adds the baselines and the setup flags the scripts expect.
- **Environment file**: `ate-dev-env.example.sh` copied to `.ate-dev-env.sh` at
  the repository root, with your project, region and cluster names.
- **Python environment**: Python 3.13 (tested) with `requirements.txt` installed in
  `.venv`, for `loadtest/`.
- **`PROJECT_ID` for the exporters**: the metric exporters in `loadtest/` read
  the project from the `PROJECT_ID` environment variable.

The paths in the scripts assume the original layout: `infra/`, `loadtest/`,
`tests/` and `substrate/` side by side, with results written to `results/`.
Copy `testbed/*` to the repository root (or adjust `ROOT`) before running.

## The cluster

`infra/up.sh` creates the cluster with Substrate's `setup-gcp` and `ate-setup`.
The cluster has these node pools:

| Pool | Nodes | Role |
|---|---|---|
| `substrate-node-pool` | 2 × `n2-standard-4`, tainted | Substrate control plane, Locust |
| `postgres` | 1 × `n2-standard-4`, tainted | PostgreSQL for ate-api-server |
| `agents-substrate` | 3 × 16 vCPU, created at 0 | Substrate workers: the measured pool |
| `agents-sandbox` | 3 × `n2-standard-16`, GKE Sandbox, created at 0 | the one-pod-per-session yardstick |

`up.sh` also applies three settings:

- **Router parking budget**: `--parked-request-budget=20s` on `atenet-router`.
  The default 5 s turns slow wakes into errors capped at 10 s.
- **WorkerPool requests**: 1 vCPU and 1280 MiB per worker, with a nodeSelector
  for `agents-substrate`. Without a CPU request the workers pack onto one node.
- **Locust**: deployed through `infra/locust.sh` and pinned to the control-plane
  pool.

The project ran under an organization with restrictive policies, which shaped
the setup:

- no default VPC, so a custom VPC with Cloud NAT;
- Shielded VMs required, so Secure Boot on every pool;
- no external IPs, so private nodes reached through the GKE DNS endpoint.

## The disk matrix

```
infra/disk-matrix.sh            # unattended: for each configuration in turn
  infra/disk-config.sh <cfg>    # recreate agents-substrate with that disk, mount /var/lib/ate,
                                # restart atelet and workers on the new nodes
  infra/fio.sh <dir>            # fio on one idle node, writing to /var/lib/ate
  python -m loadtest.ladder ... # calibration + 10, 20, 40, 80 (+160) sessions
infra/step120.sh                # fresh calibration + 120 sessions for the configurations at 80
```

Configuration names in `disk-config.sh` map to `data/disk-matrix/` as follows:

| `disk-config.sh` | `data/disk-matrix/` |
|---|---|
| `pdb100`, `pdb1t` | `n2-pd-balanced-100gb`, `n2-pd-balanced-1tb` |
| `pdssd100`, `pdssd1t` | `n2-pd-ssd-100gb`, `n2-pd-ssd-1tb` |
| `lssd1`, `lssd2`, `lssd4` | `n2-local-ssd-x1`, `n2-local-ssd-x2-raid0`, `n2-local-ssd-x4-raid0` |
| `hdb140` … `hdb1200` | `n4-hyperdisk-balanced-140` … `-1200` |

**Local SSD mounts.** Local SSD configurations need a mount on `/var/lib/ate`
before atelet starts using it:

- `local-ssd-mount.yaml` formats and mounts one raw NVMe device.
- `local-ssd-raid-mount.yaml` bind-mounts a directory on the RAID 0 array that
  GKE builds with `--ephemeral-storage-local-ssd`.

Both are privileged DaemonSets that use `nsenter`.

**Long runs.** These went on a small VM (`e2-medium`) in the same VPC, so a
sleeping laptop could not stop them:

- the `start-*.sh` scripts launch a runner detached from the SSH session;
- `stop-runner.sh` stops one cleanly.

## The yardstick

The pod-per-session baseline was produced with these scripts:

- `infra/render-baselines.sh` renders the pod manifest.
- `infra/baseline.sh pod` installs it.
- `infra/b1-medium.sh` runs the ladder at the same think scale.

## The load ladder (`loadtest/`)

| Module | Role |
|---|---|
| `ladder.py` | Drives Locust through its web API: calibration, steps, hold time, cleanup between ladders, CSV download. |
| `evaluate.py` | The four pass rules and the capacity. |
| `stats.py`, `locust_api.py`, `cluster.py` | Locust CSV parsing, the API client, and cluster checks (leftover actors, worker placement). |
| `export_metrics.py` | Exports each step's Cloud Monitoring window into `cloud-monitoring/`. |
| `diskmetrics.py`, `atemetrics.py`, `stepmetrics.py` | Ad-hoc queries used during the analysis. |
| `fio_summary.py` | Turns `fio.log` into one line per job. |

To run the tests: `python -m pytest tests`.

## Charts

`uv run testbed/charts/charts.py` regenerates the post's two disk charts in
`charts/` from `data/disk-matrix/`.

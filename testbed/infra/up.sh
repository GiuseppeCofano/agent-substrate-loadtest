#!/usr/bin/env bash
# Creates the measurement cluster; see
# docs/superpowers/plans/2026-11-07-gke-runs-and-analysis.md. Leaves both
# measured pools at 0 nodes.
set -o errexit -o nounset -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT}/.ate-dev-env.sh"
SPOT=()
if [[ "${1:-}" == "--spot" ]]; then
  SPOT=(--spot)
fi
P="${PROJECT_ID}" Z="${CLUSTER_LOCATION}" C="${CLUSTER_NAME}"
COMMON=(--cluster="${C}" --location="${Z}" --project="${P}" --node-version="${NODE_POOL_VERSION}"
        --shielded-secure-boot --shielded-integrity-monitoring --quiet)

cd "${ROOT}/substrate"
mkdir -p "${ROOT}/bin"
go build -o "${ROOT}/bin/kubectl-ate" ./cmd/kubectl-ate
# setup-gcp creates the cluster with its 2-node substrate-node-pool, which
# becomes the control-plane pool.
go run ./tools/setup-gcp bootstrap
gcloud container clusters update "${C}" --location="${Z}" --project="${P}" --enable-dns-access --quiet
gcloud container clusters get-credentials "${C}" --location="${Z}" --project="${P}" --dns-endpoint
# gcloud takes one kind of change per node-pools update call.
gcloud container node-pools update substrate-node-pool --cluster="${C}" --location="${Z}" --project="${P}" \
  --node-labels=ate.dev/workloadType=ate-control-plane --quiet
gcloud container node-pools update substrate-node-pool --cluster="${C}" --location="${Z}" --project="${P}" \
  --node-taints=ate.dev/workloadType=ate-control-plane:NoSchedule --quiet
pool_exists() {
  gcloud container node-pools describe "$1" --cluster="${C}" --location="${Z}" --project="${P}" >/dev/null 2>&1
}
pool_exists postgres || gcloud container node-pools create postgres "${COMMON[@]}" --machine-type=n2-standard-4 --num-nodes=1 \
  --node-labels=ate.dev/workloadType=ate-postgres --node-taints=ate.dev/workloadType=ate-postgres:NoSchedule
pool_exists agents-substrate || gcloud container node-pools create agents-substrate "${COMMON[@]}" --machine-type=n2-standard-16 --num-nodes=0 \
  ${SPOT[@]+"${SPOT[@]}"}
pool_exists agents-sandbox || gcloud container node-pools create agents-sandbox "${COMMON[@]}" --machine-type=n2-standard-16 --num-nodes=0 \
  ${SPOT[@]+"${SPOT[@]}"} --image-type=cos_containerd --sandbox type=gvisor

go run ./cmd/ate-setup deploy ate-system --credential-provider='{"name":"k8s.io"}' --cordon-control-plane
# The 5 s default turns slow wakes under load into errors capped at 10 s
# (budget plus Envoy's 5 s); 20 s keeps Envoy's 25 s under the benchmark
# client's 30 s timeout. See docs/guides/benchmarking.md on dense runs.
kubectl -n ate-system patch deployment atenet-router --type=json \
  -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--parked-request-budget=20s"}]'
kubectl -n ate-system rollout status deployment/atenet-router --timeout=300s
"${ROOT}/infra/pools.sh" substrate
./benchmarking/deploy_locust.sh --deploy --sandbox-class gvisor --actor-memory 1Gi --actor-cpu 1 \
  --worker-memory "${SUBSTRATE_WORKER_MEMORY:-1280Mi}" --worker-count "${SUBSTRATE_WORKERS:-45}"
# Workers only on the measured pool, one CPU each like a B1 pod, so the
# scheduler spreads them 15 per node instead of packing them by memory.
kubectl -n benchmark-workloads patch workerpool benchmark-worker --type=merge \
  -p '{"spec":{"template":{"nodeSelector":{"cloud.google.com/gke-nodepool":"agents-substrate"},
  "resources":{"requests":{"cpu":"1","memory":"1280Mi"},"limits":{"memory":"1280Mi"}}}}}'
"${ROOT}/infra/locust.sh" substrate
"${ROOT}/infra/pools.sh" none
echo "cluster ready; measured pools at 0"

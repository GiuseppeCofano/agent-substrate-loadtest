#!/usr/bin/env bash
# Recreates the agents-substrate pool with one Local SSD per node, mounts it on
# /var/lib/ate, restarts atelet and the workers there, and leaves the pool up.
# The pool must be at 0 nodes.
set -o errexit -o nounset -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT}/.ate-dev-env.sh"
P="${PROJECT_ID}" Z="${CLUSTER_LOCATION}" C="${CLUSTER_NAME}"

pool="$(gcloud container node-pools describe agents-substrate --cluster="${C}" --location="${Z}" --project="${P}" \
  --format="value(status,config.localNvmeSsdBlockConfig.localSsdCount)" 2>/dev/null || true)"
# A pool whose creation failed is left in ERROR with the requested config.
if [[ "${pool}" == RUNNING*2 ]]; then
  echo "agents-substrate already has a Local SSD"
else
  if [[ -n "${pool}" ]]; then
    gcloud container node-pools delete agents-substrate --cluster="${C}" --location="${Z}" --project="${P}" --quiet
  fi
  gcloud container node-pools create agents-substrate --cluster="${C}" --location="${Z}" --project="${P}" \
    --node-version="${NODE_POOL_VERSION}" --machine-type=n2-standard-16 --num-nodes=0 \
    --local-nvme-ssd-block count=2 --shielded-secure-boot --shielded-integrity-monitoring --quiet
fi
kubectl apply -f "${ROOT}/infra/local-ssd-mount.yaml"
"${ROOT}/infra/pools.sh" substrate
kubectl -n kube-system rollout status daemonset/ate-local-ssd --timeout=600s
# atelet and the workers started before the mount; restart them on top of it.
for node in $(kubectl get nodes -l cloud.google.com/gke-nodepool=agents-substrate -o name); do
  n="${node#node/}"
  kubectl -n ate-system delete pod -l app=atelet --field-selector="spec.nodeName=${n}" --wait=true
done
kubectl -n ate-system rollout status daemonset/atelet --timeout=600s
kubectl -n benchmark-workloads delete pod -l ate.dev/worker-pool=benchmark-worker --wait=false
for pod in $(kubectl -n kube-system get pods -l app=ate-local-ssd -o name); do
  kubectl -n kube-system logs "${pod}" | tail -2
done

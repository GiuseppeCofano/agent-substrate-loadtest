#!/usr/bin/env bash
# Recreates the agents-substrate pool (n2-standard-16 x3) with one disk
# configuration for /var/lib/ate, then restarts atelet and the workers on it.
# Configs: pdb100 pdb1t pdssd100 pdssd1t (boot disk), lssd1 (one raw Local SSD),
# lssd2 lssd4 (GKE RAID 0 of 2 or 4 Local SSDs), hdb140 hdb300 hdb600 hdb1200
# (n4-standard-16 with a Hyperdisk Balanced boot disk at that many MiB/s and
# 6,000 IOPS, so only the throughput changes).
set -o errexit -o nounset -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT}/.ate-dev-env.sh"
P="${PROJECT_ID}" Z="${CLUSTER_LOCATION}" C="${CLUSTER_NAME}"
cfg="${1:?usage: $0 pdb100|pdb1t|pdssd100|pdssd1t|lssd1|lssd2|lssd4|hdb140|hdb300|hdb600|hdb1200}"
mount=""
machine=n2-standard-16
case "${cfg}" in
  pdb100) disk=(--disk-type=pd-balanced --disk-size=100) ;;
  pdb1t) disk=(--disk-type=pd-balanced --disk-size=1024) ;;
  pdssd100) disk=(--disk-type=pd-ssd --disk-size=100) ;;
  pdssd1t) disk=(--disk-type=pd-ssd --disk-size=1024) ;;
  lssd1) disk=(--disk-type=pd-balanced --disk-size=100 --local-nvme-ssd-block=count=2); mount=local-ssd-mount.yaml ;;
  lssd2) disk=(--disk-type=pd-balanced --disk-size=100 --ephemeral-storage-local-ssd=count=2); mount=local-ssd-raid-mount.yaml ;;
  lssd4) disk=(--disk-type=pd-balanced --disk-size=100 --ephemeral-storage-local-ssd=count=4); mount=local-ssd-raid-mount.yaml ;;
  hdb140|hdb300|hdb600|hdb1200)
    machine=n4-standard-16
    disk=(--disk-type=hyperdisk-balanced --disk-size=100 --boot-disk-provisioned-iops=6000
          "--boot-disk-provisioned-throughput=${cfg#hdb}") ;;
  *) echo "unknown config ${cfg}" >&2; exit 1 ;;
esac

current="$(gcloud container node-pools describe agents-substrate --cluster="${C}" --location="${Z}" --project="${P}" \
  --format='value(status,config.labels."loadtest/disk")' 2>/dev/null || true)"
if [[ "${current}" != "RUNNING"*"${cfg}" ]]; then
  if [[ -n "${current}" ]]; then
    "${ROOT}/infra/pools.sh" none
    gcloud container node-pools delete agents-substrate --cluster="${C}" --location="${Z}" --project="${P}" --quiet
  fi
  gcloud container node-pools create agents-substrate --cluster="${C}" --location="${Z}" --project="${P}" \
    --node-version="${NODE_POOL_VERSION}" --machine-type="${machine}" --num-nodes=0 \
    --node-labels="loadtest/disk=${cfg}" "${disk[@]}" \
    --shielded-secure-boot --shielded-integrity-monitoring --quiet
fi
kubectl -n kube-system delete daemonset ate-local-ssd --ignore-not-found --wait=true
if [[ -n "${mount}" ]]; then
  kubectl apply -f "${ROOT}/infra/${mount}"
fi
"${ROOT}/infra/pools.sh" substrate
if [[ -n "${mount}" ]]; then
  kubectl -n kube-system rollout status daemonset/ate-local-ssd --timeout=600s
  for pod in $(kubectl -n kube-system get pods -l app=ate-local-ssd -o name); do
    kubectl -n kube-system logs "${pod}" | tail -4
  done
fi
# atelet and the workers may have started before the mount; restart them.
for node in $(kubectl get nodes -l cloud.google.com/gke-nodepool=agents-substrate -o name); do
  kubectl -n ate-system delete pod -l app=atelet --field-selector="spec.nodeName=${node#node/}" --wait=true
done
kubectl -n ate-system rollout status daemonset/atelet --timeout=600s
kubectl -n benchmark-workloads delete pod -l ate.dev/worker-pool=benchmark-worker --wait=false
for _ in $(seq 1 60); do
  running="$(kubectl -n benchmark-workloads get pods --no-headers 2>/dev/null | grep -c Running || true)"
  if (( running >= 45 )); then break; fi
  sleep 10
done
echo "config ${cfg} ready: $(kubectl -n benchmark-workloads get pods --no-headers | grep -c Running) workers Running"

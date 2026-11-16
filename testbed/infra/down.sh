#!/usr/bin/env bash
# Deletes the measurement cluster. Network, NAT, bucket, images and IAM stay.
set -o errexit -o nounset -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT}/.ate-dev-env.sh"
# Deleting the cluster leaves PersistentVolume disks behind (postgres keeps a
# 500 GB one), so delete the claims first and let GKE delete the disks.
kubectl -n ate-system delete statefulset postgres --ignore-not-found --wait=true --timeout=300s || true
kubectl delete pvc --all --all-namespaces --wait=true --timeout=300s || true
kubectl wait --for=delete pv --all --timeout=300s || true
gcloud container clusters delete "${CLUSTER_NAME}" --location="${CLUSTER_LOCATION}" --project="${PROJECT_ID}" --quiet
left="$(gcloud compute disks list --project="${PROJECT_ID}" --filter="name~^pvc- AND -users:*" --format="value(name)")"
if [[ -n "${left}" ]]; then
  echo "unattached PVC disks remain, delete them by hand if they are from this cluster:" >&2
  echo "${left}" >&2
fi

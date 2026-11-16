#!/usr/bin/env bash
# Scales the measured pools: substrate | sandbox | none.
set -o errexit -o nounset -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT}/.ate-dev-env.sh"
case "${1:-}" in
  substrate) want=(agents-substrate=3 agents-sandbox=0) ;;
  sandbox) want=(agents-substrate=0 agents-sandbox=3) ;;
  none) want=(agents-substrate=0 agents-sandbox=0) ;;
  *) echo "usage: $0 substrate|sandbox|none" >&2; exit 1 ;;
esac
# GKE runs one cluster operation at a time; retry while another is running.
resize() {
  local pool=$1 n=$2 out
  for _ in $(seq 1 40); do
    if out="$(gcloud container clusters resize "${CLUSTER_NAME}" --node-pool="${pool}" --num-nodes="${n}" \
        --location="${CLUSTER_LOCATION}" --project="${PROJECT_ID}" --quiet 2>&1)"; then
      return 0
    fi
    if [[ "${out}" != *"is still running"* && "${out}" != *"operation"*"in progress"* ]]; then
      echo "${out}" >&2
      return 1
    fi
    sleep 30
  done
  echo "resize of ${pool} kept conflicting with other operations" >&2
  return 1
}
for entry in "${want[@]}"; do
  resize "${entry%%=*}" "${entry#*=}"
done
for entry in "${want[@]}"; do
  pool="${entry%%=*}" n="${entry#*=}"
  if (( n > 0 )); then
    kubectl wait --for=condition=Ready node -l "cloud.google.com/gke-nodepool=${pool}" --timeout=600s
  fi
done

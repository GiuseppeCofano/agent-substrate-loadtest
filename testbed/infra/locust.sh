#!/usr/bin/env bash
# Deploys Locust for one backend (substrate | pod | warmpool) and pins it to
# the control-plane pool, away from the measured pools.
set -o errexit -o nounset -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT}/.ate-dev-env.sh"
backend="${1:?usage: $0 substrate|pod|warmpool}"
cd "${ROOT}/substrate"
./benchmarking/locust/deploy.sh --deploy --user-class agentsession --sandbox-backend "${backend}"
kubectl -n benchmarking patch deployment locust --type=merge -p '{"spec":{"template":{"spec":{
  "nodeSelector":{"cloud.google.com/gke-nodepool":"substrate-node-pool"},
  "tolerations":[{"key":"ate.dev/workloadType","operator":"Equal","value":"ate-control-plane","effect":"NoSchedule"}]}}}}'
kubectl -n benchmarking rollout status deployment/locust --timeout=300s

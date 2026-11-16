#!/usr/bin/env bash
# Installs a B1/B2 baseline (pod | warmpool) and pins the Agent Sandbox
# controller to the control-plane pool: every other node in this cluster is
# tainted, so the controller would otherwise stay Pending.
#
# With infra/rendered/<backend>.yaml present (made by infra/render-baselines.sh
# on a machine with Go and ko), it applies that file instead of building the
# glutton image, so it runs on a host with only kubectl and envsubst.
set -o errexit -o nounset -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT}/.ate-dev-env.sh"
backend="${1:?usage: $0 pod|warmpool}"
BASELINES="${ROOT}/substrate/benchmarking/baselines"
RENDERED="${ROOT}/infra/rendered/${backend}.yaml"
export WARMPOOL_REPLICAS="${WARMPOOL_REPLICAS:-10}"

if [[ "${backend}" == "warmpool" ]]; then
  kubectl apply --server-side -f "https://github.com/kubernetes-sigs/agent-sandbox/releases/download/v1.0.9/sandbox-with-extensions.yaml" >/dev/null
  kubectl -n agent-sandbox-system patch deployment agent-sandbox-controller --type=merge -p '{"spec":{"template":{"spec":{
    "nodeSelector":{"cloud.google.com/gke-nodepool":"substrate-node-pool"},
    "tolerations":[{"key":"ate.dev/workloadType","operator":"Equal","value":"ate-control-plane","effect":"NoSchedule"}]}}}}'
  kubectl -n agent-sandbox-system rollout status deployment/agent-sandbox-controller --timeout=300s
  kubectl wait --for=condition=Established --timeout=120s \
    crd/sandboxwarmpools.extensions.agents.x-k8s.io crd/sandboxtemplates.extensions.agents.x-k8s.io \
    crd/sandboxclaims.extensions.agents.x-k8s.io
fi

if [[ ! -f "${RENDERED}" ]]; then
  cd "${ROOT}/substrate"
  ./benchmarking/baselines/deploy.sh --deploy --backend "${backend}"
  exit 0
fi

"${BASELINES}/deploy.sh" --sweep
kubectl apply -f "${BASELINES}/manifests/namespace-rbac.yaml"
kubectl create namespace benchmarking --dry-run=client -o yaml | kubectl apply -f -
case "${backend}" in
  pod)
    kubectl -n benchmarking create configmap sandbox-pod-template --from-file=pod.yaml="${RENDERED}" \
      --dry-run=client -o yaml | kubectl apply -f -
    if kubectl -n benchmarking get deployment locust >/dev/null 2>&1; then
      kubectl -n benchmarking rollout restart deployment/locust
    fi
    ;;
  warmpool)
    kubectl apply -f "${RENDERED}"
    kubectl -n benchmark-sandboxes patch sandboxwarmpool glutton-pool --type=merge \
      -p "{\"spec\":{\"replicas\":${WARMPOOL_REPLICAS}}}"
    kubectl -n benchmark-sandboxes wait --for=jsonpath='{.status.readyReplicas}'="${WARMPOOL_REPLICAS}" \
      sandboxwarmpool/glutton-pool --timeout=600s
    ;;
  *) echo "usage: $0 pod|warmpool" >&2; exit 1 ;;
esac

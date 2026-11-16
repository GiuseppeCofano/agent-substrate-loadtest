#!/usr/bin/env bash
# Runs the full measurement matrix (plan 2, Task 7) unattended: cluster up,
# checks, 18 ladders, a commit per platform, cluster down. On a failure it
# scales the measured pools to 0 and exits, leaving the cluster for debugging.
set -o errexit -o nounset -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"
# shellcheck disable=SC1091
source "${ROOT}/.ate-dev-env.sh"
OUT="${ROOT}/results/runs"
LOG="${OUT}/matrix.log"
LEVELS=(1 3 6)
REPEATS=(1 2)
mkdir -p "${OUT}"

log() { echo "$(date -u +%FT%TZ) $*" | tee -a "${LOG}"; }

on_error() {
  log "FAILED at line $1; scaling measured pools to 0"
  "${ROOT}/infra/pools.sh" none >>"${LOG}" 2>&1 || true
}
trap 'on_error ${LINENO}' ERR

# Points the ladder at the Locust pod's IP. The runner VM shares the cluster's
# VPC and reaches pod IPs directly, which survives far longer than a
# kubectl port-forward.
locust_url() {
  kubectl -n benchmarking rollout status deployment/locust --timeout=300s >>"${LOG}" 2>&1
  local ip
  ip="$(kubectl -n benchmarking get pod -l app=locust --field-selector=status.phase=Running \
    -o jsonpath='{.items[0].status.podIP}')"
  export LOCUST_URL="http://${ip}:8089"
  for _ in $(seq 1 60); do
    if curl -s -o /dev/null "${LOCUST_URL}/"; then return 0; fi
    sleep 2
  done
  log "locust not reachable at ${LOCUST_URL}"
  return 1
}

wait_workers() {
  for _ in $(seq 1 90); do
    running="$(kubectl -n benchmark-workloads get pods --no-headers 2>/dev/null | grep -c Running || true)"
    if (( running >= ${SUBSTRATE_WORKERS:-45} )); then return 0; fi
    sleep 10
  done
  log "only ${running} Substrate workers Running"
  return 1
}

ladders() {
  local platform=$1
  for ts in "${LEVELS[@]}"; do
    for r in "${REPEATS[@]}"; do
      if [[ -f "${OUT}/${platform}-ts${ts}-r${r}/summary.json" ]]; then
        log "skip ${platform} ts=${ts} r=${r}: done"
        continue
      fi
      rm -rf "${OUT}/${platform}-ts${ts}-r${r}"
      locust_url
      log "start ${platform} ts=${ts} r=${r}"
      if .venv/bin/python -m loadtest.ladder --platform "${platform}" --think-scale "${ts}" --repeat "${r}" \
          --out "${OUT}" >>"${LOG}" 2>&1; then
        log "done ${platform} ts=${ts} r=${r}: capacity $(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['capacity'])" "${OUT}/${platform}-ts${ts}-r${r}/summary.json")"
      else
        log "ladder error ${platform} ts=${ts} r=${r}; continuing"
      fi
    done
  done
  git add "${OUT}"
  git commit -q -m "Measurement runs: ${platform}

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" || true
}

log "== matrix start"
if ! kubectl get nodes >/dev/null 2>&1; then
  "${ROOT}/infra/up.sh" >>"${LOG}" 2>&1
fi

# Substrate.
"${ROOT}/infra/pools.sh" substrate >>"${LOG}" 2>&1
wait_workers
log "workers per node: $(kubectl -n benchmark-workloads get pods -o custom-columns=N:.spec.nodeName --no-headers | sort | uniq -c | awk '{print $1}' | tr '\n' ' ')"
# Written once; a resumed run on another host keeps the original facts.
[[ -f "${OUT}/README.md" ]] || {
  echo "# Measurement runs"
  echo
  echo "- Started: $(date -u +%FT%TZ)"
  echo "- Fork commit: $(git -C substrate rev-parse HEAD) (GiuseppeCofano/substrate, loadtest-baselines)"
  echo "- GKE: $(kubectl version -o json | python3 -c 'import json,sys; print(json.load(sys.stdin)["serverVersion"]["gitVersion"])')"
  echo "- Measured pools: 3 x n2-standard-16 on-demand (agents-substrate, agents-sandbox; one up at a time)"
  echo "- Slots: ${SUBSTRATE_WORKERS:-45} (Substrate workers: 1 CPU + ${SUBSTRATE_WORKER_MEMORY:-1280Mi} each; B1/B2 pods: 1 CPU + 1 GiB each)"
  echo "- Pass rule: p95 > 1.5x calibration and > 250 ms slower fails; failures < 1%; Substrate WakeFirstTouch p95 <= 2 s"
  echo "- Levels (think scale): ${LEVELS[*]}; repeats: ${REPEATS[*]}; spawn rate 2/s"
} > "${OUT}/README.md"
"${ROOT}/infra/locust.sh" substrate >>"${LOG}" 2>&1
ladders substrate

# B1 and B2 on the sandbox pool.
"${ROOT}/infra/pools.sh" sandbox >>"${LOG}" 2>&1
stall="$("${ROOT}/infra/stall-check.sh" 50)"
log "stall check: ${stall}"
echo "- Stall check before B1/B2: ${stall}" >> "${OUT}/README.md"
if [[ "${stall}" != *"stalled=0"* ]]; then
  log "stall check failed; stopping before B1/B2"
  "${ROOT}/infra/pools.sh" none >>"${LOG}" 2>&1
  exit 1
fi
"${ROOT}/infra/baseline.sh" pod >>"${LOG}" 2>&1
"${ROOT}/infra/locust.sh" pod >>"${LOG}" 2>&1
ladders pod
{
  (cd substrate && ./benchmarking/baselines/deploy.sh --delete --backend pod)
  WARMPOOL_REPLICAS=10 "${ROOT}/infra/baseline.sh" warmpool
  "${ROOT}/infra/locust.sh" warmpool
} >>"${LOG}" 2>&1
ladders warmpool

"${ROOT}/infra/down.sh" >>"${LOG}" 2>&1
log "== matrix done"

#!/usr/bin/env bash
# Measures B1 (one GKE Sandbox pod per session) at think scale 3 on the
# agents-sandbox pool, to compare with the Substrate disk series.
# Results in results/b1/. Leaves the measured pools at 0 and Locust on Substrate.
set -o errexit -o nounset -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"
# shellcheck disable=SC1091
source "${ROOT}/.ate-dev-env.sh"
OUT="${ROOT}/results/b1"
LOG="${OUT}/run.log"
mkdir -p "${OUT}"
log() { echo "$(date -u +%FT%TZ) $*" | tee -a "${LOG}"; }
trap 'log "FAILED at line ${LINENO}"; "${ROOT}/infra/pools.sh" none >>"${LOG}" 2>&1 || true' ERR

log "== B1 medium start"
{
  "${ROOT}/infra/pools.sh" sandbox
  "${ROOT}/infra/baseline.sh" pod
  "${ROOT}/infra/locust.sh" pod
} >>"${LOG}" 2>&1
ip="$(kubectl -n benchmarking get pod -l app=locust --field-selector=status.phase=Running -o jsonpath='{.items[0].status.podIP}')"
LOCUST_URL="http://${ip}:8089" .venv/bin/python -m loadtest.ladder --platform pod --think-scale 3 --repeat 1 \
  --steps 10,20,40,80 --out "${OUT}" >>"${OUT}/ladder.log" 2>&1 || log "ladder error"
log "B1 ts3: capacity $(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['capacity'])" "${OUT}/pod-ts3-r1/summary.json" 2>/dev/null || echo '?')"
{
  (cd substrate && ./benchmarking/baselines/deploy.sh --delete --backend pod)
  "${ROOT}/infra/locust.sh" substrate
  "${ROOT}/infra/pools.sh" none
} >>"${LOG}" 2>&1
log "== B1 medium done"

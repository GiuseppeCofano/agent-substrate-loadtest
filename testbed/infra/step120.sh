#!/usr/bin/env bash
# Adds a 120-session step for the disk configurations that stopped at 80:
# fresh calibration, then 120 sessions at think scale 3, per configuration.
# Results go to results/disks/<cfg>/s120/. On a failure, measured pools go to 0.
set -o errexit -o nounset -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"
# shellcheck disable=SC1091
source "${ROOT}/.ate-dev-env.sh"
LOG="${ROOT}/results/disks/step120.log"
log() { echo "$(date -u +%FT%TZ) $*" | tee -a "${LOG}"; }
trap 'log "FAILED at line ${LINENO}"; "${ROOT}/infra/pools.sh" none >>"${LOG}" 2>&1 || true' ERR

log "== step 120 start"
for cfg in pdssd1t lssd2 lssd4 hdb600 hdb1200; do
  out="${ROOT}/results/disks/${cfg}/s120"
  if [[ -f "${out}/substrate-ts3-r1/summary.json" ]]; then
    log "skip ${cfg}: done"
    continue
  fi
  rm -rf "${out}"
  mkdir -p "${out}"
  log "config ${cfg}"
  "${ROOT}/infra/disk-config.sh" "${cfg}" >>"${out}/setup.log" 2>&1
  ip="$(kubectl -n benchmarking get pod -l app=locust --field-selector=status.phase=Running -o jsonpath='{.items[0].status.podIP}')"
  LOCUST_URL="http://${ip}:8089" .venv/bin/python -m loadtest.ladder --platform substrate --think-scale 3 --repeat 1 \
    --steps 120 --out "${out}" >>"${out}/ladder.log" 2>&1 || log "ladder error ${cfg}"
  log "${cfg} 120: $(grep -E '^substrate ts=3 users=120' "${out}/ladder.log" | cut -c1-200)"
done
"${ROOT}/infra/pools.sh" none >>"${LOG}" 2>&1
log "== step 120 done"

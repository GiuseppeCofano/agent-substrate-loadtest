#!/usr/bin/env bash
# Runs the disk experiment unattended: for each configuration, set up the
# agents-substrate pool, measure the disk with fio, then run one Substrate
# ladder at think scale 3. On a failure it scales the measured pools to 0.
set -o errexit -o nounset -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"
# shellcheck disable=SC1091
source "${ROOT}/.ate-dev-env.sh"
OUT="${ROOT}/results/disks"
LOG="${OUT}/matrix.log"
mkdir -p "${OUT}"
log() { echo "$(date -u +%FT%TZ) $*" | tee -a "${LOG}"; }
trap 'log "FAILED at line ${LINENO}"; "${ROOT}/infra/pools.sh" none >>"${LOG}" 2>&1 || true' ERR

# Configurations with a Substrate run, then the ones measured with fio only:
# pdb100 and lssd1 already have their Substrate runs (results/runs, results/ssd).
# Override with LADDER_CONFIGS / FIO_CONFIGS (space separated).
read -r -a LADDER <<<"${LADDER_CONFIGS:-lssd2 lssd4 pdssd1t pdssd100 pdb1t}"
read -r -a FIO_ONLY <<<"${FIO_CONFIGS-pdb100 lssd1}"

log "== disk matrix start"
for cfg in "${LADDER[@]}" ${FIO_ONLY[@]+"${FIO_ONLY[@]}"}; do
  dir="${OUT}/${cfg}"
  mkdir -p "${dir}"
  needs_ladder=0
  for c in "${LADDER[@]}"; do [[ "${c}" == "${cfg}" ]] && needs_ladder=1; done
  if [[ -f "${dir}/fio.log" ]] && { (( needs_ladder == 0 )) || [[ -f "${dir}/substrate-ts3-r1/summary.json" ]]; }; then
    log "skip ${cfg}: done"
    continue
  fi
  log "config ${cfg}"
  "${ROOT}/infra/disk-config.sh" "${cfg}" >>"${dir}/setup.log" 2>&1
  if [[ ! -f "${dir}/fio.log" ]]; then
    "${ROOT}/infra/fio.sh" "${dir}" >>"${LOG}" 2>&1
    log "fio ${cfg}: $(.venv/bin/python -m loadtest.fio_summary "${dir}/fio.log" | grep seqwrite1)"
  fi
  if (( needs_ladder == 1 )) && [[ ! -f "${dir}/substrate-ts3-r1/summary.json" ]]; then
    rm -rf "${dir}/substrate-ts3-r1"
    ip="$(kubectl -n benchmarking get pod -l app=locust --field-selector=status.phase=Running -o jsonpath='{.items[0].status.podIP}')"
    LOCUST_URL="http://${ip}:8089" .venv/bin/python -m loadtest.ladder --platform substrate --think-scale 3 --repeat 1 \
      --steps 10,20,40,80,160 --out "${dir}" >>"${dir}/ladder.log" 2>&1 || log "ladder error ${cfg}"
    log "ladder ${cfg}: capacity $(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['capacity'])" "${dir}/substrate-ts3-r1/summary.json" 2>/dev/null || echo '?')"
  fi
done
"${ROOT}/infra/pools.sh" none >>"${LOG}" 2>&1
log "== disk matrix done"

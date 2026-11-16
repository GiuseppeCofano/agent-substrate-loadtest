#!/usr/bin/env bash
# Starts one ladder detached, pointed at the Locust pod's IP.
# Usage: infra/start-ladder.sh <out-dir> <ladder args...>
set -o errexit -o nounset -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"
out="$1"; shift
mkdir -p "${out}"
ip="$(kubectl -n benchmarking get pod -l app=locust --field-selector=status.phase=Running -o jsonpath='{.items[0].status.podIP}')"
LOCUST_URL="http://${ip}:8089" setsid nohup .venv/bin/python -m loadtest.ladder --out "${out}" "$@" \
  >> "${out}/ladder.log" 2>&1 < /dev/null &
echo "started $! (locust ${ip})"

#!/usr/bin/env bash
# Stops the matrix runner, its ladder and Locust's swarm. Matches processes by
# their exact command, so it never matches the shell that runs this script.
set -o nounset -o pipefail

for pattern in '^bash infra/run-matrix.sh' '^\.venv/bin/python -m loadtest.ladder' '^/[^ ]*python[^ ]* -m loadtest.ladder'; do
  for pid in $(pgrep -f "${pattern}"); do
    kill "${pid}" 2>/dev/null && echo "stopped ${pid}"
  done
done
ip="$(kubectl -n benchmarking get pod -l app=locust --field-selector=status.phase=Running \
  -o jsonpath='{.items[0].status.podIP}' 2>/dev/null || true)"
if [[ -n "${ip}" ]]; then
  curl -s -m 10 "http://${ip}:8089/stop" >/dev/null || true
  echo "locust: $(curl -s -m 10 "http://${ip}:8089/stats/requests" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["state"], d["user_count"])')"
fi

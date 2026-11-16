#!/usr/bin/env bash
# Collects live diagnostics from the agents-substrate pool for DURATION
# seconds: atelet logs from every node, and node and worker usage every minute.
# Usage: infra/collect-diag.sh <out-dir> <duration-seconds>
set -o errexit -o nounset -o pipefail

out="${1:?usage: $0 <out-dir> <duration-seconds>}"
duration="${2:?usage: $0 <out-dir> <duration-seconds>}"
mkdir -p "${out}"
pids=()
for pod in $(kubectl -n ate-system get pods -l app=atelet -o wide --no-headers | awk '/agents-substrate/{print $1}'); do
  kubectl -n ate-system logs -f "${pod}" -c atelet --since=1s > "${out}/atelet-${pod}.log" 2>&1 &
  pids+=("$!")
done
end=$(( $(date +%s) + duration ))
while (( $(date +%s) < end )); do
  {
    echo "== $(date -u +%FT%TZ)"
    kubectl top nodes -l cloud.google.com/gke-nodepool=agents-substrate --no-headers
  } >> "${out}/top-nodes.txt" 2>&1
  {
    echo "== $(date -u +%FT%TZ)"
    kubectl -n benchmark-workloads top pods --no-headers | sort -k2 -h -r | head -15
  } >> "${out}/top-workers.txt" 2>&1
  sleep 60
done
kill "${pids[@]}" 2>/dev/null || true
echo "collected into ${out}"

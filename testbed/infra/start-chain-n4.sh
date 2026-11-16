#!/usr/bin/env bash
# Starts the N4 chain (waits for the N2 series) detached from the calling shell, so an SSH session
# that launches it returns at once.
set -o errexit -o nounset -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"
setsid nohup infra/chain-n4.sh >> results/disks/nohup-n4.out 2>&1 < /dev/null &
echo "started $!"

#!/usr/bin/env bash
# Starts the 120-session step runner detached from the calling shell, so an SSH session
# that launches it returns at once.
set -o errexit -o nounset -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"
setsid nohup infra/step120.sh >> results/disks/nohup-120.out 2>&1 < /dev/null &
echo "started $!"

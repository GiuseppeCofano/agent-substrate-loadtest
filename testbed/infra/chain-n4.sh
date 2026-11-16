#!/usr/bin/env bash
# Waits for the running N2 disk series to finish, then runs the N4 Hyperdisk
# series with the same runner. Start it detached on the runner VM.
set -o errexit -o nounset -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"
while pgrep -f '^bash infra/disk-matrix.sh' >/dev/null; do sleep 60; done
if ! tail -1 results/disks/matrix.log | grep -q "disk matrix done"; then
  echo "$(date -u +%FT%TZ) N2 series did not finish cleanly; not starting N4" >> results/disks/matrix.log
  exit 1
fi
echo "$(date -u +%FT%TZ) == starting N4 Hyperdisk series" >> results/disks/matrix.log
LADDER_CONFIGS="hdb140 hdb300 hdb600 hdb1200" FIO_CONFIGS="" exec infra/disk-matrix.sh

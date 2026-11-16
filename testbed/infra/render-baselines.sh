#!/usr/bin/env bash
# Renders the B1 Pod and the B2 warm pool manifests with the glutton image
# built and resolved by ko, into infra/rendered/. Needs Go, ko access and
# envsubst; infra/baseline.sh then applies the files with kubectl alone.
set -o errexit -o nounset -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT}/.ate-dev-env.sh"
export ACTOR_CPU_MILLICORES="${ACTOR_CPU_MILLICORES:-1000}"
export ACTOR_MEMORY_BYTES="${ACTOR_MEMORY_BYTES:-1073741824}"
export SANDBOX_RUNTIME_CLASS="${SANDBOX_RUNTIME_CLASS-gvisor}"
export WARMPOOL_REPLICAS="${WARMPOOL_REPLICAS:-10}"
mkdir -p "${ROOT}/infra/rendered"
lib="$(mktemp)"
trap 'rm -f "${lib}"' EXIT
# Reuse deploy.sh's render functions without running its argument parsing.
sed '/^action=""/,$d' "${ROOT}/substrate/benchmarking/baselines/deploy.sh" > "${lib}"
# shellcheck disable=SC1090
source "${lib}"
export MANIFESTS="${ROOT}/substrate/benchmarking/baselines/manifests"
export REPO_ROOT="${ROOT}/substrate"
render_pod | ko_resolve > "${ROOT}/infra/rendered/pod.yaml"
render_warmpool | ko_resolve > "${ROOT}/infra/rendered/warmpool.yaml"
grep -h "image:" "${ROOT}/infra/rendered/"*.yaml

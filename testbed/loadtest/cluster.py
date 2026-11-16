"""Cluster hygiene checks between and during runs, through kubectl."""

import subprocess
import time
from collections.abc import Callable
from pathlib import Path

Run = Callable[[list[str]], str]

ROOT = Path(__file__).resolve().parents[1]
# Built from the fork by infra/up.sh into the repo's git-ignored bin/.
KUBECTL_ATE = str(ROOT / "bin" / "kubectl-ate")
SESSION_LABEL = "agentsession.ate.dev/session"
EXPECTED_POOL = {"substrate": "agents-substrate", "pod": "agents-sandbox", "warmpool": "agents-sandbox"}


def kubectl(cmd: list[str]) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def _get_optional(run: Run, cmd: list[str]) -> str:
    """Runs a kubectl get whose resource type may not be installed yet."""
    try:
        return run(cmd)
    except subprocess.CalledProcessError as e:
        if "doesn't have a resource type" in (e.stderr or ""):
            return ""
        raise


def _count(out: str) -> int:
    return len([line for line in out.splitlines() if line.strip()])


def leftovers(run: Run = kubectl) -> dict[str, int]:
    actors = run([KUBECTL_ATE, "get", "actors", "-A"])
    actors_n = sum(1 for line in actors.splitlines()[1:] if " agent-" in f" {line}")
    pods = run(["kubectl", "-n", "benchmark-sandboxes", "get", "pods", "-l", SESSION_LABEL,
                "--no-headers", "--ignore-not-found"])
    # The Agent Sandbox CRDs exist only once the warm pool baseline is installed.
    claims = _get_optional(run, ["kubectl", "-n", "benchmark-sandboxes", "get", "sandboxclaims", "-l", SESSION_LABEL,
                                 "--no-headers", "--ignore-not-found"])
    return {"actors": actors_n, "pods": _count(pods), "claims": _count(claims)}


def assert_clean(run: Run = kubectl) -> None:
    left = {k: v for k, v in leftovers(run).items() if v}
    if left:
        raise RuntimeError("leftovers before run: " + ", ".join(f"{k}={v}" for k, v in left.items()))


def _agent_actors(run: Run) -> list[tuple[str, str]]:
    out = run([KUBECTL_ATE, "get", "actors", "-A"])
    actors = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) > 1 and parts[1].startswith("agent-"):
            actors.append((parts[0], parts[1]))
    return actors


def sweep(run: Run = kubectl, attempts: int = 5, wait_s: float = 10) -> None:
    """Deletes leftover actors and sandboxes. The Locust worker may be deleting
    the same actors as it stops, so a delete that fails is retried on the next
    listing, and only actors still listed after the last attempt are an error."""
    for attempt in range(attempts):
        actors = _agent_actors(run)
        if not actors:
            break
        for atespace, name in actors:
            try:
                run([KUBECTL_ATE, "delete", "actor", name, "-a", atespace])
            except subprocess.CalledProcessError:
                pass
        if attempt < attempts - 1:
            time.sleep(wait_s)
    else:
        left = _agent_actors(run)
        if left:
            raise RuntimeError("actors left after sweep: " + ", ".join(n for _, n in left))
    run([str(ROOT / "substrate" / "benchmarking" / "baselines" / "deploy.sh"), "--sweep"])


def check_placement(run: Run, platform: str) -> None:
    """Raises unless every worker (Substrate) or session pod (B1/B2) is on the measured pool."""
    want = EXPECTED_POOL[platform]
    if platform == "substrate":
        ns, selector = "benchmark-workloads", "ate.dev/worker-pool=benchmark-worker"
    else:
        # B2 pods come from the warm pool, so they carry the template's
        # labels rather than the session label, which sits on the claim.
        ns, selector = "benchmark-sandboxes", "app=agentsession-sandbox"
    out = run(["kubectl", "-n", ns, "get", "pods", "-l", selector, "-o",
               "custom-columns=NAME:.metadata.name,NODE:.spec.nodeName", "--no-headers"])
    nodes = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2:
            nodes[parts[0]] = parts[1]
    if not nodes:
        raise RuntimeError(f"no pods match {selector} in {ns}")
    # GKE node names contain the pool name: gke-<cluster>-<pool>-<hash>-<id>.
    wrong = [name for name, node in nodes.items() if want not in node]
    if wrong:
        raise RuntimeError(f"pods not on {want}: {', '.join(wrong)}")

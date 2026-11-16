import pytest

from loadtest import cluster


def fake_run(outputs):
    def run(cmd):
        key = " ".join(cmd)
        for pattern, out in outputs.items():
            if pattern in key:
                return out
        return ""
    return run


ACTORS = "ATESPACE NAME TEMPLATE STATE\nbenchmark agent-1 glutton SUSPENDED\n"


def test_assert_clean_raises_on_leftovers():
    run = fake_run({"get actors": ACTORS, "get pods": "", "get sandboxclaims": ""})
    with pytest.raises(RuntimeError, match="actors=1"):
        cluster.assert_clean(run)


def test_assert_clean_passes_when_empty():
    run = fake_run({"get actors": "ATESPACE NAME\n", "get pods": "", "get sandboxclaims": ""})
    cluster.assert_clean(run)


def test_check_placement():
    ok = fake_run({"benchmark-workloads": "worker-a agents-substrate\nworker-b agents-substrate\n"})
    cluster.check_placement(ok, "substrate")
    bad = fake_run({"benchmark-workloads": "worker-a agents-substrate\nworker-b control-plane\n"})
    with pytest.raises(RuntimeError, match="worker-b"):
        cluster.check_placement(bad, "substrate")


def test_check_placement_selects_workers_by_pool_label():
    seen = []

    def run(cmd):
        seen.append(" ".join(cmd))
        return "worker-a gke-x-agents-substrate-1\n"

    cluster.check_placement(run, "substrate")
    assert "ate.dev/worker-pool=benchmark-worker" in seen[0]


def test_leftovers_treats_missing_resource_type_as_none():
    import subprocess

    def run(cmd):
        if "sandboxclaims" in cmd:
            raise subprocess.CalledProcessError(
                1, cmd, stderr='error: the server doesn\'t have a resource type "sandboxclaims"')
        return "ATESPACE NAME\n" if "actors" in cmd else ""

    assert cluster.leftovers(run) == {"actors": 0, "pods": 0, "claims": 0}


def test_check_placement_selects_sandbox_pods_by_template_label():
    # B2 pods come from the warm pool and carry the template's labels, not
    # the session label, which sits on the claim.
    for platform in ("pod", "warmpool"):
        seen = []

        def run(cmd):
            seen.append(" ".join(cmd))
            return "glutton-pool-abc gke-x-agents-sandbox-1\n"

        cluster.check_placement(run, platform)
        assert "app=agentsession-sandbox" in seen[0]


def test_sweep_tolerates_actors_deleted_concurrently():
    import subprocess

    calls = []
    listings = iter([ACTORS, "ATESPACE NAME\n"])

    def run(cmd):
        calls.append(cmd)
        if "get" in cmd and "actors" in cmd:
            return next(listings)
        if "delete" in cmd:
            raise subprocess.CalledProcessError(1, cmd, stderr="Error: rpc error: code = NotFound desc = actor not found")
        return ""

    cluster.sweep(run, wait_s=0)  # the worker deleted it first; that counts as clean


def test_sweep_raises_when_actors_remain():
    import subprocess

    def run(cmd):
        if "get" in cmd and "actors" in cmd:
            return ACTORS
        if "delete" in cmd:
            raise subprocess.CalledProcessError(1, cmd, stderr="Error: rpc error: code = Aborted desc = another operation is in progress")
        return ""

    with pytest.raises(RuntimeError, match="agent-1"):
        cluster.sweep(run, wait_s=0)

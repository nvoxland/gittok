"""The GitHub workflows: the macOS tests run once per commit, in CI.

GitHub has few hosted macOS arm64 runners, and a job that gets none in about 15 minutes is
cancelled. So a release must not ask for a second macOS runner: it checks that CI passed
on the tagged commit.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]


def _workflow(name: str) -> dict:
    return yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text())


def test_ci_cancels_a_run_that_a_newer_push_replaces():
    concurrency = _workflow("ci.yml")["concurrency"]
    assert "github.ref" in concurrency["group"]
    assert concurrency["cancel-in-progress"] is True


def test_the_release_uses_the_ci_result_instead_of_a_macos_runner():
    jobs = _workflow("release.yml")["jobs"]
    assert not [n for n, j in jobs.items() if "macos" in str(j.get("runs-on"))]
    check = jobs["ci-passed"]
    assert check["permissions"]["actions"] == "read"
    script = "\n".join(step.get("run", "") for step in check["steps"])
    assert "actions/workflows/ci.yml/runs" in script and "head_sha" in script
    assert "ci-passed" in jobs["publish-pypi"]["needs"]

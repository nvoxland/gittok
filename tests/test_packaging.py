"""Build a wheel and check that it carries the shared files an installed app needs."""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]

pytestmark = pytest.mark.skipif(
    not (ROOT / "web" / "build" / "index.html").is_file() or shutil.which("uv") is None,
    reason="needs web/build and uv",
)


@pytest.fixture(scope="module")
def wheel(tmp_path_factory):
    out = tmp_path_factory.mktemp("wheel")
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out), str(ROOT)],
        check=True, capture_output=True, text=True,
    )  # fmt: skip
    (whl,) = out.glob("gittok-*.whl")
    return whl


@pytest.fixture(scope="module")
def wheel_names(wheel):
    return set(zipfile.ZipFile(wheel).namelist())


@pytest.fixture(scope="module")
def requires(wheel):
    z = zipfile.ZipFile(wheel)
    (meta,) = [n for n in z.namelist() if n.endswith(".dist-info/METADATA")]
    lines = z.read(meta).decode().splitlines()
    return [ln.split(":", 1)[1].strip() for ln in lines if ln.startswith("Requires-Dist:")]


def test_wheel_has_shared_files(wheel_names):
    b = "gittok/_bundled/"
    for want in (
        "config/settings.yaml",
        "config/languages.yaml",
        "config/queries/",
        "web/index.html",
        "claude/skills/gittok-generate/SKILL.md",
        "claude/skills/gittok-steer/SKILL.md",
        "claude/skills/gittok-profile-repo/SKILL.md",
        "claude/agents/gittok-writer.md",
        "claude/agents/gittok-scout.md",
    ):
        assert any(n.startswith(b + want) for n in wheel_names), want
    assert "gittok/prompts/generate.md" in wheel_names


def test_wheel_has_no_local_or_data(wheel_names):
    assert not any("/local/" in n or n.startswith("data/") for n in wheel_names)


def test_structure_and_ast_grep_are_core_dependencies(requires):
    # A plain install gets the tree-sitter layer and ast-grep rules, no extra needed.
    for pkg in ("tree-sitter-language-pack", "ast-grep-py"):
        hits = [r for r in requires if r.startswith(pkg)]
        assert hits and not any("extra ==" in r for r in hits), (pkg, requires)

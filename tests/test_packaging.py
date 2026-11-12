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
def wheel_names(tmp_path_factory):
    out = tmp_path_factory.mktemp("wheel")
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out), str(ROOT)],
        check=True, capture_output=True, text=True,
    )  # fmt: skip
    (whl,) = out.glob("blamescroll-*.whl")
    return set(zipfile.ZipFile(whl).namelist())


def test_wheel_has_shared_files(wheel_names):
    b = "blamescroll/_bundled/"
    for want in (
        "config/settings.yaml",
        "config/languages.yaml",
        "config/queries/",
        "web/index.html",
        "claude/skills/blamescroll-generate/SKILL.md",
        "claude/skills/blamescroll-steer/SKILL.md",
        "claude/skills/blamescroll-profile-repo/SKILL.md",
        "claude/agents/blamescroll-writer.md",
        "claude/agents/blamescroll-scout.md",
    ):
        assert any(n.startswith(b + want) for n in wheel_names), want
    assert "blamescroll/prompts/generate.md" in wheel_names


def test_wheel_has_no_local_or_data(wheel_names):
    assert not any("/local/" in n or n.startswith("data/") for n in wheel_names)

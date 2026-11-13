"""Build a wheel and check that it carries the shared files an installed app needs."""

from __future__ import annotations

import shutil
import subprocess
import sys
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
    assert "gittok/prompts/config_examples.yaml" in wheel_names
    assert b + "config/mascots.yaml" not in wheel_names  # no mascot is shipped


def test_wheel_has_everything_that_init_writes(wheel_names):
    for name in ("mcp.json", "settings.json", "AGENTS.md", "CLAUDE.md", "gitignore", "repos.yaml",
                 "codex.toml", "codex.md", "codex-skill.md"):
        assert f"gittok/templates/{name}" in wheel_names, name
    assert "gittok/home.py" in wheel_names and "gittok/install.py" not in wheel_names
    for name in ("render_batch.py", "mflux_worker.py", "render_process.py"):
        assert f"gittok/{name}" in wheel_names
    # The clone's own session settings (`uv run ...` commands) are not shipped.
    assert not any(n.endswith("claude/settings.json") for n in wheel_names)


def test_wheel_has_no_local_or_data(wheel_names):
    assert not any("/local/" in n or n.startswith("data/") for n in wheel_names)


def test_wheel_initializes_both_harnesses_without_the_checkout(wheel, tmp_path):
    import os

    installed = tmp_path / "installed"
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(installed)
    subprocess.run(
        [sys.executable, "-c", "from pathlib import Path; from gittok.home import init; "
         "init(Path('home'), 'test'); "
         "from gittok.config import load_config; from gittok import memes, render; "
         "cfg = load_config(Path('home').resolve()); "
         "assert memes.missing(cfg) == []; "
         "r = render.default_renderers(cfg)['meme']; assert r.available(); "
         "image, = r.render({'template': 'drake', 'lines': ['before', 'after']}, cfg, {}); "
         "assert image.data.startswith(bytes([137, 80, 78, 71])); "
         "assert not memes.store(cfg).exists()"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(installed), "GITTOK_ROOT": ""},
        check=True, capture_output=True, text=True,
    )
    home = tmp_path / "home"
    assert (home / ".codex/config.toml").is_file()
    assert (home / ".codex/hooks.json").is_file()
    assert (home / ".agents/GITTOK.md").is_file()
    for name in ("gittok-generate", "gittok-steer", "gittok-profile-repo"):
        assert (home / f".agents/skills/{name}/SKILL.md").is_file()
        assert (home / f".claude/skills/{name}/SKILL.md").is_file()


def test_structure_and_ast_grep_are_core_dependencies(requires):
    # A plain install gets the tree-sitter layer and ast-grep rules, no extra needed.
    for pkg in ("tree-sitter-language-pack", "ast-grep-py"):
        hits = [r for r in requires if r.startswith(pkg)]
        assert hits and not any("extra ==" in r for r in hits), (pkg, requires)


def test_wheel_includes_meme_fonts_and_upstream_notices(wheel_names):
    from gittok import memes

    root = "gittok/assets/memes/"
    for name in ("SOURCES.json", "LICENSE.txt", "README.md", "fonts/titilliumweb-OFL.txt",
                 "fonts/kalam-OFL.txt", "fonts/notosans-OFL.txt",
                 *(f"fonts/{font}" for font in memes.FONT_FILES.values())):
        assert root + name in wheel_names

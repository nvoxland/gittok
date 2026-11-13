"""GitTok lives in one directory that `gittok init` makes. No text names the old model."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
OLD = (
    "~/.gittok",
    ".gittok/",
    "GITTOK_HOME",
    "LaunchAgent",
    "launchctl",
    "launchd",
    "gittok install",
    "install --apply",
    "scope user",
    "~/.claude",
    "mcp_loopback_only",
    "7313/mcp",
    "streamable",
)
# These tests name the old words to assert that they are gone.
SELF = {
    "tests/test_one_directory_model.py",
    "tests/test_home.py",
    "tests/test_pairing.py",
    "tests/test_roots.py",
}
TEXT = {".md", ".py", ".yaml", ".yml", ".json", ".toml", ".svelte", ".ts", ".js", ".mjs", ".html"}


def tracked_text_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.split("\n")  # fmt: skip
    files = [ROOT / rel for rel in out if rel and rel not in SELF and "lock" not in rel]
    # The clone's own session settings are not part of this check.
    return [p for p in files if p.suffix in TEXT and p.is_file() and p.name != "settings.json"]


@pytest.mark.skipif(not (ROOT / ".git").exists(), reason="needs the git checkout")
def test_no_text_names_the_old_install_model():
    hits = []
    for path in tracked_text_files():
        text = path.read_text(errors="replace")
        hits += [f"{path.relative_to(ROOT)}: {word}" for word in OLD if word in text]
    assert not hits, "\n".join(hits)


SITE = "https://nvoxland.github.io/gittok/"


def test_the_site_gives_the_steps_and_says_when_gittok_runs():
    """The user docs are the docs site (mkdocs.yml, docs/). Install and upgrade live there."""
    install = (ROOT / "docs" / "getting-started" / "install.md").read_text()
    upgrade = (ROOT / "docs" / "guide" / "upgrade.md").read_text()
    for fact in ("uv tool install 'gittok[images]'", "gittok init .\n", "cd ~/gittok"):
        assert fact in install, fact
    assert install.index("uv tool install 'gittok[images]'") < install.index("gittok init .\n")
    assert "runs only while a session is open" in install
    assert "Nothing is installed outside" in install
    for fact in ("uv tool upgrade gittok", "gittok update", "uv tool uninstall gittok"):
        assert fact in upgrade, fact


def test_the_readme_points_to_the_site_and_its_links_work_on_pypi():
    """PyPI shows the README without the repo around it: every link and image is absolute."""
    import re

    text = (ROOT / "README.md").read_text()
    assert SITE in text
    assert "uv tool install 'gittok[images]'" in text and "gittok init ." in text
    relative = re.findall(r"\]\((?!https?://)[^)]*\)", text)
    relative += re.findall(r'src="(?!https?://)[^"]*"', text)
    assert relative == [], relative
    assert "site_url: " + SITE in (ROOT / "mkdocs.yml").read_text()


def test_skills_say_where_the_mcp_server_comes_from():
    for name in ("gittok-generate", "gittok-steer", "gittok-profile-repo"):
        text = (ROOT / ".claude" / "skills" / name / "SKILL.md").read_text()
        assert "gittok init <dir>" in text and "GitTok directory" in text, name

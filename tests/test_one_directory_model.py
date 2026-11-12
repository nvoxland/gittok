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
    "8008/mcp",
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


def test_the_readme_gives_the_three_steps_and_says_when_gittok_runs():
    text = (ROOT / "README.md").read_text()
    for fact in (
        "uv tool install 'gittok[images]'",
        "uv tool install gittok\n",
        "gittok init ~/gittok",
        "cd ~/gittok",
        "uv tool upgrade gittok",
        "gittok update",
        "uv tool uninstall gittok",
        "<!-- screenshot -->",
        "only while a Claude Code session is open",
        "Nothing is installed outside",
    ):
        assert fact in text, fact
    # The main command has the illustrated cards; the smaller install is a note after the flow.
    main, init = text.index("uv tool install 'gittok[images]'"), text.index("gittok init ~/gittok")
    assert main < init < text.index("uv tool install gittok\n")
    assert "Optional: illustrated cards" not in text


def test_skills_say_where_the_mcp_server_comes_from():
    for name in ("gittok-generate", "gittok-steer", "gittok-profile-repo"):
        text = (ROOT / ".claude" / "skills" / name / "SKILL.md").read_text()
        assert "gittok init <dir>" in text and "GitTok directory" in text, name

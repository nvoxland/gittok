"""`gittok init <dir>` and `gittok update`: a GitTok directory holds everything.

Nothing here writes outside `tmp_path`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from gittok import cli, config, home

REAL = Path(__file__).parents[1]
OWNED = [
    "AGENTS.md",
    ".mcp.json",
    "CLAUDE.md",
    ".claude/settings.json",
    ".claude/skills/gittok-generate/SKILL.md",
    ".claude/skills/gittok-steer/SKILL.md",
    ".claude/skills/gittok-profile-repo/SKILL.md",
    ".claude/agents/gittok-writer.md",
    ".claude/agents/gittok-scout.md",
]


@pytest.fixture(autouse=True)
def _no_env_root(monkeypatch):
    monkeypatch.delenv("GITTOK_ROOT", raising=False)


def tree(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


# ---- init ----


def test_init_makes_a_missing_dir_with_parents_and_writes_every_file(tmp_path):
    target = tmp_path / "a" / "b" / "gittok"
    home.init(target, "1.2.3")
    for rel in [*OWNED, config.MARKER, ".gitignore", "local/repos.yaml"]:
        assert (target / rel).is_file(), rel
    assert not (target / "data").exists()  # made on first use


def test_init_writes_a_stdio_mcp_entry_for_the_installed_command(tmp_path):
    home.init(tmp_path / "g", "1.2.3")
    entry = json.loads((tmp_path / "g" / ".mcp.json").read_text())["mcpServers"]["gittok"]
    assert entry == {"type": "stdio", "command": "gittok", "args": ["mcp", "--ui"]}


def test_init_settings_have_the_two_hooks_and_the_feed_watch_permission(tmp_path):
    home.init(tmp_path / "g", "1.2.3")
    s = json.loads((tmp_path / "g" / ".claude" / "settings.json").read_text())
    (group,) = s["hooks"]["SessionStart"]
    assert [h["command"] for h in group["hooks"]] == [
        "gittok health --hint 2>/dev/null || true",
        "gittok feed-watch --hint 2>/dev/null || true",
    ]
    assert s["permissions"]["allow"] == ["Bash(gittok feed-watch)"]


def test_init_copies_the_shipped_skills_and_agents_unchanged(tmp_path):
    home.init(tmp_path / "g", "1.2.3")
    for rel in OWNED[4:]:
        assert (tmp_path / "g" / rel).read_bytes() == (REAL / rel).read_bytes(), rel


def test_init_marker_records_the_version(tmp_path):
    home.init(tmp_path / "g", "1.2.3")
    marker = yaml.safe_load((tmp_path / "g" / config.MARKER).read_text())
    assert marker["version"] == "1.2.3"
    assert set(marker["files"]) == set(OWNED)
    assert home.recorded_version(tmp_path / "g") == "1.2.3"


def test_init_gitignore_keeps_data_and_clones_out_of_git(tmp_path):
    home.init(tmp_path / "g", "1.2.3")
    lines = (tmp_path / "g" / ".gitignore").read_text().split()
    assert "data/" in lines and "repos/" in lines


def test_the_starter_repos_file_loads_as_no_repos(tmp_path):
    home.init(tmp_path / "g", "1.2.3")
    text = (tmp_path / "g" / "local" / "repos.yaml").read_text()
    assert all(ln.startswith("#") or not ln.strip() for ln in text.splitlines())
    cfg = config.load_config(tmp_path / "g", config.shipped_root())
    assert cfg.repos == {} and cfg.settings.data_dir == (tmp_path / "g" / "data").resolve()


def test_init_agents_md_is_short_and_says_what_the_directory_is(tmp_path):
    home.init(tmp_path / "g", "1.2.3")
    text = (tmp_path / "g" / "AGENTS.md").read_text()
    assert len(text.splitlines()) <= 60
    for fact in ("GitTok directory", "add_repo", "pairing_link", "plain HTTP", "local/",
                 "data/", "repos/", "gittok update", "get_brief", "get_packet",
                 "submit_cards", "finish_run", "scout_status"):  # fmt: skip
        assert fact in text, fact


def test_agents_md_keeps_claude_code_things_in_one_section(tmp_path):
    home.init(tmp_path / "g", "1.2.3")
    text = (tmp_path / "g" / "AGENTS.md").read_text()
    neutral, claude = text.split("## Claude Code\n")
    assert "## " not in claude  # it is the last section
    for word in ("Claude", "/gittok-", "/mcp", "subagent", "SessionStart", "skill"):
        assert word not in neutral, word
    for word in ("/gittok-generate", "/gittok-profile-repo", "/mcp", "Reconnect"):
        assert word in claude, word


def test_claude_md_only_points_to_agents_md(tmp_path):
    home.init(tmp_path / "g", "1.2.3")
    assert (tmp_path / "g" / "CLAUDE.md").read_text() == "@AGENTS.md\n"


def test_harness_neutral_files_and_claude_code_files_are_separate_units():
    assert set(home.core_files()) == {"AGENTS.md"}
    claude = set(home.claude_code_files())
    assert {".mcp.json", "CLAUDE.md", ".claude/settings.json"} <= claude
    assert all(rel in (".mcp.json", "CLAUDE.md") or rel.startswith(".claude/") for rel in claude)
    assert set(home.owned_files()) == set(home.core_files()) | claude
    assert list(home.HARNESSES) == ["Claude Code"]


def test_init_accepts_an_empty_dir_and_ignores_ds_store(tmp_path):
    target = tmp_path / "g"
    target.mkdir()
    (target / ".DS_Store").write_bytes(b"x")
    home.init(target, "1.2.3")
    assert (target / config.MARKER).is_file()


def test_init_refuses_a_dir_that_is_not_empty_and_changes_nothing(tmp_path):
    target = tmp_path / "g"
    target.mkdir()
    (target / "notes.txt").write_text("mine")
    with pytest.raises(home.InitError, match="not empty"):
        home.init(target, "1.2.3")
    assert tree(target) == {"notes.txt"}


def test_init_twice_refuses_the_second_time(tmp_path):
    home.init(tmp_path / "g", "1.2.3")
    before = tree(tmp_path / "g")
    with pytest.raises(home.InitError, match="gittok update"):
        home.init(tmp_path / "g", "1.2.3")
    assert tree(tmp_path / "g") == before


def test_init_refuses_a_file(tmp_path):
    f = tmp_path / "f"
    f.write_text("x")
    with pytest.raises(home.InitError, match="is a file"):
        home.init(f, "1.2.3")
    assert f.read_text() == "x"


def test_init_refuses_a_path_under_a_file(tmp_path):
    (tmp_path / "f").write_text("x")
    with pytest.raises(home.InitError):
        home.init(tmp_path / "f" / "g", "1.2.3")


def test_init_refuses_a_dir_inside_a_gittok_directory(tmp_path):
    home.init(tmp_path / "g", "1.2.3")
    with pytest.raises(home.InitError, match="inside the GitTok directory"):
        home.init(tmp_path / "g" / "local" / "inner", "1.2.3")
    assert not (tmp_path / "g" / "local" / "inner").exists()


def test_init_refuses_a_dir_inside_a_source_clone(tmp_path):
    clone = tmp_path / "clone"
    (clone / "config").mkdir(parents=True)
    (clone / "config" / "settings.yaml").write_text("{}\n")
    with pytest.raises(home.InitError, match="source clone"):
        home.init(clone / "x", "1.2.3")
    assert not (clone / "x").exists()


def test_init_lines_say_what_was_made_and_the_next_step(tmp_path):
    target = tmp_path / "g"
    text = "\n".join(home.init(target, "1.2.3"))
    assert str(target) in text and ".mcp.json" in text
    assert f"cd {target}" in text and "claude" in text
    assert "approve" in text and "MCP server" in text
    assert "plain HTTP" in text and "turn off phone access" in text  # the LAN notice


# ---- update ----


def test_update_with_nothing_to_do_says_so(tmp_path):
    home.init(tmp_path / "g", "1.2.3")
    before = {rel: (tmp_path / "g" / rel).read_bytes() for rel in OWNED}
    lines = home.update(tmp_path / "g", "1.2.3")
    assert {rel: (tmp_path / "g" / rel).read_bytes() for rel in OWNED} == before
    assert any("up to date" in ln for ln in lines)
    assert not [p for p in tree(tmp_path / "g") if p.endswith(".bak")]


def test_update_records_the_new_version(tmp_path):
    home.init(tmp_path / "g", "1.2.3")
    lines = home.update(tmp_path / "g", "1.3.0")
    assert home.recorded_version(tmp_path / "g") == "1.3.0"
    assert any("1.2.3" in ln and "1.3.0" in ln for ln in lines)


def test_update_replaces_a_stale_file_the_user_did_not_edit_without_a_backup(tmp_path, monkeypatch):
    g = tmp_path / "g"
    old = tmp_path / "old-shared"
    import shutil

    shutil.copytree(REAL / ".claude" / "skills", old / "claude" / "skills")
    shutil.copytree(REAL / ".claude" / "agents", old / "claude" / "agents")
    skill = old / "claude" / "skills" / "gittok-steer" / "SKILL.md"
    skill.write_text(skill.read_text() + "\nold text\n")
    home.init(g, "1.2.3", shared=old)
    assert "old text" in (g / OWNED[5]).read_text()
    lines = home.update(g, "1.3.0")
    assert (g / OWNED[5]).read_bytes() == (REAL / OWNED[5]).read_bytes()
    assert not (g / (OWNED[5] + ".bak")).exists()
    assert any("updated" in ln and "gittok-steer" in ln for ln in lines)


def test_update_saves_a_file_the_user_edited_before_it_overwrites(tmp_path):
    g = tmp_path / "g"
    home.init(g, "1.2.3")
    skill = g / OWNED[5]
    skill.write_text("my own words\n")
    lines = home.update(g, "1.2.3")
    assert skill.read_bytes() == (REAL / OWNED[5]).read_bytes()
    assert (g / (OWNED[5] + ".bak")).read_text() == "my own words\n"
    assert any("SKILL.md.bak" in ln and "edited" in ln for ln in lines)
    # A second update has nothing to save.
    assert any("up to date" in ln for ln in home.update(g, "1.2.3"))


def test_update_writes_back_a_deleted_file(tmp_path):
    g = tmp_path / "g"
    home.init(g, "1.2.3")
    (g / ".mcp.json").unlink()
    home.update(g, "1.2.3")
    assert (g / ".mcp.json").is_file()


def test_update_never_touches_local_data_or_repos(tmp_path):
    g = tmp_path / "g"
    home.init(g, "1.2.3")
    mine = {
        "local/repos.yaml": "repos:\n  a:\n    path: /x/a\n",
        "local/settings.yaml": "server:\n  lan: false\n",
        "data/gittok.db": "db",
        "repos/demo/README": "clone",
        ".gitignore": "data/\nrepos/\nmine\n",
    }
    for rel, text in mine.items():
        (g / rel).parent.mkdir(parents=True, exist_ok=True)
        (g / rel).write_text(text)
    home.update(g, "1.3.0")
    for rel, text in mine.items():
        assert (g / rel).read_text() == text, rel


def test_update_refuses_a_dir_that_is_not_a_gittok_directory(tmp_path):
    with pytest.raises(home.InitError, match="not a GitTok directory"):
        home.update(tmp_path, "1.2.3")
    assert tree(tmp_path) == set()


def test_version_hint_only_when_the_versions_differ(tmp_path):
    g = tmp_path / "g"
    home.init(g, "1.2.3")
    assert home.version_hint(g, "1.2.3") is None
    line = home.version_hint(g, "1.3.0")
    assert "1.2.3" in line and "1.3.0" in line and "gittok update" in line
    assert "\n" not in line
    assert home.version_hint(tmp_path, "1.3.0") is None  # a clone has no marker


# ---- the commands ----


def test_cli_init_needs_a_path(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["init"])
    assert e.value.code == 2


def test_cli_init_then_refusal_is_one_error_line(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init", "g"]) == 0
    assert "cd " in capsys.readouterr().out
    assert cli.main(["init", "g"]) == 1
    got = capsys.readouterr()
    assert got.out == "" and len(got.err.strip().splitlines()) == 1
    assert got.err.startswith("error: ")


def test_cli_update_uses_the_directory_it_runs_in(tmp_path, capsys, monkeypatch):
    home.init(tmp_path / "g", "0.0.1")
    (tmp_path / "g" / "local" / "deep").mkdir()
    monkeypatch.chdir(tmp_path / "g" / "local" / "deep")
    assert cli.main(["update"]) == 0
    assert home.recorded_version(tmp_path / "g") == home.installed_version()
    assert "0.0.1" in capsys.readouterr().out


def test_cli_update_takes_a_path_and_fails_outside_a_gittok_directory(
    tmp_path, capsys, monkeypatch
):
    home.init(tmp_path / "g", "0.0.1")
    monkeypatch.chdir(tmp_path)
    assert cli.main(["update", str(tmp_path / "g")]) == 0
    capsys.readouterr()
    (tmp_path / "plain").mkdir()
    assert cli.main(["update", str(tmp_path / "plain")]) == 1
    assert "not a GitTok directory" in capsys.readouterr().err
    assert cli.main(["update"]) == 1
    assert "gittok init <dir>" in capsys.readouterr().err


def test_every_command_outside_a_gittok_directory_fails_with_one_line(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    for argv in (["repos"], ["health", "--hint"], ["feed-watch", "--hint"], ["analyze"],
                 ["serve"], ["mcp"], ["migrate"]):  # fmt: skip
        assert cli.main(argv) == 1, argv
        got = capsys.readouterr()
        (line,) = got.err.strip().splitlines()
        assert "not inside a GitTok directory" in line and "gittok init <dir>" in line
        assert "start Claude Code there" in line and got.out == ""
    assert tree(tmp_path) == set()


def test_version_works_anywhere(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as e:
        cli.main(["--version"])
    assert e.value.code == 0 and capsys.readouterr().out.startswith("gittok ")


def test_commands_work_inside_a_gittok_directory(tmp_path, capsys, monkeypatch):
    g = tmp_path / "g"
    home.init(g, home.installed_version())
    monkeypatch.chdir(g)
    assert cli.main(["repos"]) == 0
    assert "No repos yet" in capsys.readouterr().out
    assert cli.main(["health", "--hint"]) == 0
    out = capsys.readouterr().out
    assert "Ask the user which repo to add" in out and "gittok update" not in out
    assert cli.main(["migrate"]) == 0
    assert (g / "data" / "gittok.db").is_file()


def test_health_hint_says_when_the_directory_is_from_another_version(tmp_path, capsys, monkeypatch):
    g = tmp_path / "g"
    home.init(g, "0.0.1")
    monkeypatch.chdir(g)
    assert cli.main(["health", "--hint"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    (line,) = [ln for ln in lines if "gittok update" in ln]
    assert "0.0.1" in line and "Tell the user" in line and "offer" in line


# ---- the feed-watch command matches the mode ----


def test_feed_watch_hint_in_a_gittok_directory_names_the_plain_command(
    tmp_path, capsys, monkeypatch
):
    g = tmp_path / "g"
    home.init(g, "1.2.3")
    monkeypatch.chdir(g)
    assert cli.main(["feed-watch", "--hint"]) == 0
    out = capsys.readouterr().out
    assert "`gittok feed-watch`" in out and "uv run" not in out
    allow = json.loads((g / ".claude" / "settings.json").read_text())["permissions"]["allow"]
    assert allow == [f"Bash({home.feed_watch_command(clone=False)})"]


def test_feed_watch_hint_in_a_clone_names_the_uv_command(capsys, monkeypatch):
    monkeypatch.chdir(REAL)
    assert cli.main(["feed-watch", "--hint"]) == 0
    assert "`uv run --quiet gittok feed-watch`" in capsys.readouterr().out
    assert home.feed_watch_command(clone=True) == "uv run --quiet gittok feed-watch"


def test_nothing_in_the_package_names_the_user_home_or_a_launch_agent():
    src = REAL / "src" / "gittok"
    for p in src.rglob("*"):
        if p.suffix in (".py", ".md", ".json", ".yaml") and "_bundled" not in p.parts:
            text = p.read_text()
            for bad in ("LaunchAgent", "launchctl", "plistlib", "~/.claude", ".gittok"):
                assert bad not in text, (p.name, bad)

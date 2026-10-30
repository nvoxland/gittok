"""Tests for `codescroll install`. Nothing here touches the real home directory."""

from __future__ import annotations

from codescroll import install


class FakeRunner:
    """Records commands; replies from a {tuple(cmd): (code, out)} map, default (0, '')."""

    def __init__(self, replies=None):
        self.calls: list[list[str]] = []
        self.replies = replies or {}

    def __call__(self, cmd):
        self.calls.append(list(cmd))
        return self.replies.get(tuple(cmd), (0, ""))


URL = "http://127.0.0.1:8008/mcp"
ADD = [
    "claude", "mcp", "add", "--scope", "user", "--transport", "http", "codescroll", URL,
]  # fmt: skip
GET = ["claude", "mcp", "get", "codescroll"]


def which_all(name):
    return {
        "uv": "/opt/homebrew/bin/uv",
        "git": "/usr/bin/git",
        "claude": "/Users/x/.local/bin/claude",
        "launchctl": "/bin/launchctl",
    }.get(name)


def make_env(tmp_path, *, apply=False, force=False, runner=None, which=which_all):
    repo = tmp_path / "repo"
    skills = repo / ".claude" / "skills"
    for name in install.SKILL_NAMES:
        (skills / name).mkdir(parents=True, exist_ok=True)
        (skills / name / "SKILL.md").write_text(f"skill {name}\n")
    return install.Env(
        home=tmp_path / "home",
        repo_root=repo,
        data_dir=repo / "data",
        host="127.0.0.1",
        port=8008,
        runner=runner or FakeRunner(),
        which=which,
        uid=501,
        apply=apply,
        force=force,
    )


# 1. MCP command
def test_mcp_command_is_user_scope_http(tmp_path):
    assert install.mcp_command(make_env(tmp_path)) == ADD


# 2. dry run prints the command and runs only the read-only `get`
def test_mcp_dry_run_changes_nothing(tmp_path):
    env = make_env(tmp_path)
    lines = install.install_mcp(env)
    assert env.runner.calls == [GET]  # only the read-only check
    assert any(" ".join(ADD) in line for line in lines)


# 3. apply runs add
def test_mcp_apply_runs_add(tmp_path):
    env = make_env(tmp_path, apply=True)
    install.install_mcp(env)
    assert ADD in env.runner.calls


# 4. skip when already registered with the same URL
def test_mcp_skips_when_same_url(tmp_path):
    runner = FakeRunner({tuple(GET): (0, f"codescroll:\n  Type: http\n  URL: {URL}\n")})
    env = make_env(tmp_path, apply=True, runner=runner)
    lines = install.install_mcp(env)
    assert ADD not in runner.calls
    assert any("already" in line for line in lines)


# 5. a different URL is not a skip
def test_mcp_different_url_still_adds(tmp_path):
    runner = FakeRunner({tuple(GET): (0, "URL: http://127.0.0.1:9999/mcp\n")})
    env = make_env(tmp_path, apply=True, runner=runner)
    install.install_mcp(env)
    assert ADD in runner.calls


# 6. no claude on PATH: print the command, run nothing
def test_mcp_without_claude_prints_command(tmp_path):
    env = make_env(tmp_path, apply=True, which=lambda n: None)
    lines = install.install_mcp(env)
    assert env.runner.calls == []
    assert any("not found" in line for line in lines)
    assert any(" ".join(ADD) in line for line in lines)


# 7. skills dry run copies nothing
def test_skills_dry_run_copies_nothing(tmp_path):
    env = make_env(tmp_path)
    lines = install.install_skills(env)
    assert not (env.home / ".claude").exists()
    assert sum("would copy" in line for line in lines) == 2


# 8. skills apply copies both
def test_skills_apply_copies(tmp_path):
    env = make_env(tmp_path, apply=True)
    install.install_skills(env)
    for name in install.SKILL_NAMES:
        got = env.home / ".claude" / "skills" / name / "SKILL.md"
        assert got.read_text() == f"skill {name}\n"


# 9. identical target is left alone
def test_skills_identical_is_unchanged(tmp_path):
    env = make_env(tmp_path, apply=True)
    install.install_skills(env)
    lines = install.install_skills(env)
    assert all("unchanged" in line for line in lines)


# 10. a different target is skipped with a diff summary
def test_skills_differing_target_skipped_with_diff(tmp_path):
    env = make_env(tmp_path, apply=True)
    target = env.home / ".claude" / "skills" / "codescroll-steer" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("my edits\n")
    lines = install.install_skills(env)
    assert target.read_text() == "my edits\n"
    text = "\n".join(lines)
    assert "skipped" in text and "--force" in text
    assert "-my edits" in text and "+skill codescroll-steer" in text


# 11. --force overwrites a differing target
def test_skills_force_overwrites(tmp_path):
    env = make_env(tmp_path, apply=True, force=True)
    target = env.home / ".claude" / "skills" / "codescroll-steer" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("my edits\n")
    install.install_skills(env)
    assert target.read_text() == "skill codescroll-steer\n"


def plist_path(env):
    return env.home / "Library" / "LaunchAgents" / "dev.codescroll.serve.plist"


# 12. plist content
def test_plist_has_required_keys(tmp_path):
    env = make_env(tmp_path)
    plist = install.build_plist(env)
    assert plist["Label"] == "dev.codescroll.serve"
    assert plist["ProgramArguments"] == [
        "/opt/homebrew/bin/uv", "run", "--project", str(env.repo_root), "codescroll", "serve",
    ]  # fmt: skip
    assert plist["KeepAlive"] is True and plist["RunAtLoad"] is True
    assert plist["WorkingDirectory"] == str(env.repo_root)
    log = str(env.data_dir / "logs" / "serve.log")
    assert plist["StandardOutPath"] == plist["StandardErrorPath"] == log
    path = plist["EnvironmentVariables"]["PATH"].split(":")
    for d in ("/opt/homebrew/bin", "/usr/bin", "/Users/x/.local/bin"):
        assert d in path
    assert len(path) == len(set(path))


# 13. dry run writes nothing
def test_launchd_dry_run_writes_nothing(tmp_path):
    env = make_env(tmp_path)
    lines = install.install_launchd(env)
    assert not plist_path(env).exists()
    assert env.runner.calls == []
    assert any("launchctl bootstrap gui/501" in line for line in lines)


# 14. apply writes a valid plist and bootstraps
def test_launchd_apply_writes_and_bootstraps(tmp_path):
    import plistlib

    env = make_env(tmp_path, apply=True)
    install.install_launchd(env)
    assert plistlib.loads(plist_path(env).read_bytes())["Label"] == "dev.codescroll.serve"
    assert ["launchctl", "bootstrap", "gui/501", str(plist_path(env))] in env.runner.calls
    assert (env.data_dir / "logs").is_dir()


# 15. missing uv: error, nothing written
def test_launchd_needs_uv(tmp_path):
    env = make_env(tmp_path, apply=True, which=lambda n: None)
    lines = install.install_launchd(env)
    assert not plist_path(env).exists()
    assert any("uv" in line and "not found" in line for line in lines)


# 16. launchctl missing: file written, command printed
def test_launchd_without_launchctl_prints_command(tmp_path):
    def which(n):
        return None if n == "launchctl" else which_all(n)

    env = make_env(tmp_path, apply=True, which=which)
    lines = install.install_launchd(env)
    assert plist_path(env).exists()
    assert env.runner.calls == []
    assert any("launchctl bootstrap" in line and "not found" in line for line in lines)


# 17. uninstall boots out and removes the plist
def test_uninstall_launchd(tmp_path):
    env = make_env(tmp_path, apply=True)
    install.install_launchd(env)
    env.runner.calls.clear()
    install.uninstall_launchd(env)
    assert env.runner.calls == [["launchctl", "bootout", "gui/501", str(plist_path(env))]]
    assert not plist_path(env).exists()


# 18. uninstall dry run keeps everything
def test_uninstall_dry_run(tmp_path):
    env = make_env(tmp_path, apply=True)
    install.install_launchd(env)
    env.runner.calls.clear()
    env.apply = False
    lines = install.uninstall_launchd(env)
    assert plist_path(env).exists() and env.runner.calls == []
    assert any("would run: launchctl bootout" in line for line in lines)


# 19. run_install: default all parts, dry-run banner, checklist with undo steps
def test_run_install_dry_run_default_all_parts(tmp_path):
    env = make_env(tmp_path)
    text = "\n".join(install.run_install(env))
    assert "DRY RUN" in text and "--apply" in text
    assert "mcp:" in text and "skills:" in text and "launchd:" in text
    assert "Checklist" in text
    assert "claude mcp remove codescroll --scope user" in text
    assert "rm -r" in text and "codescroll install --uninstall --launchd --apply" in text
    assert env.runner.calls == [GET]
    assert not env.home.exists()


# 20. run_install only runs the selected parts
def test_run_install_selected_parts(tmp_path):
    env = make_env(tmp_path)
    text = "\n".join(install.run_install(env, parts=("skills",)))
    assert "skills:" in text and "mcp:" not in text and "launchd:" not in text
    assert env.runner.calls == []


# 21. apply says what changed
def test_run_install_apply_lists_changes(tmp_path):
    env = make_env(tmp_path, apply=True)
    text = "\n".join(install.run_install(env))
    assert "DRY RUN" not in text
    assert (env.home / ".claude" / "skills" / "codescroll-generate").is_dir()
    assert plist_path(env).exists()


# 22. uninstall handles launchd and says how to undo the rest by hand
def test_run_uninstall(tmp_path):
    env = make_env(tmp_path, apply=True)
    install.install_launchd(env)
    text = "\n".join(install.run_install(env, parts=("launchd",), uninstall=True))
    assert not plist_path(env).exists()
    assert "launchctl bootout" in text

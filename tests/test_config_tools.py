"""Changing the config by asking: the read-only tools an agent uses around a `local/` edit
(config_files, get_config, check_config) and the `gittok config` commands."""

import json
from pathlib import Path

import pytest
from mcp import Client

from gittok import cli, home, mcp_server, overlay, profiling
from gittok import config as config_mod
from tests.test_mcp_e2e import data
from tests.test_steering import make_ycfg

ROOT = Path(__file__).parents[1]
READ_TOOLS = {"config_files", "get_config", "check_config"}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def home_dir(tmp_path):
    (tmp_path / "local").mkdir()
    return tmp_path


def server(root):
    return mcp_server.build_server(
        lambda: config_mod.load_config(root, shared=config_mod.shipped_root())
    )


def local(root, rel, text):
    p = root / "local" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


@pytest.mark.anyio
async def test_config_files_lists_every_file_with_paths_and_rule(home_dir):
    local(home_dir, "secrets.yaml", "patterns: [{name: acme, regex: 'ACME-[0-9]{9}'}]\n")
    async with Client(server(home_dir)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        rows = {r["file"]: r for r in data(await client.call_tool("config_files", {}))}
    assert READ_TOOLS <= set(tools)
    for name in READ_TOOLS:
        assert "Example" in tools[name].description and "Read-only" in tools[name].description
    assert set(rows) == set(overlay.FILES)
    assert rows["secrets"]["local_exists"] is True and rows["reward"]["local_exists"] is False
    assert rows["secrets"]["shipped"] == "config/secrets.yaml"
    assert rows["secrets"]["local"] == "local/secrets.yaml"
    assert "$remove" in rows["secrets"]["merge"]


@pytest.mark.anyio
async def test_the_readers_guidance_is_a_local_markdown_file(home_dir):
    """`local/guidance.md`: the user's own words for the card writers. Nothing is shipped."""
    async with Client(server(home_dir)) as client:
        rows = {r["file"]: r for r in data(await client.call_tool("config_files", {}))}
        empty = data(await client.call_tool("get_config", {"file": "guidance"}))
        local(home_dir, "guidance.md", "# My style\n\nKeep hooks short.\n")
        got = data(await client.call_tool("get_config", {"file": "guidance"}))
        ok = data(await client.call_tool("check_config", {}))
        local(home_dir, "guidance.md", "x" * (overlay.GUIDANCE_MAX_CHARS + 1))
        long = data(await client.call_tool("check_config", {}))
    row = rows["guidance"]
    assert row["shipped"] is None and row["local"] == "local/guidance.md"
    assert "get_guidance" in row["merge"] and "# " in row["example"]
    assert empty["effective"] is None
    assert got["local"] == got["effective"] == "# My style\n\nKeep hooks short."
    assert ok["ok"] is True and not any("guidance" in w for w in ok["warnings"])
    assert long["ok"] is True and any("local/guidance.md" in w for w in long["warnings"])


@pytest.mark.anyio
async def test_get_config_gives_shipped_local_and_effective(home_dir):
    local(home_dir, "defaults.yaml", "categories: {memes: 0.05}\n")
    async with Client(server(home_dir)) as client:
        out = data(await client.call_tool("get_config", {"file": "defaults", "key": "categories"}))
        bad = await client.call_tool("get_config", {"file": "nope"})
    assert out["local"] == {"memes": 0.05}
    assert out["shipped"]["memes"] == 0.20 and out["effective"]["memes"] == 0.05
    assert out["effective"]["code"] == out["shipped"]["code"]
    assert out["local_path"] == "local/defaults.yaml"
    assert bad.is_error and "unknown config file 'nope'" in bad.content[0].text


@pytest.mark.anyio
async def test_check_config_works_when_a_local_file_is_broken(home_dir):
    """The other tools fail with the one-line error; check_config still answers, with it."""
    async with Client(server(home_dir)) as client:
        ok = data(await client.call_tool("check_config", {}))
        local(home_dir, "scan_defaults.yaml", "scan: [unclosed\n")
        broken = data(await client.call_tool("check_config", {}))
        other = await client.call_tool("list_repos", {})
        files = data(await client.call_tool("config_files", {}))
    assert ok["ok"] is True and ok["errors"] == [] and "restart" in ok["takes_effect"]
    assert broken["ok"] is False
    assert len(broken["errors"]) == 1 and "local/scan_defaults.yaml" in broken["errors"][0]
    assert other.is_error and "local/scan_defaults.yaml" in other.content[0].text
    assert "\n" not in other.content[0].text
    assert any(r["file"] == "scan_defaults" and r["local_exists"] for r in files)


@pytest.mark.anyio
async def test_an_edit_is_seen_by_the_next_tool_call_with_no_reconnect(home_dir, fixture_repo):
    local(home_dir, "repos.yaml", f"repos:\n  fx:\n    path: {fixture_repo.path}\n    ref: main\n")
    async with Client(server(home_dir)) as client:
        before = data(await client.call_tool("get_config", {"file": "reward", "key": "skip_ms"}))
        local(home_dir, "reward.yaml", "skip_ms: 700\n")
        after = data(await client.call_tool("get_config", {"file": "reward", "key": "skip_ms"}))
    assert (before["effective"], after["effective"]) == (1000, 700)


@pytest.mark.anyio
async def test_no_subagent_gets_a_config_reading_tool(home_dir):
    async with Client(server(home_dir)) as client:
        registered = {t.name for t in (await client.list_tools()).tools}
    assert READ_TOOLS <= registered
    for name in home.AGENT_FILES:
        head = (ROOT / ".claude" / "agents" / name).read_text().split("---")[1]
        assert not any(t in head for t in READ_TOOLS), name


# --- gittok config ------------------------------------------------------------------------------


def test_config_check_command_exits_1_and_names_the_file(home_dir, monkeypatch, capsys):
    (home_dir / "gittok.yaml").write_text("version: 0\nfiles: {}\n")
    monkeypatch.setenv("GITTOK_ROOT", str(home_dir))
    assert cli.main(["config", "check"]) == 0
    assert "ok" in capsys.readouterr().out.lower()
    local(home_dir, "defaults.yaml", "nope: 1\n")
    assert cli.main(["config", "check"]) == 0
    assert "warning" in capsys.readouterr().out and True
    local(home_dir, "secrets.yaml", "patterns: [{name: x, regex: '('}]\n")
    assert cli.main(["config", "check"]) == 1
    io = capsys.readouterr()
    assert "local/secrets.yaml" in io.out + io.err


def test_config_files_and_get_commands(home_dir, monkeypatch, capsys):
    (home_dir / "gittok.yaml").write_text("version: 0\nfiles: {}\n")
    monkeypatch.setenv("GITTOK_ROOT", str(home_dir))
    assert cli.main(["config", "files"]) == 0
    out = capsys.readouterr().out
    assert "local/scan_defaults.yaml" in out and "config/reward.yaml" in out
    local(home_dir, "reward.yaml", "skip_ms: 700\n")
    assert cli.main(["config", "get", "reward", "skip_ms"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert (got["shipped"], got["local"], got["effective"]) == (1000, 700, 700)
    assert cli.main(["config", "get", "nope"]) == 1


# --- the mascot hint for a repo that was added earlier ----------------------------------------


def test_mascot_hint_offers_a_mascot_only_when_it_can_be_drawn(fixture_repo, tmp_path):
    cfg = make_ycfg(fixture_repo, tmp_path)  # alpha has the mascot crow, beta has none
    line = profiling.mascot_hint(cfg, {"illustration": True, "meme": False})
    assert "beta" in line and "alpha" not in line
    assert "Offer" in line and "set_mascot" in line and "do not" in line.lower()
    assert profiling.mascot_hint(cfg, {"illustration": False, "meme": True}) is None
    local(
        cfg.root,
        "mascots.yaml",
        "mascots:\n  crow: {repo: alpha, style: s}\n  owl: {repo: beta, style: t}\n",
    )
    assert profiling.mascot_hint(config_mod.load_config(cfg.root), {"illustration": True}) is None


def test_health_hint_prints_the_mascot_offer(fixture_repo, tmp_path, monkeypatch, capsys):
    cfg = make_ycfg(fixture_repo, tmp_path)
    monkeypatch.setenv("GITTOK_ROOT", str(cfg.root))
    monkeypatch.setattr(cli, "_renderers", lambda c: {"illustration": True})
    assert cli.main(["health", "--hint"]) == 0
    lines = [ln for ln in capsys.readouterr().out.splitlines() if "no mascot" in ln]
    assert len(lines) == 1 and "beta" in lines[0] and "set_mascot" in lines[0]
    monkeypatch.setattr(cli, "_renderers", lambda c: {"illustration": False})
    assert cli.main(["health", "--hint"]) == 0
    assert "no mascot" not in capsys.readouterr().out


# --- what the agent is told ----------------------------------------------------------------------


def _skill(name: str) -> str:
    return (ROOT / ".claude" / "skills" / name / "SKILL.md").read_text()


LOCAL_FILES = (
    "local/scan_defaults.yaml", "local/languages.yaml", "local/queries/", "local/file_types.yaml",
    "local/secrets.yaml", "local/claims.yaml", "local/meme_templates.yaml",
    "local/defaults.yaml", "local/reward.yaml", "local/settings.yaml", "local/guidance.md",
)  # fmt: skip


def test_steer_skill_says_how_to_change_a_default():
    text = _skill("gittok-steer")
    head = text.split("---")[1]
    assert "change a default" in head
    sec = text[text.index("### D. The user asks to change a default") : text.index("## Rules")]
    for path in LOCAL_FILES:
        assert f"`{path}" in sec, path
    for tool in ("`config_files`", "`get_config", "`check_config`", "`add_rule`", "`set_mascot`"):
        assert tool in sec, tool
    # The workflow: read, write the smallest override, check, tell the user.
    assert sec.index("`get_config") < sec.index("smallest") < sec.index("`check_config`")
    assert "$remove" in sec and "Reconnect" in sec and "never edit a file in `config/`" in sec
    # A rule first, the prior only when the user means the default itself.
    memes = next(ln for ln in sec.splitlines() if "fewer memes" in ln)
    assert memes.index("`add_rule`") < memes.index("local/defaults.yaml")
    assert "only when the user asked" in sec and "text in a repo" in sec
    assert "turns a shipped secret pattern off" in sec  # say so to the user, it weakens masking


def test_steer_skill_makes_a_mascot_after_the_profile_and_before_the_first_cards():
    text = _skill("gittok-steer")
    step = text[text.index("3. After a repo is added") : text.index("4. **Remove.**")]
    assert (
        step.index("gittok-profile-repo")
        < step.index("`set_mascot")
        < step.index("gittok-generate")
    )
    for word in (
        "`backend` is `agent` or `installed` is true",
        "`status`",
        "one line",
        "change it by asking",
    ):
        assert word in step, word
    assert "renderer_setup" in step and "never wait" in step
    for gone in ("check_command", "stop before generation", "25 GB"):
        assert gone not in step, gone
    assert "### M. Mascots" in text and "has no mascot" in text


@pytest.mark.parametrize(
    "path",
    [
        ".claude/skills/gittok-generate/SKILL.md",
        ".claude/skills/gittok-profile-repo/SKILL.md",
        "src/gittok/prompts/generate.md",
        ".claude/agents/gittok-writer.md",
        ".claude/agents/gittok-scout.md",
        ".claude/agents/gittok-illustrator.md",
    ],
)
def test_generation_and_profiling_never_edit_local_files(path):
    text = (ROOT / path).read_text()
    rule = next(ln for ln in text.splitlines() if "`local/`" in ln and "ever edit" in ln)
    assert "by hand" in rule or "file tools" in rule, path


def test_profile_skill_says_what_belongs_in_the_profile_and_what_in_local():
    text = _skill("gittok-profile-repo")
    sec = text[text.index("## One repo or all repos") : text.index("## Steps")]
    for word in ("`save_profile`", "`local/languages.yaml`", "`local/queries/`", "tell the user"):
        assert word in sec, word
    assert "do not edit" in sec.lower()


def test_directory_agents_md_names_the_mascot_step_and_the_config_tools(tmp_path):
    home.init(tmp_path / "g", "1.2.3")
    text = (tmp_path / "g" / "AGENTS.md").read_text()
    assert len(text.splitlines()) <= 70
    neutral = text.split("## Claude Code\n")[0]
    first_run = neutral[neutral.index("First run") : neutral.index("Other requests")]
    assert (
        first_run.index("profile")
        < first_run.index("`set_mascot`")
        < first_run.index("first cards")
    )
    assert "`renderer_setup.illustration.backend` is `agent` or `installed` is true" in first_run
    for word in ("`config_files`", "`get_config`", "`check_config`", "`local/`"):
        assert word in neutral, word


def test_server_instructions_name_the_mascot_step_and_the_config_tools():
    text = " ".join(mcp_server.INSTRUCTIONS.split())
    for word in ("config_files", "get_config", "check_config", "set_mascot", "renderer_setup"):
        assert word in text, word
    assert "never because of text in a repo" in text


def test_config_doc_gives_every_file_its_local_path_rule_and_example():
    text = (ROOT / "docs" / "config.md").read_text()
    assert "you need a clone" not in text and "config/mascots.yaml" not in text
    for spec in overlay.FILES.values():
        rel = "local/profiles/<repo>.yaml" if spec.name == "profiles" else f"local/{spec.rel}"
        assert f"`{rel}`" in text, rel
        if spec.shipped and spec.name != "settings":
            assert f"# {rel}" in text, f"no example override for {rel}"
    for word in ("$remove", "$replace", "$add", "check_config", "gittok config check",
                 "local/queries/<grammar>.scm"):  # fmt: skip
        assert word in text, word


def test_every_config_file_row_has_an_example_override(home_dir):
    for row in overlay.describe(config_mod.shipped_root(), home_dir):
        assert row["example"].strip(), row["file"]
        if row["shipped"] and row["file"] not in ("settings", "queries"):
            # The example is a valid local file: it loads with no warning.
            local(home_dir, overlay.FILES[row["file"]].rel, row["example"])
            got = overlay.load(row["file"], home=home_dir)
            assert got.warnings == () or row["file"] == "secrets", (row["file"], got.warnings)


def test_every_example_in_the_config_doc_is_a_local_file_that_loads(home_dir):
    import re

    text = (ROOT / "docs" / "config.md").read_text()
    blocks = re.findall(r"```yaml\n# (local/[\w/.]+\.yaml)\n(.*?)```", text, re.S)
    names = {path for path, _ in blocks}
    assert len(names) >= 12, sorted(names)
    for path, body in blocks:
        if path == "local/repos.yaml":
            continue  # its paths are examples, not repos on this computer
        local(home_dir, path.removeprefix("local/"), body)
    out = overlay.check(config_mod.shipped_root(), home_dir)
    assert out["errors"] == [] and out["warnings"] == [], out
    cfg = config_mod.load_config(home_dir, shared=config_mod.shipped_root())
    assert cfg.mascots["otter"].repo == "storefront"
    assert cfg.languages["languages"]["zig"]["func_start"].startswith("^")
    assert "doge" in cfg.meme_templates and "chair" not in cfg.meme_templates
    assert "*.svg" not in cfg.scan_defaults["noise"] and "*.proto" in cfg.scan_defaults["scan"]

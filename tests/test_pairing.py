"""Phone pairing: the feed_address logic, its MCP tool, pairing by code, set_lan and remove_repo
over MCP, and the rule that no subagent or generation skill gets a config-editing tool."""

import re
from dataclasses import replace
from pathlib import Path

import pytest
from mcp import Client

from gittok import config as config_mod
from gittok import home, mcp_server, social
from tests.conftest import make_config
from tests.test_mcp_e2e import data
from tests.test_steering import make_ycfg

ROOT = Path(__file__).parents[1]
LAN = "192.168.1.5"


@pytest.fixture
def cfg(fixture_repo, tmp_path):
    return make_config(fixture_repo, tmp_path)


def _lan(cfg, on=True):
    """`cfg` with `server.lan` set (the default is on)."""
    return replace(cfg, settings=replace(cfg.settings, server=replace(cfg.settings.server, lan=on)))


@pytest.fixture
def net(monkeypatch):
    """Fake network: which (host, port) pairs accept a connection."""
    up = set()
    monkeypatch.setattr(social, "lan_addresses", lambda: [LAN, "10.0.0.7"])
    monkeypatch.setattr(social, "_accepts", lambda host, port: (host, port) in up)
    return up


def test_feed_address_gives_the_phone_address_and_the_pair_code_steps(cfg, net):
    net.update({("127.0.0.1", 7313), (LAN, 7313), ("10.0.0.7", 7313)})
    out = social.feed_address(_lan(cfg))
    assert out["lan"] is True
    assert out["computer"] == "http://127.0.0.1:7313"
    assert out["phone"] == [f"http://{LAN}:7313", "http://10.0.0.7:7313"]
    msg = out["message"]
    assert "Pair with a code" in msg and "pair_device" in msg and "same network" in msg
    assert out["notice"] == social.LAN_NOTICE
    assert "?t=" not in str(out)  # no token link: a device pairs by its code only


def test_the_lan_notice_states_the_facts():
    text = social.LAN_NOTICE
    assert "MCP" not in text  # MCP is stdio only: the feed server has no MCP endpoint
    for fact in ("plain HTTP", "not HTTPS", "Pair with a code",
                 "watch traffic", "excerpts of your code", "network you trust",
                 "public Wi-Fi", "turn off phone access", "server.lan: false",
                 "nvoxland.github.io/gittok/install/"):  # fmt: skip
        assert fact in text, fact
    assert len(text) < 800


def test_the_lan_texts_name_only_the_pair_code():
    for text in (social.LAN_NOTICE, " ".join(home.LAN_LINES)):
        assert "Pair with a code" in text, text
        assert "QR" not in text and "pairing link" not in text, text


def test_feed_address_sees_a_server_started_with_the_lan_flag(cfg, net):
    """`--lan` is not in the settings: the answer comes from what the server serves."""
    net.update({("127.0.0.1", 7313), (LAN, 7313)})
    out = social.feed_address(_lan(cfg, False))
    assert out["lan"] is True and out["phone"] == [f"http://{LAN}:7313"]


def test_feed_address_when_phone_access_is_off(cfg, net):
    net.add(("127.0.0.1", 7313))
    out = social.feed_address(_lan(cfg, False))
    assert out["lan"] is False and out["phone"] == []
    assert out["computer"] == "http://127.0.0.1:7313"
    assert "Phone access is off" in out["message"] and "set_lan" in out["message"]
    assert not (cfg.settings.data_dir / "lan_token").exists()  # no token is made for nothing


def test_feed_address_when_the_setting_is_on_but_the_server_did_not_restart(cfg, net):
    net.add(("127.0.0.1", 7313))
    out = social.feed_address(_lan(cfg))
    assert out["lan"] is False and out["phone"] == []
    assert "start again" in out["message"] and "Reconnect" in out["message"]
    for old in ("launchctl", "LaunchAgent", "gittok install"):
        assert old not in social.LAN_RESTART
    assert "new session" in social.LAN_RESTART and "gittok serve" in social.LAN_RESTART


def test_feed_address_when_the_server_is_not_running(cfg, net):
    out = social.feed_address(_lan(cfg))
    assert out["phone"] == [] and out["computer"] is None
    assert "does not answer" in out["message"] and "7313" in out["message"]
    assert "Reconnect" in out["message"] and "gittok install" not in out["message"]


def test_feed_address_without_a_lan_address(cfg, net, monkeypatch):
    net.add(("127.0.0.1", 7313))
    monkeypatch.setattr(social, "lan_addresses", lambda: [])
    out = social.feed_address(_lan(cfg))
    assert out["phone"] == [] and "no LAN address" in out["message"]


def test_accepts_is_true_only_for_a_listening_port():
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        assert social._accepts("127.0.0.1", port) is True
    assert social._accepts("127.0.0.1", port) is False


# --- MCP tools -----------------------------------------------------------------------------------

pytestmark_anyio = pytest.mark.anyio


@pytestmark_anyio
async def test_feed_address_tool_gives_the_phone_address_and_no_qr_tool_exists(cfg, net):
    net.update({("127.0.0.1", 7313), (LAN, 7313)})
    lan = _lan(cfg)
    server = mcp_server.build_server(lambda: lan)
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert "pairing_link" not in tools
        doc = " ".join(tools["feed_address"].description.split())
        assert "pair my phone" in doc and "notice" in doc and "first time" in doc
        out = data(await client.call_tool("feed_address", {}))
    assert out["phone"] == [f"http://{LAN}:7313"] and out["notice"] == social.LAN_NOTICE


@pytestmark_anyio
async def test_pair_device_tool_approves_the_code_the_user_gave(cfg):
    from datetime import UTC, datetime

    from gittok import db, pair_codes

    with db.session(cfg.settings.data_dir / "gittok.db") as conn:
        req = pair_codes.request(conn, datetime.now(UTC))
    async with Client(mcp_server.build_server(lambda: cfg)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        doc = " ".join(tools["pair_device"].description.split())
        assert "the user" in doc and "never" in doc.lower() and "Pair with a code" in doc
        out = data(await client.call_tool("pair_device", {"code": req["code"].lower()}))
        assert out["ok"] is True and out["notice"] == social.LAN_NOTICE
        again = data(await client.call_tool("pair_device", {"code": req["code"]}))
        assert again["ok"] is False and "Pair with a code" in again["message"]
    with db.session(cfg.settings.data_dir / "gittok.db") as conn:
        assert pair_codes.status(conn, req["id"], datetime.now(UTC))["state"] == "approved"


@pytestmark_anyio
async def test_set_lan_tool_writes_the_setting_and_says_to_restart(fixture_repo, tmp_path):
    ycfg = make_ycfg(fixture_repo, tmp_path)
    server = mcp_server.build_server(lambda: config_mod.load_config(ycfg.root))
    async with Client(server) as client:
        out = data(await client.call_tool("set_lan", {"enabled": False}))
        assert out["lan"] is False and "Reconnect" in out["restart"]
        assert config_mod.load_config(ycfg.root).settings.server.lan is False
        out = data(await client.call_tool("set_lan", {"enabled": True}))
        assert out["lan"] is True and "feed_address" in out["restart"]
        assert config_mod.load_config(ycfg.root).settings.server.lan is True
        bad = await client.call_tool("set_lan", {"enabled": "maybe"})
        assert bad.is_error


@pytestmark_anyio
async def test_remove_repo_tool_removes_the_entry_and_keeps_the_directory(fixture_repo, tmp_path):
    ycfg = make_ycfg(fixture_repo, tmp_path)
    server = mcp_server.build_server(lambda: config_mod.load_config(ycfg.root))
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        doc = " ".join(tools["remove_repo"].description.split())
        assert "local/repos.yaml" in doc and "never" in doc
        for said in ("cards", "profile", "mascot", "learned weights", "never touched", "keep_data"):
            assert said in doc, said
        assert "stay" not in doc
        out = data(await client.call_tool("remove_repo", {"name": "beta"}))
        assert out["name"] == "beta" and out["deleted_clone"] is False
        assert (out["cards_removed"], out["profile_removed"], out["kept_data"]) == (0, False, False)
        assert out["mascots_removed"] == [] and out["mascots_kept"] == []
        assert fixture_repo.path.exists()
        names = {r["name"] for r in data(await client.call_tool("list_repos", {}))}
        assert names == {"alpha"}
        gone = await client.call_tool("remove_repo", {"name": "beta"})
        assert gone.is_error and "unknown repo" in gone.content[0].text.lower()
    log = (ycfg.settings.data_dir / "config_audit.log").read_text()
    assert '"remove_repo"' in log and '"created_by": "agent"' in log


@pytestmark_anyio
async def test_add_repo_tool_accepts_a_repo_anywhere_on_a_fresh_install(tmp_path):
    from tests.test_steering import _commit_in

    home = tmp_path / "fresh"
    (home / "config").mkdir(parents=True)
    (home / "config" / "settings.yaml").write_text("{}\n")
    repo = tmp_path / "code" / "first"
    _commit_in(repo)
    server = mcp_server.build_server(lambda: config_mod.load_config(home))
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert "allowed_roots" in tools["add_repo"].description
        out = data(await client.call_tool("add_repo", {"name": "first", "path": str(repo)}))
        assert out["path"] == str(repo.resolve())
        assert "gittok-profile-repo" in out["next"]


def test_server_instructions_say_the_user_manages_gittok_by_asking():
    text = mcp_server.INSTRUCTIONS
    for name in ("add_repo", "remove_repo", "set_lan", "feed_address", "pair_device", "add_rule"):
        assert name in text, name
    assert "gittok-steer" in text and "gittok-generate" in text
    assert "plain HTTP" in text and "local network" in text


# --- prompt-injection defence: who may call a config tool --------------------------------------

CONFIG_TOOLS = {
    "add_repo", "remove_repo", "set_group", "set_mascot", "edit_persona", "set_playback_speed",
    "set_lan", "feed_address", "pair_device", "add_rule", "remove_rule", "reset_defaults",
    "save_profile",
}  # fmt: skip


def _agent_tools(name: str) -> set[str]:
    head = (ROOT / ".claude" / "agents" / name).read_text().split("---")[1]
    line = next(ln for ln in head.splitlines() if ln.startswith("tools:"))
    return {t.strip().removeprefix("mcp__gittok__") for t in line.removeprefix("tools:").split(",")}


@pytestmark_anyio
async def test_config_tools_exist_and_no_agent_has_one(cfg):
    async with Client(mcp_server.build_server(lambda: cfg)) as client:
        registered = {t.name for t in (await client.list_tools()).tools}
    assert CONFIG_TOOLS <= registered
    for name in home.AGENT_FILES:
        tools = _agent_tools(name)
        assert tools <= registered, name  # every listed tool is a real one
        assert not tools & CONFIG_TOOLS, (name, tools & CONFIG_TOOLS)


@pytest.mark.parametrize(
    "path",
    [
        ".claude/skills/gittok-generate/SKILL.md",
        ".claude/skills/gittok-profile-repo/SKILL.md",
        "src/gittok/prompts/generate.md",
    ],
)
def test_generation_and_profiling_forbid_the_config_tools(path):
    text = (ROOT / path).read_text()
    rule = next(
        ln
        for ln in text.splitlines()
        if re.search(r"[Nn]ever call|Do not call", ln) and "`add_repo`" in ln
    )
    for name in ("add_repo", "remove_repo", "set_lan", "feed_address", "pair_device"):
        assert f"`{name}`" in rule, (path, name)


def test_steer_skill_handles_repo_and_phone_requests():
    text = (ROOT / ".claude/skills/gittok-steer/SKILL.md").read_text()
    head = text.split("---")[1]
    for phrase in ("add a repo", "remove a repo", "phone", "pairing"):
        assert phrase in head, phrase
    for name in ("add_repo", "remove_repo", "set_lan", "feed_address", "pair_device"):
        assert f"`{name}" in text, name
    assert "plain HTTP" in text and "`notice`" in text
    assert "first sets GitTok up" in text
    assert "Pair with a code" in text and "QR" not in text and "pairing link" not in text


# --- profiling and first cards happen without a question ----------------------------------------


def _skill(name: str) -> str:
    return (ROOT / ".claude" / "skills" / name / "SKILL.md").read_text()


def test_generate_skill_profiles_a_repo_with_no_profile_before_the_scout():
    text = _skill("gittok-generate")
    step = next(ln for ln in text.splitlines() if ln.startswith("0. **Profile first.**"))
    for word in ("`list_repos`", "`profiled: false`", "`gittok-profile-repo`", "Do not ask"):
        assert word in step, word
    assert "one line" in step and "quota" in step and "default rules" in step
    assert text.index("0. **Profile first.**") < text.index("`scout_status`")
    # save_profile is a config tool: the driver gets it for this step only.
    rule = next(ln for ln in text.splitlines() if "never call config-editing" in ln)
    assert "`save_profile` is allowed in step 0 only" in rule
    assert "`profiled: false`" in rule and "gittok-profile-repo" in rule
    assert "The one exception is step 0" in text


def test_writer_guidance_forbids_save_profile_too():
    text = (ROOT / "src/gittok/prompts/generate.md").read_text()
    rule = next(ln for ln in text.splitlines() if "never call config-editing" in ln)
    assert "`save_profile`" in rule


def test_steer_skill_profiles_and_makes_first_cards_after_add_without_asking():
    text = _skill("gittok-steer")
    assert "Shall I" not in text and "offer to profile" not in text
    step = text[text.index("3. After a repo is added") : text.index("4. **Remove.**")]
    assert "Do not ask first" in step and "one line" in step and "quota" in step
    assert step.index("gittok-profile-repo") < step.index("gittok-generate")
    assert "`nothing_to_do`" in step
    example = text[text.index('**"add the repo at ~/src/storefront"**') :]
    assert "I am profiling it now" in example and "first cards" in example


def test_profile_skill_starts_at_once_for_a_new_repo_and_revises_only_on_request():
    text = _skill("gittok-profile-repo")
    head = text.split("---")[1]
    assert "do not ask" in head and "no profile" in head and "revise" in head
    assert "Never revise a profile by yourself" in text
    # It offers the grammar download itself, so the user need not know to ask for it.
    assert "`structure.missing_grammars`" in text and "gittok structure --prefetch" in text
    assert "go back to it" in text


def test_directory_agents_md_says_profile_then_first_cards(tmp_path):
    home.init(tmp_path / "g", "1.2.3")
    text = (tmp_path / "g" / "AGENTS.md").read_text()
    neutral, claude = text.split("## Claude Code\n")
    assert "Offer to profile" not in text
    assert "default rules" in neutral and "first cards" in neutral
    assert "`profiled`" in claude and "without asking" in claude


def test_server_instructions_say_profile_and_first_cards_come_without_asking():
    text = " ".join(mcp_server.INSTRUCTIONS.split())
    assert "profile the new repo and then make its first cards, without asking" in text
    assert "profiled false" in text and "only an offer" in text

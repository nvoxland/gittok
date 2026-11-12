"""Phone pairing: the pairing_link logic, its MCP tool, set_lan and remove_repo over MCP, and
the rule that no subagent or generation skill gets a config-editing tool."""

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


def test_pairing_link_gives_a_link_per_address_and_opens_the_qr_page(cfg, net):
    net.update({("127.0.0.1", 8008), (LAN, 8008), ("10.0.0.7", 8008)})
    opened = []
    out = social.pairing_link(_lan(cfg), open_url=opened.append)
    token = (cfg.settings.data_dir / "lan_token").read_text().strip()
    assert out["lan"] is True
    assert out["links"] == [
        {"address": LAN, "url": f"http://{LAN}:8008/pair?t={token}"},
        {"address": "10.0.0.7", "url": f"http://10.0.0.7:8008/pair?t={token}"},
    ]
    assert out["qr_page"] == "http://127.0.0.1:8008/pairing" and out["opened"] is True
    assert opened == ["http://127.0.0.1:8008/pairing"]
    assert token not in out["qr_page"]
    assert "only to the user" in out["message"] and "same network" in out["message"]
    assert out["notice"] == social.LAN_NOTICE


def test_the_lan_notice_states_the_facts():
    text = social.LAN_NOTICE
    assert "MCP" not in text  # MCP is stdio only: the feed server has no MCP endpoint
    for fact in ("plain HTTP", "not HTTPS", "pairing link or QR code",
                 "watch traffic", "excerpts of your code", "network you trust",
                 "public Wi-Fi", "turn off phone access", "server.lan: false",
                 "docs/install.md"):  # fmt: skip
        assert fact in text, fact
    assert len(text) < 800


def test_pairing_link_can_skip_the_browser(cfg, net):
    net.update({("127.0.0.1", 8008), (LAN, 8008)})
    opened = []
    out = social.pairing_link(_lan(cfg), open_browser=False, open_url=opened.append)
    assert opened == [] and out["opened"] is False
    assert [x["address"] for x in out["links"]] == [LAN]  # only addresses that answer


def test_pairing_link_reports_a_browser_that_did_not_open(cfg, net):
    net.update({("127.0.0.1", 8008), (LAN, 8008)})

    def broken(url):
        raise OSError("no browser")

    out = social.pairing_link(_lan(cfg), open_url=broken)
    assert out["opened"] is False and out["links"]
    assert social.pairing_link(_lan(cfg), open_url=lambda url: False)["opened"] is False


def test_pairing_link_sees_a_server_started_with_the_lan_flag(cfg, net):
    """`--lan` is not in the settings: the answer comes from what the server serves."""
    net.update({("127.0.0.1", 8008), (LAN, 8008)})
    out = social.pairing_link(_lan(cfg, False), open_url=lambda url: True)
    assert out["lan"] is True and len(out["links"]) == 1


def test_pairing_link_when_phone_access_is_off(cfg, net):
    net.add(("127.0.0.1", 8008))
    opened = []
    out = social.pairing_link(_lan(cfg, False), open_url=opened.append)
    assert out == {
        "lan": False,
        "links": [],
        "qr_page": "http://127.0.0.1:8008/pairing",
        "opened": False,
        "message": out["message"],
    }
    assert "Phone access is off" in out["message"] and "set_lan" in out["message"]
    assert opened == []
    assert not (cfg.settings.data_dir / "lan_token").exists()  # no token is made for nothing


def test_pairing_link_when_the_setting_is_on_but_the_server_did_not_restart(cfg, net):
    net.add(("127.0.0.1", 8008))
    opened = []
    out = social.pairing_link(_lan(cfg), open_url=opened.append)
    assert out["lan"] is False and out["links"] == [] and opened == []
    assert "start again" in out["message"] and "Reconnect" in out["message"]
    for old in ("launchctl", "LaunchAgent", "gittok install"):
        assert old not in social.LAN_RESTART
    assert "new session" in social.LAN_RESTART and "gittok serve" in social.LAN_RESTART


def test_pairing_link_when_the_server_is_not_running(cfg, net):
    opened = []
    out = social.pairing_link(_lan(cfg), open_url=opened.append)
    assert out["links"] == [] and out["opened"] is False and out["qr_page"] is None
    assert "does not answer" in out["message"] and "8008" in out["message"]
    assert "Reconnect" in out["message"] and "gittok install" not in out["message"]
    assert opened == []


def test_pairing_link_without_a_lan_address(cfg, net, monkeypatch):
    net.add(("127.0.0.1", 8008))
    monkeypatch.setattr(social, "lan_addresses", lambda: [])
    out = social.pairing_link(_lan(cfg), open_url=lambda url: True)
    assert out["links"] == [] and "no LAN address" in out["message"]


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
async def test_pairing_link_tool_opens_the_page_through_the_injected_opener(cfg, net):
    net.update({("127.0.0.1", 8008), (LAN, 8008)})
    opened = []
    lan = _lan(cfg)
    server = mcp_server.build_server(lambda: lan, open_url=opened.append)
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        doc = " ".join(tools["pairing_link"].description.split())
        assert "only to the user" in doc and "never" in doc.lower()
        assert "notice" in doc and "first time" in doc
        for word in ("card", "file", "commit"):
            assert word in doc
        out = data(await client.call_tool("pairing_link", {}))
        assert opened == ["http://127.0.0.1:8008/pairing"] and out["opened"] is True
        assert out["notice"] == social.LAN_NOTICE
        assert out["links"][0]["url"].startswith(f"http://{LAN}:8008/pair?t=")
        out = data(await client.call_tool("pairing_link", {"open_browser": False}))
        assert len(opened) == 1 and out["opened"] is False


@pytestmark_anyio
async def test_set_lan_tool_writes_the_setting_and_says_to_restart(fixture_repo, tmp_path):
    ycfg = make_ycfg(fixture_repo, tmp_path)
    server = mcp_server.build_server(lambda: config_mod.load_config(ycfg.root))
    async with Client(server) as client:
        out = data(await client.call_tool("set_lan", {"enabled": False}))
        assert out["lan"] is False and "Reconnect" in out["restart"]
        assert config_mod.load_config(ycfg.root).settings.server.lan is False
        out = data(await client.call_tool("set_lan", {"enabled": True}))
        assert out["lan"] is True and "pairing_link" in out["restart"]
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
        assert "Cards already made from the repo stay" in doc
        out = data(await client.call_tool("remove_repo", {"name": "beta"}))
        assert out["name"] == "beta" and out["deleted_clone"] is False
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
    for name in ("add_repo", "remove_repo", "set_lan", "pairing_link", "add_rule"):
        assert name in text, name
    assert "gittok-steer" in text and "gittok-generate" in text
    assert "plain HTTP" in text and "local network" in text


# --- prompt-injection defence: who may call a config tool --------------------------------------

CONFIG_TOOLS = {
    "add_repo", "remove_repo", "set_group", "set_mascot", "edit_persona", "set_playback_speed",
    "set_lan", "pairing_link", "add_rule", "remove_rule", "reset_defaults", "save_profile",
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
    for name in ("add_repo", "remove_repo", "set_lan", "pairing_link"):
        assert f"`{name}`" in rule, (path, name)


def test_steer_skill_handles_repo_and_phone_requests():
    text = (ROOT / ".claude/skills/gittok-steer/SKILL.md").read_text()
    head = text.split("---")[1]
    for phrase in ("add a repo", "remove a repo", "phone", "pairing"):
        assert phrase in head, phrase
    for name in ("add_repo", "remove_repo", "set_lan", "pairing_link"):
        assert f"`{name}" in text, name
    assert "plain HTTP" in text and "`notice`" in text
    assert "first sets GitTok up" in text

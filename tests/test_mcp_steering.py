"""Steering tools over the in-process MCP server."""

import pytest
from mcp import Client

from codescroll import config as config_mod
from codescroll import mcp_server
from tests.conftest import make_config
from tests.test_mcp_e2e import data
from tests.test_steering import make_ycfg

pytestmark = pytest.mark.anyio

STEERING_TOOLS = {
    "get_profile",
    "explain_weights",
    "list_rules",
    "add_rule",
    "remove_rule",
    "reset_defaults",
    "add_repo",
    "set_group",
    "set_mascot",
    "edit_persona",
    "recent_cards",
    "card_stats",
    "coverage",
}


@pytest.fixture
def server(fixture_repo, tmp_path):
    cfg = make_config(fixture_repo, tmp_path)
    return mcp_server.build_server(lambda: cfg)


async def test_steering_tools_are_registered_with_examples(server):
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert STEERING_TOOLS <= set(tools)
    for name in STEERING_TOOLS:
        desc = tools[name].description or ""
        assert len(desc) > 30, name
        assert "Example" in desc, name


async def test_add_rule_is_listed_and_created_by_agent(server):
    async with Client(server) as client:
        rule = data(
            await client.call_tool(
                "add_rule",
                {"type": "ban", "feature": "format", "value": "meme", "reason": "no memes"},
            )
        )
        assert rule["created_by"] == "agent"
        assert rule["reason"] == "no memes"
        rules = data(await client.call_tool("list_rules", {}))
        assert [r["id"] for r in rules] == [rule["id"]]


async def test_bad_rule_value_becomes_tool_error(server):
    async with Client(server) as client:
        res = await client.call_tool(
            "add_rule", {"type": "ban", "feature": "format", "value": "nope"}
        )
    assert res.is_error
    assert "Unknown format" in res.content[0].text


async def test_remove_rule(server):
    async with Client(server) as client:
        rule = data(
            await client.call_tool(
                "add_rule", {"type": "boost", "feature": "format", "value": "quiz"}
            )
        )
        gone = data(await client.call_tool("remove_rule", {"rule_id": rule["id"]}))
        assert gone
        assert data(await client.call_tool("list_rules", {})) == []
        missing = await client.call_tool("remove_rule", {"rule_id": 999})
        assert missing.is_error


async def test_read_tools_work_on_an_empty_db(server):
    async with Client(server) as client:
        assert data(await client.call_tool("explain_weights", {})) is not None
        assert data(await client.call_tool("explain_weights", {"feature": "format"})) is not None
        assert data(await client.call_tool("get_profile", {})) is not None
        cov = data(await client.call_tool("coverage", {"repo": "fixture"}))
        assert cov
        assert data(await client.call_tool("recent_cards", {"limit": 5})) == []
        bad = await client.call_tool("card_stats", {"card_id": "nope"})
        assert bad.is_error
        reset = data(await client.call_tool("reset_defaults", {}))
        assert reset == {"deleted": 0}


async def test_add_repo_is_seen_by_the_next_list_repos(fixture_repo, tmp_path):
    ycfg = make_ycfg(fixture_repo, tmp_path)
    server = mcp_server.build_server(lambda: config_mod.load_config(ycfg.root))
    async with Client(server) as client:
        before = {r["name"] for r in data(await client.call_tool("list_repos", {}))}
        assert "delta" not in before
        added = data(
            await client.call_tool(
                "add_repo", {"name": "delta", "path": str(fixture_repo.path), "group": "newbies"}
            )
        )
        assert added["name"] == "delta"
        repos = {r["name"]: r for r in data(await client.call_tool("list_repos", {}))}
        assert repos["delta"]["group"] == "newbies"
        data(await client.call_tool("set_group", {"repo": "delta", "group": "oldies"}))
        repos = {r["name"]: r for r in data(await client.call_tool("list_repos", {}))}
        assert repos["delta"]["group"] == "oldies"
        persona = data(
            await client.call_tool("edit_persona", {"handle": "greybeard", "voice": "Gruff."})
        )
        assert persona["voice"] == "Gruff."
        masc = data(
            await client.call_tool(
                "set_mascot", {"name": "owl", "style": "an owl", "repo": "delta"}
            )
        )
        assert masc["name"] == "owl"
        repos = {r["name"]: r for r in data(await client.call_tool("list_repos", {}))}
        assert repos["delta"]["mascot"] == "owl"


async def test_get_brief_lists_active_rules_and_honors_bans(server):
    async with Client(server) as client:
        await client.call_tool(
            "add_rule",
            {"type": "ban", "feature": "format", "value": "code_card", "reason": "less code"},
        )
        brief = data(await client.call_tool("get_brief", {"count": 10}))
    assert "Rules:" in brief["brief_markdown"]
    assert "less code" in brief["brief_markdown"]
    assert all("code_card" not in pk["formats"] for pk in brief["packets"])


async def test_expired_rules_are_not_in_the_brief(fixture_repo, tmp_path):
    from codescroll import db

    cfg = make_config(fixture_repo, tmp_path)
    server = mcp_server.build_server(lambda: cfg)
    async with Client(server) as client:
        await client.call_tool(
            "add_rule",
            {"type": "ban", "feature": "format", "value": "code_card", "expires": "1h"},
        )
        with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
            conn.execute("UPDATE rules SET expires_at = '2020-01-01T00:00:00Z'")
            conn.commit()
        brief = data(await client.call_tool("get_brief", {"count": 3}))
        assert "Rules:" not in brief["brief_markdown"]
        listed = data(await client.call_tool("list_rules", {"include_expired": True}))
        assert len(listed) == 1


async def test_brief_skips_formats_whose_renderer_is_unavailable(
    fixture_repo, tmp_path, monkeypatch
):
    from codescroll import render

    class Down:
        def available(self):
            return False

    class Up:
        def available(self):
            return True

    monkeypatch.setattr(
        render, "default_renderers", lambda cfg: {"meme": Down(), "illustration": Down()}
    )
    cfg = make_config(fixture_repo, tmp_path)
    server = mcp_server.build_server(lambda: cfg)
    async with Client(server) as client:
        brief = data(await client.call_tool("get_brief", {"count": 20}))
        assert (
            "Skipping meme, mascot_scene, comic: renderer not available" in brief["brief_markdown"]
        )
        used = {f for pk in brief["packets"] for f in pk["formats"]}
        assert not used & {"meme", "mascot_scene", "comic"}

        monkeypatch.setattr(
            render, "default_renderers", lambda cfg: {"meme": Up(), "illustration": Down()}
        )
        brief = data(await client.call_tool("get_brief", {"count": 20}))
        assert "Skipping mascot_scene, comic" in brief["brief_markdown"]
        assert "meme" in {f for pk in brief["packets"] for f in pk["formats"]}

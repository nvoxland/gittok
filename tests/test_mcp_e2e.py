"""Drives the real MCP server in-process, the way a Claude Code session would."""

import json

import pytest
from mcp import Client

from codescroll import mcp_server
from tests.cards import example_card, text_card
from tests.conftest import make_config

pytestmark = pytest.mark.anyio


def data(result):
    assert not result.is_error, result.content
    if result.structured_content is not None:
        sc = result.structured_content
        return sc.get("result", sc) if set(sc) == {"result"} else sc
    return json.loads(result.content[0].text)


async def test_scripted_run_stores_valid_cards_and_reports_rejects(fixture_repo, tmp_path):
    cfg = make_config(fixture_repo, tmp_path)
    server = mcp_server.build_server(lambda: cfg)
    async with Client(server) as client:
        brief = data(await client.call_tool("get_brief", {"count": 3}))
        run_id = brief["run_id"]
        assert "## Packet p1" in brief["brief_markdown"]
        assert "Real people" in brief["guidance_markdown"]
        assert brief["packets"][0]["suggested_model"] in ("haiku", "sonnet")
        # Top-level guidance is the base only; each packet carries its own with its formats.
        assert "Format sections" not in brief["guidance_markdown"]
        for pk in brief["packets"]:
            assert len(pk["formats"]) == pk["count"]
            assert "Real people" in pk["guidance_markdown"]
            for fmt in pk["formats"]:
                assert f"### Format: `{fmt}`" in pk["guidance_markdown"]

        # A subagent researches with the read-only tools...
        shown = await client.call_tool(
            "git_show",
            {"repo": "fixture", "commit": fixture_repo.shas["fix1"], "run_id": run_id},
        )
        assert "fix rounding in invoice" in shown.content[0].text

        # ...and the driver submits what it wrote.
        bad = example_card(fixture_repo)
        bad["visual"]["lines"] = [1, 99]
        cards = [example_card(fixture_repo), text_card(fixture_repo), bad]
        res = data(await client.call_tool("submit_cards", {"run_id": run_id, "cards": cards}))
        assert len(res["accepted"]) == 2
        assert [r["reason"] for r in res["rejected"]] == ["lines_out_of_range"]
        assert res["rejected"][0]["index"] == 2

        summary = data(
            await client.call_tool(
                "finish_run", {"run_id": run_id, "notes": {"models": {"p1": "haiku"}}}
            )
        )
        assert summary["accepted"] == 2
        assert summary["mcp_calls"]["git_show"] == 1
        assert summary["mcp_calls"]["submit_cards"] == 1


def _calls(cfg, run_id):
    from codescroll import db, runs

    with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
        return runs.get_run(conn, run_id)["meta"]["mcp_calls"]


async def test_calls_counted_per_explicit_run_only(fixture_repo, tmp_path):
    cfg = make_config(fixture_repo, tmp_path)
    server = mcp_server.build_server(lambda: cfg)
    sha = fixture_repo.shas["fix1"]
    async with Client(server) as client:
        r1 = data(await client.call_tool("get_brief", {"count": 2}))["run_id"]
        assert _calls(cfg, r1) == {"get_brief": 1}
        r2 = data(await client.call_tool("get_brief", {"count": 2}))["run_id"]
        assert _calls(cfg, r1) == {"get_brief": 1}  # not bumped by the second brief
        assert _calls(cfg, r2) == {"get_brief": 1}
        await client.call_tool("git_show", {"repo": "fixture", "commit": sha})  # no run_id
        await client.call_tool("git_show", {"repo": "fixture", "commit": sha, "run_id": r1})
        await client.call_tool("list_dir", {"repo": "fixture", "run_id": r1})
        assert _calls(cfg, r1) == {"get_brief": 1, "git_show": 1, "list_dir": 1}
        assert _calls(cfg, r2) == {"get_brief": 1}


async def test_bump_failure_does_not_fail_the_tool(fixture_repo, tmp_path, monkeypatch):
    from codescroll import runs

    cfg = make_config(fixture_repo, tmp_path)
    server = mcp_server.build_server(lambda: cfg)

    def boom(*a, **k):
        raise RuntimeError("db locked")

    async with Client(server) as client:
        run_id = data(await client.call_tool("get_brief", {"count": 2}))["run_id"]
        monkeypatch.setattr(runs, "bump_call", boom)
        res = data(
            await client.call_tool(
                "submit_cards", {"run_id": run_id, "cards": [text_card(fixture_repo)]}
            )
        )
        assert len(res["accepted"]) == 1


def _with_repo(cfg, name, path, ref):
    from codescroll.config import Repo

    cfg.repos[name] = Repo(name=name, path=path, ref=ref)


async def test_get_brief_skips_failing_repos(fixture_repo, tmp_path):
    cfg = make_config(fixture_repo, tmp_path)
    _with_repo(cfg, "broken", fixture_repo.path, "no-such-ref")
    server = mcp_server.build_server(lambda: cfg)
    async with Client(server) as client:
        brief = data(await client.call_tool("get_brief", {"count": 3}))
    assert brief["run_id"]
    assert [s["repo"] for s in brief["skipped"]] == ["broken"]
    assert "no-such-ref" in brief["skipped"][0]["error"]
    assert {p["repo"] for p in brief["packets"]} == {"fixture"}


async def test_get_brief_all_repos_failing_is_a_tool_error(fixture_repo, tmp_path):
    cfg = make_config(fixture_repo, tmp_path)
    cfg.repos.clear()
    _with_repo(cfg, "broken", fixture_repo.path, "no-such-ref")
    server = mcp_server.build_server(lambda: cfg)
    async with Client(server) as client:
        res = await client.call_tool("get_brief", {"count": 3})
    assert res.is_error
    assert "broken" in res.content[0].text and "no-such-ref" in res.content[0].text

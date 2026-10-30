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

        # A subagent researches with the read-only tools...
        shown = await client.call_tool(
            "git_show", {"repo": "fixture", "commit": fixture_repo.shas["fix1"]}
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

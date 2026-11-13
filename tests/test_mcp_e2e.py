"""Drives the real MCP server in-process, the way a Claude Code session would."""

import json
from datetime import UTC, datetime

import pytest
from mcp import Client

from gittok import db, ledger, mcp_server
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
        # The driver gets a compact brief: no guidance, no leads, no card-writing text.
        assert "Mix:" in brief["summary_markdown"]
        assert "## Packet" not in brief["summary_markdown"]
        assert "guidance_markdown" not in brief and "brief_markdown" not in brief
        pk0 = brief["packets"][0]
        assert pk0["suggested_model"] in ("haiku", "sonnet")
        assert set(pk0) == {"id", "repo", "count", "suggested_model", "categories", "formats"}

        # Each subagent fetches its own packet (leads, recent stories, evidence), then the
        # guidance for its formats in a second call: one reply with both was over 50 KB, and
        # the harness saved it to a file the writer could not read.
        for pk in brief["packets"]:
            args = {"run_id": run_id, "packet_id": pk["id"]}
            raw = await client.call_tool("get_packet", args)
            got = data(raw)
            assert got["count"] == pk["count"] and len(got["formats"]) == pk["count"]
            assert f"## Packet {pk['id']}" in got["packet_markdown"]
            assert "guidance_markdown" not in got and "leads" not in got  # leads: packet_markdown
            graw = await client.call_tool("get_guidance", args)
            guide = data(graw)["guidance_markdown"]
            assert "Real people" in guide
            for fmt in got["formats"]:
                assert f"### Format: `{fmt}`" in guide
            for reply in (raw, graw):
                assert len(reply.content[0].text) < mcp_server.MAX_REPLY_CHARS

        # It researches with the read-only tools...
        shown = await client.call_tool(
            "git_show",
            {"repo": "fixture", "commit": fixture_repo.shas["fix1"], "run_id": run_id},
        )
        assert "fix rounding in invoice" in shown.content[0].text

        # ...checks its cards without storing them...
        bad = example_card(fixture_repo)
        bad["visual"]["lines"] = [1, 99]
        cards = [example_card(fixture_repo), text_card(fixture_repo), bad]
        chk = data(await client.call_tool("check_cards", {"run_id": run_id, "cards": cards}))
        assert chk["ok"] == [0, 1]
        assert [r["reason"] for r in chk["rejected"]] == ["lines_out_of_range"]

        # ...and submits them itself, naming its packet.
        res = data(
            await client.call_tool(
                "submit_cards", {"run_id": run_id, "cards": cards, "packet_id": pk0["id"]}
            )
        )
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
        assert summary["mcp_calls"]["check_cards"] == 1
        assert summary["mcp_calls"]["get_packet"] == len(brief["packets"])
        assert summary["packets"][pk0["id"]] == {"accepted": 2, "rejected": 1, "submissions": 1}


def _calls(cfg, run_id):
    from gittok import db, runs

    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
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
    from gittok import runs

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
    from gittok.config import Repo

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


async def test_get_brief_uses_learned_mix_when_rewards_exist(fixture_repo, tmp_path):
    from gittok import db, learning

    cfg = make_config(fixture_repo, tmp_path)
    server = mcp_server.build_server(lambda: cfg)
    async with Client(server) as client:
        plain = data(await client.call_tool("get_brief", {"count": 12}))
    assert "Mix: default" in plain["summary_markdown"]

    from gittok import brief

    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        for f in brief.CATEGORY_FORMATS["code"]:
            if f != "code_card":
                m = learning.Model(cfg, learning.load_reward_config(cfg), {}, learning._now(None))
                m0, q0 = m.prior(("format", f))
                conn.execute(
                    "INSERT OR REPLACE INTO model_weights VALUES (?, ?, ?, ?, ?, ?)",
                    ("format", f, m0 + 2, q0 + 12, 50, learning._iso(learning._now(None))),
                )
        for i in range(7):
            conn.execute(
                "INSERT INTO rewards(card_id, reward, computed_at) VALUES (?, 0.5, 'x')",
                (f"c{i}",),
            )
        conn.commit()
    async with Client(server) as client:
        learned = data(await client.call_tool("get_brief", {"count": 12}))
    assert "Mix: learned from 7 rewards" in learned["summary_markdown"]


def test_recent_stories_carry_format_and_template(fixture_repo, tmp_path):
    from types import SimpleNamespace

    from gittok import db, store
    from tests import cards as C

    cfg = make_config(fixture_repo, tmp_path)
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        conn.execute("INSERT INTO runs(id, status, started_at) VALUES ('r1', 'finished', 'x')")
        spec = text_card(fixture_repo)
        store.insert_card(conn, cfg, "r1", SimpleNamespace(card=spec, resolved={}, story_key="k1"))
        conn.commit()
        meme = C.meme_card(fixture_repo)
        store.insert_card(conn, cfg, "r1", SimpleNamespace(card=meme, resolved={}, story_key="k2"))
        conn.commit()
        got = mcp_server.recent_stories(conn)
    assert {r["format"]: r["template"] for r in got}[meme["format"]] == "drake"
    got = [r for r in got if r["format"] == spec["format"]]
    assert got == [
        {
            "story_type": spec["story_type"],
            "hook": spec["hook"],
            "format": spec["format"],
            "template": None,
        }
    ]


async def test_get_brief_without_count_is_noop_when_backlog_is_full(fixture_repo, tmp_path):
    from types import SimpleNamespace

    from gittok import db, store

    cfg = make_config(fixture_repo, tmp_path)
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        conn.execute("INSERT INTO runs(id, status, started_at) VALUES ('r0', 'finished', 'x')")
        for i in range(30):
            acc = SimpleNamespace(card=text_card(fixture_repo), resolved={}, story_key=f"k{i}")
            store.insert_card(conn, cfg, "r0", acc)
        conn.commit()
    server = mcp_server.build_server(lambda: cfg)
    async with Client(server) as client:
        out = data(await client.call_tool("get_brief", {}))
        assert out["nothing_to_do"] is True and out["run_id"] is None
        assert out["health"]["backlog"] == 30 and out["health"]["want"] == 0
        assert data(await client.call_tool("feed_health", {}))["backlog"] == 30
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM runs WHERE id != 'r0'").fetchone()[0] == 0


async def test_explicit_count_still_opens_run(fixture_repo, tmp_path):
    cfg = make_config(fixture_repo, tmp_path)
    server = mcp_server.build_server(lambda: cfg)
    async with Client(server) as client:
        out = data(await client.call_tool("get_brief", {"count": 2}))
        assert out["run_id"] and "nothing_to_do" not in out


async def test_get_packet_attaches_materials(fixture_repo, tmp_path):
    cfg = make_config(fixture_repo, tmp_path, packet_size=2)
    server = mcp_server.build_server(lambda: cfg)
    async with Client(server) as client:
        brief = data(await client.call_tool("get_brief", {"count": 6}))
        run_id = brief["run_id"]
        assert "materials_markdown" not in brief
        seen = []
        for pk in brief["packets"]:
            args = {"run_id": run_id, "packet_id": pk["id"]}
            seen.append(data(await client.call_tool("get_packet", args)))
        assert all(g["lead_refs"] and "leads" not in g for g in seen)
        joined = "\n".join(g["materials_markdown"] for g in seen)
        assert "```diff" in joined or "blob " in joined


async def _lead_ids(client, brief) -> set[int]:
    ids = set()
    for pk in brief["packets"]:
        args = {"run_id": brief["run_id"], "packet_id": pk["id"]}
        got = data(await client.call_tool("get_packet", args))
        ids |= {r["id"] for r in got["lead_refs"] if r.get("id") is not None}
    return ids


async def test_second_brief_on_same_head_skips_covered_leads(fixture_repo, tmp_path):
    cfg = make_config(fixture_repo, tmp_path, packet_size=2)
    server = mcp_server.build_server(lambda: cfg)
    async with Client(server) as client:
        first = data(await client.call_tool("get_brief", {"count": 6}))
        first_ids = await _lead_ids(client, first)
        assert first_ids  # leads come from the ledger and carry its ids
        with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
            marks = ",".join("?" * len(first_ids))
            conn.execute(
                f"UPDATE leads SET times_covered = 1, last_covered_at = ? WHERE id IN ({marks})",
                (ledger.iso(datetime.now(UTC)), *first_ids),
            )
        second = data(await client.call_tool("get_brief", {"count": 6}))
        second_ids = await _lead_ids(client, second)
        assert not first_ids & second_ids


async def test_submit_facts_checks_against_the_head_and_rejects_stale(fixture_repo, tmp_path):
    from gittok import gitq

    cfg = make_config(fixture_repo, tmp_path)
    server = mcp_server.build_server(lambda: cfg)
    head = gitq.rev_parse(fixture_repo.path, "main")
    async with Client(server) as client:
        data(await client.call_tool("get_brief", {"count": 1}))  # analyzes the repo
        good = {"defines": {"path": "src/app.py", "name": "main", "line": 1}}
        bad = {"calls": {"path": "src/app.py", "line": 2, "caller": "main", "callee": "zzz"}}
        args = {"repo": "fixture", "head_sha": head, "tool": "lint 1.0", "facts": [good, bad]}
        got = data(await client.call_tool("submit_facts", args))
        assert got["accepted"] == {"defines": 1} and got["rejected_count"] == 1
        assert "zzz" in got["rejected"][0]["reason"]
        stale = await client.call_tool("submit_facts", {**args, "head_sha": "0" * 40})
        assert stale.is_error and "stale" in stale.content[0].text
        unknown = await client.call_tool("submit_facts", {**args, "repo": "nope"})
        assert unknown.is_error


async def test_get_brief_with_no_repos_returns_a_message_and_opens_no_run(fixture_repo, tmp_path):
    from dataclasses import replace

    cfg = replace(make_config(fixture_repo, tmp_path), repos={})
    server = mcp_server.build_server(lambda: cfg)
    async with Client(server) as client:
        for args in ({}, {"count": 3}):
            out = data(await client.call_tool("get_brief", args))
            assert out["run_id"] is None and out["nothing_to_do"] is True
            assert out["no_repos"] is True
            assert "Ask the user which repo to add" in out["message"]
            assert "add_repo" in out["message"] and "terminal" not in out["message"]
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


async def test_get_packet_starts_with_the_hard_limits(fixture_repo, tmp_path):
    """Writers broke the size limits again and again (excerpt_too_long, too_long): the limits
    were deep in the guidance. Each packet now starts with them, from the validator."""
    from gittok import validator

    cfg = make_config(fixture_repo, tmp_path, packet_size=2)
    async with Client(mcp_server.build_server(lambda: cfg)) as client:
        brief = data(await client.call_tool("get_brief", {"count": 2}))
        pk = brief["packets"][0]
        got = data(
            await client.call_tool("get_packet", {"run_id": brief["run_id"], "packet_id": pk["id"]})
        )
    assert next(iter(got)) == "limits_markdown"
    text = got["limits_markdown"]
    for n in (validator.MAX_HOOK, validator.FRONT_BUDGET, validator.ITEM_COST,
              validator.MAX_FRONT_CODE_LINES, validator.MAX_SPAN):  # fmt: skip
        assert str(n) in text, n
    assert "check_cards" not in text


async def test_writers_get_the_readers_own_guidance_last(fixture_repo, tmp_path):
    cfg = make_config(fixture_repo, tmp_path)
    server = mcp_server.build_server(lambda: cfg)
    async with Client(server) as client:
        brief = data(await client.call_tool("get_brief", {"count": 1}))
        args = {"run_id": brief["run_id"], "packet_id": brief["packets"][0]["id"]}
        plain = data(await client.call_tool("get_guidance", args))["guidance_markdown"]
        (tmp_path / "local").mkdir(exist_ok=True)
        (tmp_path / "local" / "guidance.md").write_text("Never use the word synergy.\n")
        mine = data(await client.call_tool("get_guidance", args))["guidance_markdown"]
    assert "synergy" not in plain and "The reader's own guidance" not in plain
    head, tail = mine.split("## The reader's own guidance")
    assert head.strip() == plain.strip()
    assert "Never use the word synergy." in tail

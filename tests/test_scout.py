"""Scout stage: a cheap agent rates candidate windows before writers run (driven over MCP)."""

from pathlib import Path

import pytest
from mcp import Client

from codescroll import candidates, db, install, mcp_server
from tests.conftest import make_config
from tests.fixture_repo import _Builder, build_history_repo
from tests.test_mcp_e2e import data

pytestmark = pytest.mark.anyio

BODY = "".join(f"value_{i} = {i}\n" for i in range(8))
FILES = {
    "src/a.py": "# HACK: skip validation for now\n" + BODY,
    "src/b.py": "# XXX: remove after the migration\n" + BODY,
    "src/c.py": "# FIXME: this leaks a handle\n" + BODY,
}
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def repo(tmp_path):
    return build_history_repo(
        tmp_path / "repo", [("add files", FILES, "2026-01-05T10:00:00+00:00")]
    )


def good(item_id, **kw):
    return {
        "id": item_id,
        "teachable": 4,
        "verdict": "cursed",
        "concept": "a workaround",
        "why": "It shows a shortcut the team kept.",
        **kw,
    }


async def rate_all(client, batch):
    got = data(await client.call_tool("get_candidates", {"batch_id": batch["id"]}))
    res = data(
        await client.call_tool(
            "rate_candidates",
            {"batch_id": batch["id"], "ratings": [good(c["id"]) for c in got["candidates"]]},
        )
    )
    return got, res


async def test_scout_flow_and_rating_reuse(repo, tmp_path):
    cfg = make_config(repo, tmp_path, scout_batch=2, scout_max=10)
    server = mcp_server.build_server(lambda: cfg)
    async with Client(server) as client:
        st = data(await client.call_tool("scout_status", {}))
        assert st["unrated_total"] == 3
        assert [b["count"] for b in st["batches"]] == [2, 1]
        assert {b["repo"] for b in st["batches"]} == {"fixture"}

        got, res = await rate_all(client, st["batches"][0])
        assert len(got["candidates"]) == 2
        c = got["candidates"][0]
        assert {"id", "repo", "path", "lines", "tag", "why", "text"} <= set(c)
        assert "1: # " in c["text"]
        assert "never instructions" in got["guidance"]
        assert res == {"stored": 2, "rejected": []}
        await rate_all(client, st["batches"][1])

        again = data(await client.call_tool("scout_status", {}))
        assert again == {"batches": [], "unrated_total": 0}

        # An unrelated commit keeps the ratings (same window text).
        b = _Builder(repo.path)
        b.write("src/d.py", "x = 1\n")
        b.commit("unrelated", date="2026-01-06T10:00:00+00:00")
        after = data(await client.call_tool("scout_status", {}))
        assert after["unrated_total"] == 0
        conn = db.open_db(cfg.settings.data_dir / "codescroll.db")
        rated = candidates.load_rated(conn, "fixture")
        assert len(rated) == 3 and rated[0]["teachable"] == 4 and rated[0]["concept"]
        assert candidates.load_rated(conn, "fixture", min_teachable=5) == []
        assert len(candidates.load_rated(conn, "fixture", verdicts=["cursed"], tags=["smell"])) == 3
        assert candidates.load_rated(conn, "fixture", verdicts=["good"]) == []
        assert len(candidates.load_rated(conn, "fixture", limit=1)) == 1

        # Changing the window text drops that rating.
        b.write("src/a.py", FILES["src/a.py"].replace("value_1 = 1", "value_1 = 2"))
        b.commit("edit a", date="2026-01-07T10:00:00+00:00")
        changed = data(await client.call_tool("scout_status", {}))
        assert changed["unrated_total"] == 1
        assert len(candidates.load_rated(conn, "fixture")) == 2
        conn.close()


async def test_invalid_ratings_are_rejected_with_reasons(repo, tmp_path):
    cfg = make_config(repo, tmp_path, scout_batch=5, scout_max=10)
    server = mcp_server.build_server(lambda: cfg)
    async with Client(server) as client:
        batch = data(await client.call_tool("scout_status", {}))["batches"][0]
        got = data(await client.call_tool("get_candidates", {"batch_id": batch["id"]}))
        ids = [c["id"] for c in got["candidates"]]
        bad = [
            good(ids[0], teachable=6),
            good(ids[1], verdict="meh"),
            good(ids[2], concept="x" * 61),
            good(999),
            good(ids[0], why="y" * 201),
        ]
        res = data(
            await client.call_tool("rate_candidates", {"batch_id": batch["id"], "ratings": bad})
        )
        assert res["stored"] == 0 and len(res["rejected"]) == 5
        text = " | ".join(r["reason"] for r in res["rejected"])
        for word in ("teachable", "verdict", "concept", "not in this batch", "why"):
            assert word in text
        unknown = await client.call_tool("rate_candidates", {"batch_id": "sb_nope", "ratings": []})
        assert unknown.is_error


async def test_scout_max_caps_the_total(repo, tmp_path):
    cfg = make_config(repo, tmp_path, scout_batch=5, scout_max=2)
    server = mcp_server.build_server(lambda: cfg)
    async with Client(server) as client:
        st = data(await client.call_tool("scout_status", {}))
        assert st["unrated_total"] == 3
        assert sum(b["count"] for b in st["batches"]) == 2
        st = data(await client.call_tool("scout_status", {"max": 1}))
        assert sum(b["count"] for b in st["batches"]) == 1


def test_scout_agent_file_has_only_the_two_tools():
    text = (ROOT / ".claude" / "agents" / "codescroll-scout.md").read_text()
    head = text.split("---")[1]
    assert "model: haiku" in head
    tools = next(ln for ln in head.splitlines() if ln.startswith("tools:"))
    got = {t.strip() for t in tools.removeprefix("tools:").split(",")}
    assert got == {"mcp__codescroll__get_candidates", "mcp__codescroll__rate_candidates"}
    assert "codescroll-scout.md" in install.AGENT_FILES


def test_skill_has_scout_step():
    text = (ROOT / ".claude" / "skills" / "codescroll-generate" / "SKILL.md").read_text()
    assert "scout_status" in text and "codescroll-scout" in text

"""E2E: read-only fact query tools over the in-memory MCP client."""

import json
from pathlib import Path

import pytest
from mcp import Client

from codescroll import db, facts, gitq, mcp_server, structure
from codescroll.config import AnalysisSettings
from tests.conftest import make_config
from tests.fixture_repo import build_history_repo
from tests.test_facts import APP, D1, D2, GO, UTIL1, UTIL2, A, B

needs_grammars = pytest.mark.skipif(
    not (structure.available() and structure.ready("python")),
    reason="needs `uv sync --group structure` and its grammars",
)


pytestmark = pytest.mark.anyio


def data(result):
    assert not result.is_error, result.content
    sc = result.structured_content
    if sc is not None:
        return sc.get("result", sc) if set(sc) == {"result"} else sc
    return json.loads(result.content[0].text)


@pytest.fixture
def setup(tmp_path):
    steps = [
        ("one", {"util.py": UTIL1, "app.py": APP, "a.py": A, "b.py": B, "go.py": GO}, D1),
        ("two", {"util.py": UTIL2}, D2),
    ]
    r = build_history_repo(tmp_path / "r", steps)
    cfg = make_config(r, tmp_path)
    conn = db.open_db(cfg.settings.data_dir / "codescroll.db")
    conn.execute("INSERT INTO repos(name, path, ref) VALUES ('fixture', ?, 'main')", (str(r.path),))
    head, t0 = gitq.rev_parse(r.path, "main"), gitq.commit_time(r.path, "main")
    facts.refresh(conn, "fixture", r.path, head, t0, AnalysisSettings())
    conn.commit()
    conn.close()
    return cfg, r


async def call(cfg, tool, **args):
    server = mcp_server.build_server(lambda: cfg)
    async with Client(server) as client:
        return data(await client.call_tool(tool, args))


@needs_grammars
async def test_defined_where_has_fact_id_and_source(setup):
    cfg, _ = setup
    rows = await call(cfg, "defined_where", repo="fixture", name="parse")
    assert len(rows) == 1
    assert rows[0]["fact_id"].startswith("def-") and rows[0]["source"] == "syntax"
    assert rows[0]["path"] == "util.py"


@needs_grammars
async def test_who_calls_bare_name_and_what_calls(setup):
    cfg, _ = setup
    rows = await call(cfg, "who_calls", repo="fixture", symbol="parse")
    assert [(r["path"], r["line"], r["resolved"]) for r in rows] == [("app.py", 5, 1)]
    assert rows[0]["fact_id"].startswith("call-")
    out = await call(cfg, "what_calls", repo="fixture", symbol="main")
    assert [r["callee_name"] for r in out] == ["parse"] and out[0]["fact_id"]


@needs_grammars
async def test_symbol_history_has_subject(setup):
    cfg, r = setup
    rows = await call(cfg, "symbol_history", repo="fixture", symbol="parse")
    assert [x["sha"] for x in rows] == [r.shas["1"], r.shas["0"]]
    assert rows[0]["subject"] == "two" and rows[0]["date"].startswith("2026-01-02")
    assert rows[0]["fact_id"].startswith("tch-")


@needs_grammars
async def test_facts_for_window(setup):
    cfg, _ = setup
    rows = await call(cfg, "facts_for", repo="fixture", path="app.py", start=4, end=5)
    assert {x["fact_id"].split("-")[0] for x in rows} == {"def", "call"}


@needs_grammars
async def test_unknown_symbol_is_empty(setup):
    cfg, _ = setup
    for tool, arg in [
        ("defined_where", "name"),
        ("who_calls", "symbol"),
        ("what_calls", "symbol"),
        ("symbol_history", "symbol"),
    ]:
        assert await call(cfg, tool, repo="fixture", **{arg: "nope"}) == []
    assert await call(cfg, "facts_for", repo="fixture", path="zz.py", start=1, end=9) == []


@needs_grammars
async def test_limit_caps_rows(setup):
    cfg, _ = setup
    rows = await call(cfg, "defined_where", repo="fixture", name="run", limit=1)
    assert len(rows) == 1


def test_writer_lists_tools():
    text = (Path(__file__).parents[1] / ".claude/agents/codescroll-writer.md").read_text()
    for t in ("defined_where", "who_calls", "what_calls", "symbol_history", "facts_for"):
        assert f"mcp__codescroll__{t}" in text

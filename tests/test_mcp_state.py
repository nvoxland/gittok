"""Questions about GitTok's state are answered by MCP tools, not by SQLite or the CLI."""

import random
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp import Client

from gittok import config as config_mod
from gittok import db, home, mcp_server, runs, social, steering, store, supply
from tests.cards import text_card
from tests.test_mcp_e2e import data
from tests.test_steering import make_ycfg

pytestmark = pytest.mark.anyio
ROOT = Path(__file__).parents[1]


@pytest.fixture
def ycfg(fixture_repo, tmp_path):
    return make_ycfg(fixture_repo, tmp_path)


def server(ycfg, **kw):
    return mcp_server.build_server(lambda: config_mod.load_config(ycfg.root), **kw)


def add_card(conn, cfg, repos, created_at, run="r1") -> str:
    if not conn.execute("SELECT 1 FROM runs WHERE id = ?", (run,)).fetchone():
        conn.execute(
            "INSERT INTO runs(id, status, started_at) VALUES (?, 'finished', ?)", (run, created_at)
        )
    spec = text_card(SimpleNamespace(shas={"delete_legacy": "abc"}), repos=repos)
    acc = SimpleNamespace(card=spec, resolved={}, story_key=f"k{random.random()}")
    cid = store.insert_card(conn, cfg, run, acc, now=created_at)
    conn.commit()
    return cid


def seed(ycfg) -> dict:
    """alpha: two cards, one seen just now. beta: none."""
    with closing(db.open_db(ycfg.settings.data_dir / "gittok.db")) as conn:
        old = add_card(conn, ycfg, ["alpha"], "2026-05-01T00:00:00Z")
        new = add_card(conn, ycfg, ["alpha"], "2026-05-30T00:00:00Z")
        conn.execute(
            "INSERT INTO events(card_id, type, ts, data, received_at) "
            "VALUES (?, 'impression', ?, '{}', 'x')",
            (old, int(datetime.now(UTC).timestamp() * 1000)),
        )
        conn.commit()
    return {"old": old, "new": new}


async def test_list_repos_counts_cards_per_repo(ycfg):
    seed(ycfg)
    async with Client(server(ycfg)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        repos = {r["name"]: r for r in data(await client.call_tool("list_repos", {}))}
    for word in ("cards", "unseen", "last_card_at", "profiled"):
        assert word in tools["list_repos"].description, word
    a, b = repos["alpha"], repos["beta"]
    assert (a["cards"], a["unseen"], a["last_card_at"]) == (2, 1, "2026-05-30T00:00:00Z")
    assert (b["cards"], b["unseen"], b["last_card_at"]) == (0, 0, None)
    assert a["profiled"] is False and a["group"] == "dev"


def test_repo_card_counts_is_one_query(ycfg):
    seed(ycfg)
    with closing(db.open_db(ycfg.settings.data_dir / "gittok.db")) as conn:
        seen = []
        conn.set_trace_callback(seen.append)
        out = supply.repo_card_counts(conn)
    assert out == {"alpha": {"cards": 2, "last_card_at": "2026-05-30T00:00:00Z"}}
    assert len([s for s in seen if s.lstrip().upper().startswith("SELECT")]) == 1


async def test_feed_health_has_a_per_repo_breakdown(ycfg):
    seed(ycfg)
    async with Client(server(ycfg)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        h = data(await client.call_tool("feed_health", {}))
    assert h["by_repo"] == {"alpha": 1, "beta": 0} and h["backlog"] == 1
    assert "by_repo" in tools["feed_health"].description


async def test_recent_cards_names_the_repo_and_filters_by_it(ycfg):
    ids = seed(ycfg)
    with closing(db.open_db(ycfg.settings.data_dir / "gittok.db")) as conn:
        other = add_card(conn, ycfg, ["beta"], "2026-05-31T00:00:00Z")
    async with Client(server(ycfg)) as client:
        rows = data(await client.call_tool("recent_cards", {}))
        assert [(r["id"], r["repo"], r["group"]) for r in rows] == [
            (other, "beta", "ops"),
            (ids["new"], "alpha", "dev"),
            (ids["old"], "alpha", "dev"),
        ]
        rows = data(await client.call_tool("recent_cards", {"repo": "alpha", "limit": 1}))
        assert [r["id"] for r in rows] == [ids["new"]]
        stats = data(await client.call_tool("card_stats", {"card_id": other}))
        assert (stats["repo"], stats["group"]) == ("beta", "ops")
        bad = await client.call_tool("recent_cards", {"repo": "nope"})
        assert bad.is_error and "unknown repo" in bad.content[0].text.lower()


async def test_recent_runs_gives_counts_and_reject_reasons(ycfg):
    with closing(db.open_db(ycfg.settings.data_dir / "gittok.db")) as conn:
        rid = store.ensure_repo(conn, ycfg.repos["alpha"])
        conn.execute(
            "INSERT INTO runs(id, repo_id, status, requested, accepted, rejected, submissions, "
            "reject_reasons, started_at, finished_at, duration_ms) VALUES "
            "('old', ?, 'finished', 5, 3, 2, 1, ?, '2026-05-01T00:00:00Z', "
            "'2026-05-01T00:10:00Z', 600000)",
            (
                rid,
                db.dumps(
                    [
                        {"reason": "bad_quote", "detail": "secret text of a card"},
                        {"reason": "bad_quote", "detail": "x"},
                    ]
                ),
            ),
        )
        conn.execute(
            "INSERT INTO runs(id, status, requested, started_at) "
            "VALUES ('new', 'open', 8, '2026-05-02T00:00:00Z')"
        )
        conn.commit()
        assert [r["run_id"] for r in runs.recent(conn, limit=1)] == ["new"]
    async with Client(server(ycfg)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        rows = data(await client.call_tool("recent_runs", {"limit": 5}))
    assert "Example" in tools["recent_runs"].description
    assert [r["run_id"] for r in rows] == ["new", "old"]
    assert rows[0]["status"] == "open" and rows[0]["repo"] is None
    old = rows[1]
    assert (old["repo"], old["requested"], old["accepted"], old["rejected"]) == ("alpha", 5, 3, 2)
    assert old["top_reject_reasons"] == [["bad_quote", 2]]
    assert old["started_at"] == "2026-05-01T00:00:00Z" and old["duration_ms"] == 600000
    assert "secret text" not in str(rows)


async def test_status_says_version_directory_and_server(ycfg):
    (ycfg.root / home.MARKER).write_text("version: 0.0.1\nfiles: {}\n")
    asked = []

    def server_dir(port):
        asked.append(port)
        return str(ycfg.root)

    async with Client(server(ycfg, server_dir=server_dir, owns_server=True)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        s = data(await client.call_tool("status", {}))
    assert "Example" in tools["status"].description
    assert s["version"] == home.installed_version()
    assert s["directory"] == str(ycfg.root)
    assert s["directory_version"] == "0.0.1" and s["directory_up_to_date"] is False
    assert "gittok update" in s["update"]
    port = ycfg.settings.server.port
    assert asked == [port]
    assert s["server"] == {
        "port": port,
        "lan": ycfg.settings.server.lan,
        "running": True,
        "serves_this_directory": True,
        "owned_by_this_session": True,
        "urls": social.feed_urls(ycfg),
    }
    assert s["server"]["urls"][0] == f"http://127.0.0.1:{port}"
    assert s["run_open"] is False and s["repos"] == 2
    # Can a mascot be drawn, can a meme: the agent makes no mascot that nobody can draw.
    assert set(s["renderers"]) == {"illustration", "meme"}
    assert all(isinstance(v, bool) for v in s["renderers"].values())

    async with Client(server(ycfg, server_dir=lambda port: None)) as client:
        s = data(await client.call_tool("status", {}))
    assert s["server"]["running"] is False and s["server"]["owned_by_this_session"] is False
    assert s["server"]["serves_this_directory"] is False


def test_the_state_tools_are_named_where_the_agent_looks():
    for text in (
        mcp_server.INSTRUCTIONS,
        (ROOT / ".claude/skills/gittok-steer/SKILL.md").read_text(),
        (ROOT / "src/gittok/templates/AGENTS.md").read_text(),
    ):
        flat = " ".join(text.split())
        for name in ("list_repos", "feed_health", "recent_cards", "recent_runs", "status"):
            assert name in flat, name
        assert "do not read the database" in flat.lower()


def test_no_agent_gets_the_new_state_tools():
    for name in home.AGENT_FILES:
        head = (ROOT / ".claude" / "agents" / name).read_text().split("---")[1]
        assert "recent_runs" not in head and "mcp__gittok__status" not in head
    assert steering  # the module the tools call


async def test_status_renderers_follow_what_can_run(ycfg, monkeypatch):
    class R:
        def __init__(self, ok):
            self.ok = ok

        def available(self):
            return self.ok

    fake = {"meme": R(False), "illustration": R(True)}
    monkeypatch.setattr(mcp_server.render, "default_renderers", lambda cfg: fake)
    async with Client(server(ycfg, server_dir=lambda port: None)) as client:
        s = data(await client.call_tool("status", {}))
        repos = {r["name"]: r for r in data(await client.call_tool("list_repos", {}))}
    assert s["renderers"] == {"illustration": True, "meme": False}
    # list_repos gives the mascot that cards of the repo use: the repo's field, or a mascot
    # whose own `repo` names it.
    assert repos["alpha"]["mascot"] == "crow" and repos["beta"]["mascot"] is None
    steering.set_mascot(config_mod.load_config(ycfg.root), "owl", style="an owl")
    (ycfg.root / "local" / "mascots.yaml").write_text(
        "mascots:\n  owl:\n    repo: beta\n    style: an owl\n"
    )
    async with Client(server(ycfg, server_dir=lambda port: None)) as client:
        repos = {r["name"]: r for r in data(await client.call_tool("list_repos", {}))}
    assert repos["beta"]["mascot"] == "owl"


def test_get_brief_keeps_mascot_formats_from_a_repo_with_no_mascot(ycfg):
    cfg = config_mod.load_config(ycfg.root)
    assert mcp_server.no_mascot_repos(cfg, ["alpha", "beta"]) == frozenset({"beta"})

"""Per-rule outcomes: scout ratings and reader rewards rolled up per detector."""

import pytest

from codescroll import candidate_leads, db, rule_stats
from tests.test_candidate_leads import cand


@pytest.fixture
def conn():
    c = db.open_db(":memory:")
    c.execute("INSERT INTO repos(name, path) VALUES ('r', '/x')")
    c.execute("INSERT INTO runs(id, repo_id, status, started_at) VALUES ('run', 1, 'open', 't')")
    c.commit()
    yield c
    c.close()


def rule_cand(conn, path, start, tag, rule_id, rating=None):
    cand(conn, path, start, tag, rating=rating)
    conn.execute(
        "UPDATE candidates SET rule_id = ? WHERE path = ? AND line_start = ?",
        (rule_id, path, start),
    )
    conn.commit()


def card(conn, cid, path, start, tag, reward=None, events=()):
    key = f"cand:{path}:{start}:{tag}"
    conn.execute(
        "INSERT OR IGNORE INTO leads(repo, story_type, kind, path, lead_key, text, strength, "
        "head_sha, first_seen_at, last_seen_at) VALUES ('r','quiz','path',?,?,'t',1,'h','t','t')",
        (path, key),
    )
    lead = conn.execute("SELECT id FROM leads WHERE lead_key = ?", (key,)).fetchone()[0]
    conn.execute(
        "INSERT INTO cards(id, run_id, repo_id, story_type, format, persona, tone, spec, "
        "story_key, created_at, lead_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (cid, "run", 1, "quiz", "f", "p", "t", "{}", cid, "t", lead),
    )
    if reward is not None:
        conn.execute(
            "INSERT INTO rewards(card_id, reward, computed_at) VALUES (?,?,'2026-05-31T00:00:00Z')",
            (cid, reward),
        )
    for i, kind in enumerate(events):
        conn.execute(
            "INSERT INTO knowledge_events(event_id, ts, card_id, kind) VALUES (?,?,?,?)",
            (abs(hash(cid)) % 100000 + i, i, cid, kind),
        )
    conn.commit()


@pytest.fixture
def two_rules(conn):
    rule_cand(conn, "a.py", 1, "smell", "good", rating=(5, "core"))
    rule_cand(conn, "a.py", 20, "smell", "good", rating=(4, "core"))
    rule_cand(conn, "b.py", 1, "smell", "bad", rating=(1, "bad"))
    rule_cand(conn, "b.py", 20, "smell", "bad")
    cand(conn, "c.py", 1, "core", rating=(3, "core"))
    card(conn, "c1", "a.py", 1, "smell", reward=0.9, events=["knew_it"])
    card(conn, "c2", "a.py", 20, "smell", reward=0.7, events=["teach_more"])
    card(conn, "c3", "b.py", 1, "smell", reward=0.1)
    card(conn, "c4", "c.py", 1, "core", reward=0.5)


def by_rule(conn):
    return {r["rule"]: r for r in rule_stats.rollup(conn, "r")}


def test_rollup_per_rule(conn, two_rules):
    good = by_rule(conn)["good"]
    assert (good["found"], good["rated"], good["mean_teachable"]) == (2, 2, 4.5)
    assert (good["cards"], good["knew_it"], good["teach_more"]) == (2, 1, 1)
    assert good["mean_reward"] == pytest.approx(0.8)
    bad = by_rule(conn)["bad"]
    assert (bad["found"], bad["rated"], bad["mean_teachable"], bad["cards"]) == (2, 1, 1.0, 1)
    assert bad["mean_reward"] == pytest.approx(0.1)


def test_builtin_pseudo_rules_appear(conn, two_rules):
    row = by_rule(conn)["builtin:core"]
    assert (row["found"], row["cards"], row["mean_teachable"]) == (1, 1, 3.0)


def test_rows_sorted_by_usefulness(conn, two_rules):
    names = [r["rule"] for r in rule_stats.rollup(conn, "r")]
    assert names[0] == "good"
    assert names.index("good") < names.index("bad")


def test_factor_moves_within_bounds(conn, two_rules):
    f = rule_stats.factors(conn, "r")
    assert f["good"] > 1.0 > f["bad"]
    assert all(0.5 <= v <= 1.5 for v in f.values())


def test_factor_clamped(conn):
    for i in range(60):
        rule_cand(conn, "x.py", i * 20 + 1, "smell", "great", rating=(5, "core"))
        rule_cand(conn, "y.py", i * 20 + 1, "smell", "awful", rating=(1, "bad"))
    f = rule_stats.factors(conn, "r")
    assert f["great"] == pytest.approx(1.5, abs=0.25)
    assert f["great"] <= 1.5
    assert 0.5 <= f["awful"] < 0.8


def test_rule_without_data_keeps_weight(conn):
    rule_cand(conn, "n.py", 1, "smell", "new")
    assert rule_stats.factors(conn, "r")["new"] == 1.0
    assert rule_stats.effective_weight(1.7, {}, "new") == 1.7


def test_effective_weight(conn, two_rules):
    f = rule_stats.factors(conn, "r")
    assert rule_stats.effective_weight(2.0, f, "good") == pytest.approx(2.0 * f["good"])


def test_lead_strength_uses_factor(conn, monkeypatch):
    rule_cand(conn, "a.py", 1, "smell", "good", rating=(5, "core"))
    rule_cand(conn, "b.py", 1, "smell", "bad", rating=(5, "core"))
    monkeypatch.setattr(rule_stats, "factors", lambda c, r: {"good": 1.5, "bad": 0.5})
    out = {ld.path: s for ld, s in candidate_leads.leads_for(conn, "r", "quiz", {}, None, 10)}
    assert out["a.py"] == pytest.approx(1.5)
    assert out["b.py"] == pytest.approx(0.5)


@pytest.mark.anyio
async def test_mcp_tool_returns_rows(fixture_repo, tmp_path):
    from mcp import Client

    from codescroll import mcp_server
    from tests.conftest import make_config
    from tests.test_mcp_e2e import data

    cfg = make_config(fixture_repo, tmp_path)
    c = db.open_db(cfg.settings.data_dir / "codescroll.db")
    cand(c, "a.py", 1, "smell", rating=(5, "core"), repo="fixture")
    c.execute("UPDATE candidates SET rule_id = 'good'")
    c.commit()
    c.close()
    server = mcp_server.build_server(lambda: cfg)
    async with Client(server) as client:
        rows = data(await client.call_tool("rule_stats", {"repo": "fixture"}))
        assert [r["rule"] for r in rows] == ["good"]
        assert rows[0]["mean_teachable"] == 5.0
        bad = await client.call_tool("rule_stats", {"repo": "nope"})
        assert bad.is_error


def test_get_profile_has_rule_outcomes(conn, two_rules, tmp_path):
    from types import SimpleNamespace

    from codescroll import steering

    cfg = SimpleNamespace(
        root=tmp_path,
        repos={"r": None},
        settings=SimpleNamespace(user=SimpleNamespace(git_identities=[])),
    )
    prof = steering.get_profile(conn, cfg)
    assert prof["rule_outcomes"]["r"][0]["rule"] == "good"

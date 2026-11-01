from datetime import UTC, datetime, timedelta

import pytest

from codescroll import db, ledger
from tests.conftest import make_config

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def sig(*paths):
    files = [{"path": p, "commits": 9 - i, "lines": 90 - i} for i, p in enumerate(paths)]
    return {"churn": {"files": {"90": files}}}


BLOBS = {"src/a.py": "a" * 40, "lib/b.py": "b" * 40, "docs/c.py": "c" * 40}


@pytest.fixture
def conn():
    c = db.open_db(":memory:")
    yield c
    c.close()


@pytest.fixture
def cfg(fixture_repo, tmp_path):
    return make_config(fixture_repo, tmp_path)


def refresh(conn, s, now=NOW, head="h1", blobs=BLOBS, repo="r"):
    return ledger.refresh(conn, repo, s, 0, head, blobs, now)


def rows(conn, path=None):
    sql = "SELECT * FROM leads WHERE story_type = 'hot_spot'"
    args = []
    if path:
        sql += " AND path = ?"
        args.append(path)
    return conn.execute(sql + " ORDER BY id", args).fetchall()


def test_refresh_upserts_leads_and_new_blob_is_new_row(conn):
    refresh(conn, sig("src/a.py", "lib/b.py"))
    a, b = rows(conn)
    assert (a["path"], a["kind"], a["blob_sha"]) == ("src/a.py", "path", "a" * 40)
    assert a["strength"] == 1.0 and b["strength"] == 0.5
    assert a["head_sha"] == "h1" and a["first_seen_at"] == a["last_seen_at"]

    later = NOW + timedelta(days=1)
    refresh(conn, sig("src/a.py", "lib/b.py"), now=later, head="h2")
    assert len(rows(conn)) == 2  # same identity: updated in place
    a = rows(conn, "src/a.py")[0]
    assert (a["head_sha"], a["last_seen_at"]) == ("h2", ledger.iso(later))
    assert a["first_seen_at"] == ledger.iso(NOW)

    changed = {**BLOBS, "src/a.py": "d" * 40}
    last = later + timedelta(days=1)
    refresh(conn, sig("src/a.py", "lib/b.py"), now=last, head="h3", blobs=changed)
    old, new = rows(conn, "src/a.py")
    assert (old["blob_sha"], new["blob_sha"]) == ("a" * 40, "d" * 40)
    assert old["last_seen_at"] == ledger.iso(later)  # the old row stays, no longer current


def test_refresh_skips_kind_none_leads(conn):
    refresh(conn, {"churn": {"dirs": {"90": [{"path": "src", "commits": 5}]}}})
    assert conn.execute("SELECT COUNT(*) FROM leads WHERE kind = 'none'").fetchone()[0] == 0


def seed_dir_interest(conn, **means):
    for d, m in means.items():
        conn.execute(
            "INSERT INTO weights(feature, value, alpha, beta, updated_at) "
            "VALUES ('dir', ?, ?, ?, ?)",
            (d, m * 100, (1 - m) * 100, ledger.iso(NOW)),
        )


def test_ranked_prefers_interesting_uncovered_leads(conn, cfg):
    refresh(conn, sig("src/a.py", "lib/b.py", "docs/c.py"))
    ids = {r["path"]: r["id"] for r in rows(conn)}
    # src ranks first by strength, but lib is loved and src is not; docs is unknown (0.5).
    seed_dir_interest(conn, lib=0.9, src=0.2)
    order = [x.path for x in ledger.ranked(conn, cfg, "r", "hot_spot", NOW, 10)]
    assert order == ["lib/b.py", "src/a.py", "docs/c.py"]  # scores 0.45, 0.2, 0.17
    # covering lib twice quarters its score: it drops to the bottom but stays offered
    conn.execute("UPDATE leads SET times_covered = 2 WHERE id = ?", (ids["lib/b.py"],))
    got = ledger.ranked(conn, cfg, "r", "hot_spot", NOW, 10)
    assert [x.path for x in got] == ["src/a.py", "docs/c.py", "lib/b.py"]
    assert got[2].id == ids["lib/b.py"]


def test_covered_lead_in_cooldown_is_skipped(conn, cfg):
    refresh(conn, sig("src/a.py", "lib/b.py"))
    conn.execute(
        "UPDATE leads SET times_covered = 2, last_covered_at = ? WHERE path = 'src/a.py'",
        (ledger.iso(NOW - timedelta(days=5)),),
    )
    assert [x.path for x in ledger.ranked(conn, cfg, "r", "hot_spot", NOW, 10)] == ["lib/b.py"]
    after = NOW + timedelta(days=cfg.settings.agent.lead_cooldown_days + 1)
    got = [x.path for x in ledger.ranked(conn, cfg, "r", "hot_spot", after, 10)]
    assert got == ["lib/b.py", "src/a.py"]  # cooled down, but the cover penalty ranks it last


def test_leads_gone_from_head_are_not_offered(conn, cfg):
    refresh(conn, sig("src/a.py", "lib/b.py"))
    refresh(conn, sig("lib/b.py"), now=NOW + timedelta(days=1), head="h2")
    got = ledger.ranked(conn, cfg, "r", "hot_spot", NOW + timedelta(days=1), 10)
    assert [x.path for x in got] == ["lib/b.py"]


def test_ranked_respects_limit_and_repo(conn, cfg):
    refresh(conn, sig("src/a.py", "lib/b.py"))
    refresh(conn, sig("docs/c.py"), repo="other")
    assert len(ledger.ranked(conn, cfg, "r", "hot_spot", NOW, 1)) == 1
    assert [x.path for x in ledger.ranked(conn, cfg, "other", "hot_spot", NOW, 9)] == ["docs/c.py"]


def lead(**kw):
    return {"story_type": "hot_spot", "repo": "r", "kind": "path", **kw}


def card(commits=(), paths=()):
    return {
        "sources": [{"repo": "r", "commit": c} for c in commits]
        + [{"repo": "r", "path": p} for p in paths],
        "visual": {"kind": "text"},
        "depth": [],
    }


def test_match_lead_by_commit_then_path():
    refs = [lead(path="x.py", id=1), lead(kind="commit", commit="c" * 40, id=2)]
    assert ledger.match_lead(card(commits=["c" * 40], paths=["x.py"]), refs)["id"] == 2
    assert ledger.match_lead(card(paths=["x.py"]), refs)["id"] == 1
    assert ledger.match_lead(card(paths=["other.py"]), refs) is None


def test_match_lead_accepts_short_sha_and_visual_and_depth():
    full = "abcdef1234567890" + "0" * 24
    refs = [lead(kind="commit", commit=full, id=7)]
    short = {"sources": [], "visual": {"kind": "code", "commit": "abcdef1"}, "depth": []}
    assert ledger.match_lead(short, refs)["id"] == 7
    deep = {
        "sources": [],
        "visual": {"kind": "text"},
        "depth": [{"kind": "code_diff", "commit": full, "path": "z"}],
    }
    assert ledger.match_lead(deep, refs)["id"] == 7
    assert ledger.match_lead(card(commits=["abcdef2"]), refs) is None


def test_match_lead_ignores_leads_without_ids():
    refs = [lead(kind="none", text="dir x"), lead(path="x.py")]
    assert ledger.match_lead(card(paths=["x.py"]), refs) is None


def test_for_brief_includes_only_types_with_current_rows(conn, cfg):
    refresh(conn, sig("src/a.py"))
    got = ledger.for_brief(conn, cfg, ["r", "nope"], NOW)
    assert [x.path for x in got[("r", "hot_spot")]] == ["src/a.py"]
    assert ("r", "commit_drama") not in got and not any(k[0] == "nope" for k in got)
    conn.execute("UPDATE leads SET last_covered_at = ?", (ledger.iso(NOW),))
    assert ledger.for_brief(conn, cfg, ["r"], NOW)[("r", "hot_spot")] == []  # exhausted, not absent


def iso_days(days):
    return ledger.iso(NOW - timedelta(days=days))


def test_variants_lists_good_old_stories_best_first_with_newest_hook(conn, cfg):
    conn.execute("INSERT INTO repos(name, path) VALUES ('r', '/r')")
    conn.execute("INSERT INTO runs(id, status, started_at) VALUES ('r1','finished','t')")
    old = iso_days(40)
    src = '[{"repo": "r", "commit": "abc"}]'
    for key, reward, liked, last in (
        ("good", 0.7, 0, old),
        ("best", 0.9, 0, old),
        ("liked", None, 1, old),
        ("weak", 0.2, 0, old),
        ("recent", 0.9, 0, iso_days(3)),
    ):
        conn.execute(
            "INSERT INTO stories(story_key, repo, story_type, sources, first_card_at,"
            " last_card_at, best_reward, liked, formats) VALUES"
            " (?, 'r', 'hot_spot', ?, ?, ?, ?, ?, '[\"meme\"]')",
            (key, src, old, last, reward, liked),
        )
    conn.execute(
        "INSERT INTO cards(id, run_id, repo_id, story_type, format, persona, tone, spec,"
        " story_key, created_at) VALUES ('c1','r1',1,'hot_spot','meme','p','t',"
        "'{\"hook\": \"Hot file\"}','best',?)",
        (old,),
    )
    got = ledger.variants(conn, cfg, NOW)
    assert [v["story_key"] for v in got] == ["liked", "best", "good"]
    best = got[1]
    assert best["hook"] == "Hot file" and best["formats_used"] == ["meme"]
    assert (best["repo"], best["story_type"]) == ("r", "hot_spot")
    assert best["sources"] == [{"repo": "r", "commit": "abc"}] and best["best_reward"] == 0.9
    assert got[0]["hook"] is None  # its card was deleted by gc: story type and sources only

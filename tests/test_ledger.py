from datetime import UTC, datetime, timedelta

import pytest

from gittok import db, ledger
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


def test_refresh_upserts_leads_and_edited_file_keeps_its_row(conn, cfg):
    refresh(conn, sig("src/a.py", "lib/b.py"))
    a, b = rows(conn)
    assert (a["path"], a["kind"], a["blob_sha"]) == ("src/a.py", "path", "a" * 40)
    assert a["lead_key"] == "p:src/a.py"
    assert a["strength"] == 1.0 and b["strength"] == 0.5
    assert a["head_sha"] == "h1" and a["first_seen_at"] == a["last_seen_at"]

    later = NOW + timedelta(days=1)
    refresh(conn, sig("src/a.py", "lib/b.py"), now=later, head="h2")
    assert len(rows(conn)) == 2  # same identity: updated in place
    a = rows(conn, "src/a.py")[0]
    assert (a["head_sha"], a["last_seen_at"]) == ("h2", ledger.iso(later))
    assert a["first_seen_at"] == ledger.iso(NOW)

    ledger.mark_covered(conn, a["id"], later)
    changed = {**BLOBS, "src/a.py": "d" * 40}
    last = later + timedelta(days=1)
    refresh(conn, sig("src/a.py", "lib/b.py"), now=last, head="h3", blobs=changed)
    (a,) = rows(conn, "src/a.py")  # an edit does not make a fresh lead
    assert a["blob_sha"] == "d" * 40 and a["id"] == rows(conn)[0]["id"]
    assert (a["times_covered"], a["last_covered_at"]) == (1, ledger.iso(later))
    got = ledger.ranked(conn, cfg, "r", "hot_spot", last, 10)
    assert [x.path for x in got] == ["lib/b.py"]  # still in its cooldown


def test_refresh_stores_kind_none_leads_with_synthetic_keys(conn):
    refresh(conn, {"churn": {"dirs": {"90": [{"path": "src", "commits": 5}]}}})
    (r,) = conn.execute("SELECT * FROM leads WHERE kind = 'none'").fetchall()
    assert (r["lead_key"], r["path"], r["commit_sha"]) == ("dir:src", "", "")
    pair = {"co_change": [{"a": "x.py", "b": "y.py", "count": 3, "jaccard": 0.5}]}
    ledger.refresh(conn, "r", pair, 0, "h1", {}, NOW)
    keys = {
        x[0] for x in conn.execute("SELECT lead_key FROM leads WHERE story_type = 'secret_couples'")
    }
    assert keys == {"pair:x.py|y.py"}


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
    seed_dir_interest(conn, lib=1.0, src=0.0)
    order = [x.path for x in ledger.ranked(conn, cfg, "r", "hot_spot", NOW, 10)]
    # scores 0.75, 0.5, 0.33: interest is only a mild factor (0.5 + interest)
    assert order == ["lib/b.py", "src/a.py", "docs/c.py"]
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


# --- story blocks and cooldown share one clock ---------------------------------------


def add_story(conn, key, stype, sources, reward=None, liked=0, formats=("meme",), age=3):
    conn.execute(
        "INSERT INTO stories(story_key, repo, story_type, sources, first_card_at, last_card_at,"
        " best_reward, liked, formats) VALUES (?, 'r', ?, ?, ?, ?, ?, ?, ?)",
        (
            key,
            stype,
            db.dumps(sources),
            iso_days(age),
            iso_days(age),
            reward,
            liked,
            db.dumps(list(formats)),
        ),
    )


def test_for_brief_drops_leads_whose_story_is_blocked(conn, cfg):
    refresh(conn, sig("src/a.py", "lib/b.py", "docs/c.py"))
    add_story(
        conn, "k1", "hot_spot", [{"repo": "r", "path": "src/a.py", "lines": [1, 4]}], reward=0.1
    )
    add_story(conn, "k2", "hot_spot", [{"repo": "r", "path": "lib/b.py"}], reward=0.9, age=40)
    got = [x.path for x in ledger.for_brief(conn, cfg, ["r"], NOW)[("r", "hot_spot")]]
    assert got == ["lib/b.py", "docs/c.py"]  # a.py: weak story is blocked; b.py: may be retold


def test_blocked_story_outlasts_the_cooldown(conn, cfg):
    refresh(conn, sig("src/a.py"))
    add_story(conn, "k1", "hot_spot", [{"repo": "r", "path": "src/a.py"}], reward=0.1, age=60)
    conn.execute("UPDATE leads SET last_covered_at = ?", (iso_days(45),))  # cooldown is over
    assert ledger.for_brief(conn, cfg, ["r"], NOW)[("r", "hot_spot")] == []


def test_commit_lead_blocked_by_story_with_that_commit(conn, cfg):
    sha = "ab" * 20
    s = {"reverts": [{"sha": sha, "ts": 1, "author": "x", "reverted_sha": "cd" * 20}]}
    refresh(conn, s)
    ledger.refresh(conn, "r", s, 0, "h1", {}, NOW)
    add_story(conn, "k1", "commit_drama", [{"repo": "r", "commit": sha[:10]}], reward=0.0)
    assert ledger.for_brief(conn, cfg, ["r"], NOW)[("r", "commit_drama")] == []


def test_dir_lead_gets_cooldown(conn, cfg):
    s = {"author_shares": {"by_dir": {"src": [{"author": "a", "share": 0.9}]}}}
    ledger.refresh(conn, "r", s, 0, "h1", {}, NOW)
    (lead,) = ledger.for_brief(conn, cfg, ["r"], NOW)[("r", "whose_code")]
    assert lead.key == "dir:src" and lead.kind == "none"
    ledger.mark_covered(conn, lead.id, NOW)
    assert ledger.for_brief(conn, cfg, ["r"], NOW + timedelta(days=2))[("r", "whose_code")] == []
    again = ledger.for_brief(conn, cfg, ["r"], NOW + timedelta(days=31))[("r", "whose_code")]
    assert [x.key for x in again] == ["dir:src"]


def test_offerable_covers_leads_computed_without_a_ledger(conn, cfg):
    s = {"author_shares": {"by_dir": {"src": [{"author": "a", "share": 0.9}]}}}
    ledger.refresh(conn, "r", s, 0, "h1", {}, NOW)
    ok = ledger.offerable(conn, cfg, NOW)
    from gittok import brief

    (lead,) = brief.lead_refs_for("whose_code", s, 0, 5, repo="r")
    assert ok(lead)
    conn.execute("UPDATE leads SET last_covered_at = ?", (iso_days(2),))
    assert not ledger.offerable(conn, cfg, NOW)(lead)
    path_lead = brief.Lead("hot_spot", "r", "path", path="q.py", text="t")
    add_story(conn, "k", "hot_spot", [{"repo": "r", "path": "q.py"}], reward=0.0)
    assert not ledger.offerable(conn, cfg, NOW)(path_lead)


def test_match_lead_requires_same_story_type_and_matches_dirs_and_other_line_ranges():
    refs = [lead(path="x.py", id=1, key="p:x.py", lines=[3, 9])]
    other_lines = {**card(paths=["x.py"]), "story_type": "hot_spot"}
    other_lines["sources"][0]["lines"] = [40, 50]
    assert ledger.match_lead(other_lines, refs)["id"] == 1
    assert ledger.match_lead({**card(paths=["x.py"]), "story_type": "rip"}, refs) is None
    d = [lead(kind="none", id=5, key="dir:src", story_type="whose_code")]
    hit = {**card(), "story_type": "whose_code", "dirs": ["src"]}
    assert ledger.match_lead(hit, d)["id"] == 5
    assert ledger.match_lead({**hit, "dirs": ["lib"]}, d) is None


def test_rekey_migration_merges_path_rows_that_differ_by_blob():
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    files = db._migration_files()
    last = next(f for f in files if f.name.startswith("0013"))
    for f in files:
        if f.name < last.name:
            conn.executescript(f.read_text(encoding="utf-8"))

    def ins(blob, seen, cov, at, reward=None, n=0, path="a.py", kind="path", sha=""):
        return conn.execute(
            "INSERT INTO leads(repo, story_type, kind, path, commit_sha, blob_sha, text, strength,"
            " head_sha, first_seen_at, last_seen_at, times_covered, last_covered_at, mean_reward,"
            " rewards_n) VALUES ('r', 'hot_spot', ?, ?, ?, ?, ?, 1.0, 'h', ?, ?, ?, ?, ?, ?)",
            (kind, path, sha, blob, f"t{blob}", seen, seen, cov, at, reward, n),
        ).lastrowid

    old = ins("b1", "2026-01-01", 2, "2026-02-01", 0.2, 1)
    new = ins("b2", "2026-03-01", 1, "2026-01-15", 0.8, 3)
    other = ins("b1", "2026-03-01", 0, None, path="z.py")
    commit = ins("", "2026-03-01", 1, "2026-03-02", kind="commit", sha="c" * 40, path="")
    conn.execute("INSERT INTO runs(id, status, started_at) VALUES ('r1','finished','t')")
    conn.execute("INSERT INTO repos(name, path) VALUES ('r', '/r')")
    conn.execute(
        "INSERT INTO cards(id, run_id, repo_id, story_type, format, persona, tone, spec,"
        " story_key, created_at, lead_id) VALUES ('c1','r1',1,'hot_spot','meme','p','t','{}',"
        "'k','t',?)",
        (old,),
    )
    conn.executescript(last.read_text(encoding="utf-8"))
    got = conn.execute("SELECT * FROM leads WHERE path = 'a.py'").fetchall()
    assert len(got) == 1
    (m,) = got
    assert m["id"] == new and m["lead_key"] == "p:a.py" and m["blob_sha"] == "b2"
    assert (m["times_covered"], m["last_covered_at"]) == (3, "2026-02-01")
    assert m["first_seen_at"] == "2026-01-01" and m["rewards_n"] == 4
    assert m["mean_reward"] == pytest.approx((0.2 * 1 + 0.8 * 3) / 4)
    assert conn.execute("SELECT lead_id FROM cards").fetchone()[0] == new
    assert (
        conn.execute("SELECT lead_key FROM leads WHERE id = ?", (other,)).fetchone()[0] == "p:z.py"
    )
    assert conn.execute("SELECT lead_key FROM leads WHERE id = ?", (commit,)).fetchone()[0] == (
        "c:" + "c" * 40 + ":"
    )

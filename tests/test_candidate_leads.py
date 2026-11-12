"""Understanding and interactive leads come from rated candidates, not the churn fallback."""

from datetime import timedelta

import pytest

from gittok import brief, db, ledger
from tests.conftest import make_config
from tests.test_brief import DEFAULTS, build, signals
from tests.test_ledger import NOW, refresh

NINE = (
    "what_it_does",
    "journey",
    "analogy",
    "snippet_callouts",
    "cursed_clever_line",
    "quiz",
    "this_or_that",
    "guess_who",
    "guess_when",
)


@pytest.fixture
def conn():
    c = db.open_db(":memory:")
    yield c
    c.close()


@pytest.fixture
def cfg(fixture_repo, tmp_path):
    return make_config(fixture_repo, tmp_path)


def cand(conn, path, start, tag, why="a thing", rating=None, score=1.0, repo="r"):
    """Store a candidate; `rating` is (teachable, verdict) or None for unrated."""
    h = f"hash-{path}-{start}"
    conn.execute(
        "INSERT INTO candidates(repo, path, line_start, line_end, tag, why, score, head_sha, "
        "first_seen_at, last_seen_at, window_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (repo, path, start, start + 9, tag, why, score, "h1", "t", "t", h),
    )
    if rating:
        conn.execute(
            "INSERT INTO candidate_ratings(repo, path, line_start, tag, window_hash, teachable, "
            "verdict, concept, why, rated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (repo, path, start, tag, h, rating[0], rating[1], "an idea", "worth a card", "t"),
        )
    conn.commit()


def lead_rows(conn, story_type):
    return conn.execute(
        "SELECT * FROM leads WHERE story_type = ? AND lead_key LIKE 'cand:%' ORDER BY id",
        (story_type,),
    ).fetchall()


def paths(conn, story_type):
    return {r["path"] for r in lead_rows(conn, story_type)}


def test_refresh_stores_candidate_leads_with_key_lines_and_scout_text(conn):
    cand(conn, "src/a.py", 20, "smell", "HACK marker", (5, "cursed"))
    refresh(conn, {})
    (row,) = lead_rows(conn, "cursed_clever_line")
    assert row["lead_key"] == "cand:src/a.py:20:smell"
    assert (row["kind"], row["path"], row["lines"]) == ("path", "src/a.py", "[20,29]")
    assert "[cursed]" in row["text"] and "HACK marker" in row["text"]
    assert "(src/a.py:20)" in row["text"] and "an idea" in row["text"]
    assert "teachable 5" in row["text"]


def test_rated_five_outranks_rated_two(conn, cfg):
    cand(conn, "src/low.py", 1, "clever", rating=(2, "clever"))
    cand(conn, "lib/high.py", 1, "clever", rating=(5, "clever"))
    refresh(conn, {})
    got = [x.path for x in ledger.ranked(conn, cfg, "r", "cursed_clever_line", NOW, 10)]
    assert got == ["lib/high.py", "src/low.py"]


def test_candidate_lead_is_a_path_lead_with_its_window(conn, cfg):
    cand(conn, "src/a.py", 20, "core", rating=(4, "core"))
    refresh(conn, {})
    (ld,) = ledger.ranked(conn, cfg, "r", "what_it_does", NOW, 10)
    assert (ld.kind, ld.path, ld.lines) == ("path", "src/a.py", (20, 29))
    assert ld.key == "cand:src/a.py:20:core" and ld.id is not None


def test_unrated_only_when_no_rated_and_at_a_discount(conn, cfg):
    cand(conn, "src/u.py", 1, "core")
    refresh(conn, {})
    (u,) = lead_rows(conn, "what_it_does")
    assert u["strength"] <= 0.15 and "unrated" in u["text"]
    cand(conn, "src/r.py", 1, "core", rating=(3, "core"))
    later = NOW + timedelta(days=1)
    refresh(conn, {}, now=later, head="h2")
    got = [x.path for x in ledger.ranked(conn, cfg, "r", "what_it_does", later, 9)]
    assert got == ["src/r.py"]


def test_tag_and_verdict_decide_the_story_type(conn):
    cand(conn, "src/a.py", 1, "entry_point", rating=(4, "core"))
    cand(conn, "src/b.py", 1, "magic_number", rating=(4, "cursed"))
    cand(conn, "src/c.py", 1, "long_function", rating=(5, "good"))
    cand(conn, "src/d.py", 1, "long_function", rating=(2, "good"))
    refresh(conn, {})
    assert paths(conn, "journey") == {"src/a.py", "src/c.py", "src/d.py"}
    assert paths(conn, "cursed_clever_line") == {"src/b.py"}
    assert paths(conn, "quiz") == {"src/a.py", "src/b.py", "src/c.py"}  # teachable >= 4 only
    assert paths(conn, "snippet_callouts") == {"src/a.py", "src/b.py", "src/c.py"}


def test_guess_who_needs_two_clear_authors_in_the_top_dir(conn):
    cand(conn, "src/a.py", 1, "core", rating=(4, "core"))
    cand(conn, "lib/b.py", 1, "core", rating=(4, "core"))
    authors = {
        "src": [{"author": "A", "share": 0.6}, {"author": "B", "share": 0.4}],
        "lib": [{"author": "A", "share": 0.95}, {"author": "B", "share": 0.05}],
    }
    refresh(conn, {"author_shares": {"by_dir": authors}})
    assert paths(conn, "guess_who") == {"src/a.py"}


def test_guess_when_takes_stable_core_or_old_windows(conn):
    cand(conn, "src/a.py", 1, "stable_core", rating=(3, "good"))
    cand(conn, "src/b.py", 1, "long_function", rating=(3, "good"))
    cand(conn, "src/c.py", 1, "long_function", rating=(3, "good"))
    old = [{"path": "src/b.py", "line": 3, "ts": 100, "author": "A", "sha": "s", "text": "x"}]
    ledger.refresh(conn, "r", {"oldest_lines": old}, 10**9, "h1", {}, NOW)
    assert paths(conn, "guess_when") == {"src/a.py", "src/b.py"}


def test_candidate_leads_keep_cooldown(conn, cfg):
    cand(conn, "src/a.py", 1, "core", rating=(4, "core"))
    cand(conn, "src/b.py", 1, "core", rating=(4, "core"))
    refresh(conn, {})
    (a,) = ledger.ranked(conn, cfg, "r", "what_it_does", NOW, 1)
    ledger.mark_covered(conn, a.id, NOW)
    left = [x.path for x in ledger.ranked(conn, cfg, "r", "what_it_does", NOW, 5)]
    assert a.path not in left and len(left) == 1
    assert not ledger.offerable(conn, cfg, NOW)(a)


def test_for_brief_refreshes_candidate_leads_when_ratings_arrive_later(conn, cfg):
    cand(conn, "src/a.py", 1, "core")
    refresh(conn, {"churn": {"files": {"90": [{"path": "src/x.py", "commits": 3, "lines": 9}]}}})
    conn.execute(
        "INSERT INTO candidate_ratings(repo, path, line_start, tag, window_hash, teachable, "
        "verdict, concept, why, rated_at) VALUES ('r','src/a.py',1,'core','hash-src/a.py-1',"
        "5,'core','c','w','t')"
    )
    conn.commit()
    analyses = {"r": {"signals": {}, "t0": 0, "head_sha": "h1"}}
    got = ledger.for_brief(conn, cfg, ["r"], NOW, analyses=analyses)
    (ld,) = got[("r", "what_it_does")]
    assert "teachable 5" in ld.text
    assert got[("r", "hot_spot")]  # other types stay current after the candidate refresh


def test_old_churn_rows_of_the_nine_types_are_no_longer_current(conn, cfg):
    conn.execute(
        "INSERT INTO leads(repo, story_type, kind, path, lead_key, text, strength, head_sha, "
        "first_seen_at, last_seen_at) VALUES ('r', 'what_it_does', 'path', 'src/x.py', "
        "'p:src/x.py', 'src/x.py (9 commits in the last year)', 1.0, 'h1', ?, ?)",
        (ledger.iso(NOW), ledger.iso(NOW)),
    )
    refresh(conn, {"churn": {"files": {"90": [{"path": "src/x.py", "commits": 3, "lines": 9}]}}})
    assert ledger.ranked(conn, cfg, "r", "what_it_does", NOW, 5) == []
    assert ("r", "what_it_does") not in ledger.for_brief(conn, cfg, ["r"], NOW)


# --- brief ---------------------------------------------------------------


def stories(b):
    return [s for p in b.packets for s in p.card_stories]


def test_no_candidates_skips_the_nine_types_and_fills_the_count():
    b = build(count=12, packet_size=4, ledger={})
    assert sum(p.count for p in b.packets) == 12
    assert not set(stories(b)) & set(NINE)
    assert not [r for p in b.packets for r in p.lead_refs if r["story_type"] in NINE]


def test_candidate_leads_skip_test_and_doc_files(conn):
    cand(conn, "tests/test_x.py", 1, "core", rating=(5, "core"))
    cand(conn, "AGENTS.md", 1, "core", rating=(5, "core"))
    cand(conn, "docs/guide.rst", 1, "core", rating=(5, "core"))
    cand(conn, "src/real.py", 1, "core", rating=(2, "core"))
    refresh(conn, {})
    for t in ("snippet_callouts", "what_it_does", "journey", "analogy"):
        assert paths(conn, t) <= {"src/real.py"}, t
    assert paths(conn, "what_it_does") == {"src/real.py"}


def test_lead_refs_for_has_no_churn_fallback():
    for t in NINE:
        assert brief.lead_refs_for(t, signals(), 0) == []


def test_candidate_leads_reach_packets_and_no_churn_path_leaks(conn, cfg):
    cand(conn, "billing/pay.py", 5, "core", "central hub", (5, "core"), repo="fixture")
    cand(conn, "billing/odd.py", 7, "clever", "bit twiddling", (5, "clever"), repo="fixture")
    refresh(conn, signals(), repo="fixture")
    b = build(count=12, ledger=ledger.for_brief(conn, cfg, ["fixture"], NOW))
    assert sum(p.count for p in b.packets) == 12
    nine = [r for p in b.packets for r in p.lead_refs if r["story_type"] in NINE]
    assert nine and {r["path"] for r in nine} <= {"billing/pay.py", "billing/odd.py"}
    assert not any("src/app.py" in r["text"] for r in nine)


# --- noise: intro dirs and whose_code ---------------------------------------


@pytest.mark.parametrize(
    "path,ok",
    [
        ("src/a/x.py", True),
        (".github/aw/x.yml", False),
        ("cassettes/http/x.json", False),
        ("tests/fixtures/x.py", False),
        ("src/__snapshots__/x.snap", False),
        ("vendor/lib/x.go", False),
        ("docs/x.md", False),
        ("src/generated/x.py", False),
        ("x.py", True),
    ],
)
def test_code_path(path, ok):
    assert brief.code_path(path) is ok


def intro_lead(path, i):
    return brief.Lead("hot_spot", "fixture", "path", path=path, text=f"{path}: hot", id=i)


D = {"categories": {"git_drama": 1.0}, "tones": DEFAULTS["tones"]}


def test_intro_never_picks_hidden_or_fixture_dirs():
    leads = [
        intro_lead("src/known.py", 1),
        intro_lead(".github/aw/ci.yml", 2),
        intro_lead("cassettes/http/rec.json", 3),
        intro_lead("billing/api/pay.py", 4),
    ]
    b = build(
        count=8,
        sig={"churn": {}},
        defaults=D,
        ledger={("fixture", "hot_spot"): leads},
        novelty={"fixture": {"src": 0.1}},
        intro_share=0.5,
    )
    intro = [r["path"] for p in b.packets for r in p.lead_refs if r.get("intro")]
    assert intro == ["billing/api/pay.py"]


def test_intro_prefers_dirs_with_core_candidates():
    leads = [intro_lead("misc/a.py", 1), intro_lead("billing/b.py", 2)]
    b = build(
        count=8,
        sig={"churn": {}},
        defaults=D,
        ledger={("fixture", "hot_spot"): leads},
        novelty={"fixture": {"src": 0.1}},
        intro_share=0.125,
        intro_prefer={"fixture": {"billing"}},
    )
    intro = [r["path"] for p in b.packets for r in p.lead_refs if r.get("intro")]
    assert intro == ["billing/b.py"]


def test_whose_code_never_offers_root_or_hidden_dirs():
    sig = signals()
    share = [{"author": "A", "share": 1.0}]
    dirs = (".", ".claude", ".clj-kondo", ".docker", "src", "billing")
    sig["author_shares"]["by_dir"] = {d: share for d in dirs}
    got = [x.text for x in brief.lead_refs_for("whose_code", sig, 0)]
    assert got == ["dir src/: A 100%", "dir billing/: A 100%"]

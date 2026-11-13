"""Subject cooldown across story types and the penalty for rejected leads."""

from datetime import UTC, datetime, timedelta

import pytest

from gittok import brief, db, ledger
from tests.conftest import make_config

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
SHA = "ab" * 20
REVERT = {"reverts": [{"sha": SHA, "ts": 1, "author": "x", "reverted_sha": "cd" * 20}]}
BLOBS = {"src/a.py": "a" * 40, "lib/b.py": "b" * 40}


def sig(*paths):
    files = [{"path": p, "commits": 9 - i, "lines": 90 - i} for i, p in enumerate(paths)]
    return {"churn": {"files": {"90": files}}}


@pytest.fixture
def conn():
    c = db.open_db(":memory:")
    yield c
    c.close()


@pytest.fixture
def cfg(fixture_repo, tmp_path):
    return make_config(fixture_repo, tmp_path)


def refresh(conn, s):
    return ledger.refresh(conn, "r", s, 0, "h1", BLOBS, NOW)


def days_ago(days):
    return ledger.iso(NOW - timedelta(days=days))


def subject_card(conn, visual, sources, age=3, story_type="before_after", status="ready"):
    conn.execute("INSERT OR IGNORE INTO repos(name, path) VALUES ('r', '/r')")
    conn.execute(
        "INSERT OR IGNORE INTO runs(id, status, started_at) VALUES ('run1', 'finished', 't')"
    )
    n = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    spec = {"visual": visual, "sources": sources, "repos": ["r"]}
    conn.execute(
        "INSERT INTO cards(id, run_id, repo_id, story_type, format, persona, tone, spec, status,"
        " story_key, created_at) VALUES (?, 'run1', 1, ?, 'meme', 'p', 't', ?, ?, ?, ?)",
        (f"c{n}", story_type, db.dumps(spec), status, f"k{n}", days_ago(age)),
    )


def drama(conn, cfg):
    return ledger.for_brief(conn, cfg, ["r"], NOW)[("r", "commit_drama")]


def hot(conn, cfg):
    return ledger.for_brief(conn, cfg, ["r"], NOW)[("r", "hot_spot")]


def test_commit_used_by_another_story_type_is_not_offered_within_the_window(conn, cfg):
    refresh(conn, REVERT)
    assert len(drama(conn, cfg)) == 1
    visual = {"kind": "code", "repo": "r", "commit": SHA[:7], "path": "x.py"}
    subject_card(conn, visual, [{"repo": "r", "commit": SHA}], age=3)
    assert drama(conn, cfg) == []


def test_subject_is_the_visual_else_the_first_source(conn, cfg):
    refresh(conn, REVERT)
    subject_card(conn, {"kind": "text"}, [{"repo": "r", "commit": SHA}, {"repo": "r", "path": "q"}])
    assert drama(conn, cfg) == []


def test_second_source_is_not_the_subject(conn, cfg):
    refresh(conn, REVERT)
    subject_card(conn, {"kind": "text"}, [{"repo": "r", "path": "q"}, {"repo": "r", "commit": SHA}])
    assert len(drama(conn, cfg)) == 1


def test_subject_cooldown_ends_after_the_window(conn, cfg):
    refresh(conn, REVERT)
    old = cfg.settings.agent.subject_cooldown_days + 1
    subject_card(conn, {"kind": "code", "repo": "r", "commit": SHA}, [], age=old)
    assert len(drama(conn, cfg)) == 1


def test_path_subject_blocks_path_leads_of_other_story_types(conn, cfg):
    refresh(conn, sig("src/a.py", "lib/b.py"))
    subject_card(conn, {"kind": "code", "repo": "r", "path": "src/a.py"}, [], age=2)
    assert [x.path for x in hot(conn, cfg)] == ["lib/b.py"]
    lead = brief.Lead("hot_spot", "r", "path", path="src/a.py", text="t")
    assert not ledger.offerable(conn, cfg, NOW)(lead)


def test_pinned_leads_are_exempt_from_subject_cooldown(conn, cfg):
    refresh(conn, sig("lib/b.py"))
    conn.execute(
        "INSERT INTO leads(repo, story_type, kind, path, commit_sha, lead_key, text, strength,"
        " head_sha, first_seen_at, last_seen_at) VALUES ('r', 'hot_spot', 'path', 'src/a.py', '',"
        " 'notif:1', 'asked', 1.0, 'h', 'x', 'x')"
    )
    subject_card(conn, {"kind": "code", "repo": "r", "path": "src/a.py"}, [], age=2)
    assert [x.key for x in hot(conn, cfg)] == ["notif:1", "p:lib/b.py"]


def test_rejected_lead_ranks_lower_and_recovers_after_the_window(conn, cfg):
    refresh(conn, sig("src/a.py", "lib/b.py"))
    a = conn.execute("SELECT id FROM leads WHERE path = 'src/a.py'").fetchone()[0]
    ledger.mark_rejected(conn, a, NOW - timedelta(days=1))
    ledger.mark_rejected(conn, a, NOW - timedelta(days=1))
    got = ledger.ranked(conn, cfg, "r", "hot_spot", NOW, 10)
    assert [x.path for x in got] == ["lib/b.py", "src/a.py"]  # strength 1.0 x 0.25 < 0.5
    after = NOW + timedelta(days=cfg.settings.agent.subject_cooldown_days + 2)
    got = ledger.ranked(conn, cfg, "r", "hot_spot", after, 10)
    assert [x.path for x in got] == ["src/a.py", "lib/b.py"]


def test_only_rejects_inside_the_window_lower_the_rank(conn, cfg):
    """Old rejects are forgotten: a new reject after the window counts as the first."""
    refresh(conn, sig("src/a.py", "lib/b.py"))
    a = conn.execute("SELECT id FROM leads WHERE path = 'src/a.py'").fetchone()[0]
    days = cfg.settings.agent.subject_cooldown_days
    for _ in range(5):
        ledger.mark_rejected(conn, a, NOW - timedelta(days=days + 10), window_days=days)
    ledger.mark_rejected(conn, a, NOW - timedelta(days=1), window_days=days)
    assert conn.execute("SELECT times_rejected FROM leads WHERE id = ?", (a,)).fetchone()[0] == 1

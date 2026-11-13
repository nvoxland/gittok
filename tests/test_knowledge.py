import json
import random
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from gittok import config as config_mod
from gittok import db, knowledge, learning, steering, store
from tests.cards import text_card
from tests.conftest import make_config

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
T = int(NOW.timestamp() * 1000)


@pytest.fixture
def cfg(fixture_repo, tmp_path):
    return make_config(fixture_repo, tmp_path)


@pytest.fixture
def conn():
    c = db.open_db(":memory:")
    c.execute(
        "INSERT INTO runs(id, status, started_at) VALUES ('r1', 'finished', '2026-05-30T00:00:00Z')"
    )
    yield c
    c.close()


def add_card(conn, cfg, **over) -> str:
    spec = text_card(SimpleNamespace(shas={"delete_legacy": "abc"}), **over)
    acc = SimpleNamespace(card=spec, resolved={}, story_key=f"k{random.random()}")
    cid = store.insert_card(conn, cfg, "r1", acc, now="2026-05-31T00:00:00Z")
    conn.commit()
    return cid


def ev(conn, card, type_, data=None, ts=T):
    conn.execute(
        "INSERT INTO events(card_id, type, ts, data, received_at) VALUES (?, ?, ?, ?, 'x')",
        (card, type_, ts, json.dumps(data or {})),
    )
    conn.commit()


def run(conn, cfg):
    return learning.process_events(conn, cfg, now=NOW)


def test_unseen_dir_is_fully_novel_and_seen_dir_less(conn, cfg):
    a = add_card(conn, cfg, dirs=["src"])
    add_card(conn, cfg, dirs=["billing"])
    for i in range(3):
        ev(conn, a, "impression", ts=T + i)
    run(conn, cfg)
    assert knowledge.novelty(conn, "fixture", "billing") == 1.0
    assert knowledge.novelty(conn, "fixture", "src") < knowledge.novelty(conn, "fixture", "billing")
    assert 0 <= knowledge.novelty(conn, "fixture", "src") <= 1


def test_wrong_quiz_raises_and_right_quiz_lowers(conn, cfg):
    a = add_card(conn, cfg, dirs=["src"])
    ev(conn, a, "impression")
    run(conn, cfg)
    base = knowledge.novelty(conn, "fixture", "src")
    ev(conn, a, "answer", {"choice": 0, "correct": False}, ts=T + 1)
    run(conn, cfg)
    assert knowledge.novelty(conn, "fixture", "src") > base
    for i in range(2, 8):
        ev(conn, a, "answer", {"choice": 1, "correct": True}, ts=T + i)
    run(conn, cfg)
    assert knowledge.novelty(conn, "fixture", "src") < base


def test_retired_knew_it_and_teach_more_events_do_not_move_novelty(conn, cfg):
    a = add_card(conn, cfg, dirs=["src"])
    ev(conn, a, "impression")
    run(conn, cfg)
    base = knowledge.novelty(conn, "fixture", "src")
    ev(conn, a, "knew_it", ts=T + 1)
    ev(conn, a, "teach_more", ts=T + 2)
    run(conn, cfg)
    assert knowledge.novelty(conn, "fixture", "src") == base


def test_explain_panel_open_counts_once_per_card(conn, cfg):
    a = add_card(conn, cfg, dirs=["src"])
    spec = json.loads(conn.execute("SELECT spec FROM cards WHERE id=?", (a,)).fetchone()[0])
    idx = 1 + [p["kind"] for p in spec["depth"]].index("explain")
    ev(conn, a, "depth_open", {"panel": 0})
    ev(conn, a, "depth_open", {"panel": idx}, ts=T + 1)
    ev(conn, a, "depth_open", {"panel": idx}, ts=T + 2)
    run(conn, cfg)
    row = conn.execute("SELECT * FROM knowledge WHERE repo='fixture' AND dir='src'").fetchone()
    assert row["explains_opened"] == 1


def test_parent_prefixes_up_to_two_levels(conn, cfg):
    a = add_card(conn, cfg, dirs=["a/b/c"])
    ev(conn, a, "impression")
    run(conn, cfg)
    dirs = {r["dir"] for r in conn.execute("SELECT dir FROM knowledge")}
    assert dirs == {"a", "a/b"}


def test_reprocessing_does_not_change_numbers(conn, cfg):
    a = add_card(conn, cfg, dirs=["src"])
    ev(conn, a, "impression")
    ev(conn, a, "answer", {"choice": 0, "correct": False}, ts=T + 1)
    run(conn, cfg)
    snap = [tuple(r) for r in conn.execute("SELECT * FROM knowledge ORDER BY dir")]
    n = knowledge.novelty(conn, "fixture", "src")
    run(conn, cfg)
    knowledge.update(conn)
    assert [tuple(r) for r in conn.execute("SELECT * FROM knowledge ORDER BY dir")] == snap
    assert knowledge.novelty(conn, "fixture", "src") == n
    row = conn.execute("SELECT * FROM knowledge WHERE dir='src'").fetchone()
    assert (row["cards_seen"], row["quiz_wrong"]) == (1, 1)


def test_churn_does_not_make_a_dir_less_novel(conn, cfg):
    from gittok import signals

    a = add_card(conn, cfg, dirs=["billing"])
    for i in range(4):
        ev(conn, a, "impression", ts=T + i)
    run(conn, cfg)
    quiet = knowledge.novelty(conn, "fixture", "billing")
    signals.analyze(conn, cfg.repos["fixture"], cfg.settings.analysis)
    assert knowledge.novelty(conn, "fixture", "billing") >= quiet


def test_churn_boost_is_bounded_and_scales_with_recent_commits():
    base = knowledge.combine({"cards_seen": 2}, commits_30d=0)
    some = knowledge.combine({"cards_seen": 2}, commits_30d=5)
    lots = knowledge.combine({"cards_seen": 2}, commits_30d=500)
    assert base < some < lots <= 1


def test_own_blame_share_is_a_small_prior():
    row = {"cards_seen": 1}
    plain = knowledge.combine(row)
    mine = knowledge.combine(row, own_share=1.0)
    assert mine < plain
    assert plain - mine <= 0.25 + 1e-9


def test_novelty_map_and_coverage_and_profile(conn, cfg):
    a = add_card(conn, cfg, dirs=["src"])
    add_card(conn, cfg, dirs=["billing"])
    ev(conn, a, "impression")
    run(conn, cfg)
    m = knowledge.novelty_map(conn, "fixture")
    assert m["src"] < 1
    rows = {r["dir"]: r for r in steering.coverage(conn, cfg)}
    assert rows["billing"]["novelty"] == 1.0
    assert rows["src"]["novelty"] == m["src"]
    prof = steering.get_profile(conn, cfg)["knowledge"]
    assert prof[0]["novelty"] == 1.0 or "novelty" in prof[0]
    json.dumps(prof)


def test_git_identities_setting():
    assert config_mod.UserSettings().git_identities == ()

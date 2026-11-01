import random
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import yaml

from codescroll import db, learning, slotter, store
from tests.cards import text_card
from tests.conftest import make_config

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def cfg(fixture_repo, tmp_path):
    """Pure ranking by default: no exploration and no learning boost."""
    c = make_config(fixture_repo, tmp_path)
    c.defaults["exploration_share"] = 0.0
    set_slotting(c, learning_boost_share=0.0)
    return c


def set_slotting(cfg, **knobs):
    path = cfg.root / "config" / "reward.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"slotting": knobs}))


@pytest.fixture
def conn():
    c = db.open_db(":memory:")
    c.execute(
        "INSERT INTO runs(id, status, started_at) VALUES ('r1', 'finished', '2026-05-30T00:00:00Z')"
    )
    yield c
    c.close()


def add_card(conn, cfg, created_at="2026-05-31T00:00:00Z", **over) -> str:
    spec = text_card(SimpleNamespace(shas={"delete_legacy": "abc"}), **over)
    acc = SimpleNamespace(card=spec, resolved={}, story_key=f"k{random.random()}")
    cid = store.insert_card(conn, cfg, "r1", acc, now=created_at)
    conn.commit()
    return cid


def add_rule(conn, type_, feature, value, **kw):
    conn.execute(
        "INSERT INTO rules(type, feature, value, factor, slots, max_share, expires_at, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, '2026-05-01T00:00:00Z')",
        (type_, feature, value, kw.get("factor"), kw.get("slots"), kw.get("max_share"),
         kw.get("expires_at")),
    )  # fmt: skip
    conn.commit()


def impress(conn, card_id, when):
    conn.execute(
        "INSERT INTO events(card_id, type, ts, data, received_at) "
        "VALUES (?, 'impression', ?, '{}', ?)",
        (card_id, int(when.timestamp() * 1000), "2026-06-01T00:00:00Z"),
    )
    conn.commit()


def fix_scores(monkeypatch, scores: dict[str, float]):
    """Make Thompson scores deterministic; unlisted cards get 0.5."""

    def fake(conn, cfg, ids, rng, now=None):
        return {i: scores.get(i, 0.5) for i in ids}

    monkeypatch.setattr(learning, "score_cards", fake)


def batch(conn, cfg, limit=10, served=(), seed=1):
    return slotter.build_batch(conn, cfg, limit, set(served), seed, NOW)


def test_batch_has_ready_cards_and_skips_served(conn, cfg):
    ids = [add_card(conn, cfg) for _ in range(4)]
    conn.execute("UPDATE cards SET status = 'pending_render' WHERE id = ?", (ids[0],))
    out = batch(conn, cfg, served={ids[1]})
    assert sorted(out) == sorted(ids[2:])


def test_recently_impressed_cards_are_excluded_for_repeat_days(conn, cfg):
    old, recent, fresh = (add_card(conn, cfg) for _ in range(3))
    impress(conn, old, NOW - timedelta(days=8))
    impress(conn, recent, NOW - timedelta(days=6))
    assert sorted(batch(conn, cfg)) == sorted([old, fresh])


def _same_story(conn, *ids, key="story-1"):
    for i in ids:
        conn.execute("UPDATE cards SET story_key = ?, format = ? WHERE id = ?", (key, i, i))
    conn.commit()


def test_variants_of_one_story_not_served_within_repeat_window(conn, cfg):
    first, variant, other = (add_card(conn, cfg) for _ in range(3))
    _same_story(conn, first, variant)
    impress(conn, first, NOW - timedelta(days=3))
    assert sorted(batch(conn, cfg)) == sorted([other])
    conn.execute("DELETE FROM events")  # the impression is now outside the window
    impress(conn, first, NOW - timedelta(days=8))
    out = batch(conn, cfg)  # both are eligible again, but still only one per batch
    assert len(out) == 2 and other in out and (first in out) != (variant in out)


def test_one_card_per_story_key_per_batch(conn, cfg, monkeypatch):
    a, b, c = (add_card(conn, cfg) for _ in range(3))
    _same_story(conn, a, b)
    fix_scores(monkeypatch, {a: 0.2, b: 0.9, c: 0.5})
    assert sorted(batch(conn, cfg)) == sorted([b, c])


def test_ban_rule_removes_matching_cards(conn, cfg):
    a = add_card(conn, cfg, format="chart")
    b = add_card(conn, cfg, format="meme")
    add_rule(conn, "ban", "format", "chart")
    assert batch(conn, cfg) == [b]
    assert a not in batch(conn, cfg)


def test_expired_rule_is_ignored(conn, cfg):
    a = add_card(conn, cfg, format="chart")
    add_rule(conn, "ban", "format", "chart", expires_at="2026-05-31T00:00:00Z")
    assert batch(conn, cfg) == [a]


@pytest.mark.parametrize("kind", ["boost", "prefer"])
def test_boost_and_prefer_multiply_score(conn, cfg, monkeypatch, kind):
    a = add_card(conn, cfg, format="chart")
    b = add_card(conn, cfg, format="meme")
    fix_scores(monkeypatch, {a: 0.2, b: 0.5})
    assert batch(conn, cfg, limit=1) == [b]
    add_rule(conn, kind, "format", "chart", factor=3.0)
    assert batch(conn, cfg, limit=1) == [a]


def test_focus_reserves_slots_for_matching_cards(conn, cfg, monkeypatch):
    charts = [add_card(conn, cfg, format="chart") for _ in range(3)]
    others = [add_card(conn, cfg, format="meme", dirs=[f"d{i}"]) for i in range(6)]
    fix_scores(monkeypatch, {**{c: 0.01 for c in charts}, **{o: 0.9 for o in others}})
    assert not set(batch(conn, cfg, limit=4)) & set(charts)
    add_rule(conn, "focus", "format", "chart", slots=2)
    out = batch(conn, cfg, limit=4)
    assert len(set(out) & set(charts)) == 2
    assert len(out) == 4


def test_limit_rule_caps_matching_share(conn, cfg, monkeypatch):
    charts = [add_card(conn, cfg, format="chart") for _ in range(5)]
    others = [add_card(conn, cfg, format="meme") for _ in range(8)]
    fix_scores(monkeypatch, {**{c: 0.9 for c in charts}, **{o: 0.1 for o in others}})
    assert len(set(batch(conn, cfg, limit=8)) & set(charts)) == 5
    add_rule(conn, "limit", "format", "chart", max_share=0.25)
    out = batch(conn, cfg, limit=8)
    assert len(set(out) & set(charts)) == 2
    assert len(out) == 8


def test_exploration_share_fills_from_lower_half(conn, cfg, monkeypatch):
    ids = [add_card(conn, cfg) for _ in range(20)]
    ranked = {c: 1 - n / 100 for n, c in enumerate(ids)}  # ids[0] is the best
    fix_scores(monkeypatch, ranked)
    assert set(batch(conn, cfg, limit=10)) == set(ids[:10])
    cfg.defaults["exploration_share"] = 0.2
    out = batch(conn, cfg, limit=10, seed=3)
    assert len(out) == 10
    assert len(set(out) & set(ids[10:])) == 2
    assert set(ids[:8]) <= set(out)
    # reproducible for one seed, different for another
    assert batch(conn, cfg, limit=10, seed=3) == out
    assert any(set(batch(conn, cfg, limit=10, seed=s)) != set(out) for s in range(4, 12))


def test_learning_boost_picks_cards_from_least_covered_dirs(conn, cfg, monkeypatch):
    a_cards = [add_card(conn, cfg, dirs=["a"]) for _ in range(6)]
    b_card = add_card(conn, cfg, dirs=["b"])
    c_card = add_card(conn, cfg, dirs=["c"])
    for cid in (*a_cards, b_card):
        impress(conn, cid, NOW - timedelta(days=9))
    fix_scores(monkeypatch, {**{a: 0.9 for a in a_cards}, b_card: 0.3, c_card: 0.1})
    assert c_card not in batch(conn, cfg, limit=5)
    set_slotting(cfg, learning_boost_share=0.2)
    out = batch(conn, cfg, limit=5)
    assert c_card in out
    assert b_card not in out
    assert len(out) == 5


def fmt(conn, ids):
    return [conn.execute("SELECT format FROM cards WHERE id = ?", (i,)).fetchone()[0] for i in ids]


def test_rhythm_never_three_same_formats_in_a_row_when_avoidable(conn, cfg, monkeypatch):
    posts = [add_card(conn, cfg, format="text_post") for _ in range(4)]
    pics = [add_card(conn, cfg, format="illustration") for _ in range(2)]
    fix_scores(monkeypatch, {**{p: 0.9 for p in posts}, **{p: 0.1 for p in pics}})
    formats = fmt(conn, batch(conn, cfg, limit=6))
    assert len(formats) == 6
    assert not any(formats[i] == formats[i + 1] == formats[i + 2] for i in range(4))


def test_rhythm_alternates_fast_and_slow_formats(conn, cfg, monkeypatch):
    fast = [add_card(conn, cfg, format=f) for f in ("meme", "chart", "fun_fact")]
    slow = [add_card(conn, cfg, format=f) for f in ("thread", "comic", "code_card")]
    fix_scores(monkeypatch, {**{c: 0.9 for c in fast}, **{c: 0.1 for c in slow}})
    classes = ["fast" if f in ("meme", "chart", "fun_fact") else "slow"
               for f in fmt(conn, batch(conn, cfg, limit=6))]  # fmt: skip
    assert len(classes) == 6
    assert all(classes[i] != classes[i + 1] for i in range(5))


def due_quiz(conn, cfg, n):
    from tests.cards import quiz_card

    ids = [add_card_spec(conn, cfg, quiz_card(SimpleNamespace(shas={}))) for _ in range(n)]
    for cid in ids:
        impress(conn, cid, NOW - timedelta(days=1))  # recent, so only SRS can bring it back
        conn.execute(
            "INSERT INTO srs(card_id, interval_days, due_at, streak, mastered) "
            "VALUES (?, 1, ?, 0, 0)",
            (cid, "2026-05-31T12:00:00Z"),
        )
    conn.commit()
    return ids


def add_card_spec(conn, cfg, spec):
    acc = SimpleNamespace(card=spec, resolved={}, story_key=f"k{random.random()}")
    cid = store.insert_card(conn, cfg, "r1", acc, now="2026-05-31T00:00:00Z")
    conn.commit()
    return cid


def test_due_srs_cards_at_most_two_and_at_position_three_or_later(conn, cfg, monkeypatch):
    plain = [add_card(conn, cfg, format=f"f{i}") for i in range(8)]
    due = due_quiz(conn, cfg, 4)
    fix_scores(monkeypatch, {**{p: 0.5 for p in plain}, **{d: 0.99 for d in due}})
    out = batch(conn, cfg, limit=8)
    positions = [n for n, i in enumerate(out) if i in due]
    assert len(positions) == 2
    assert all(p >= 3 for p in positions)
    assert len(out) == 8


def test_served_due_cards_do_not_come_back(conn, cfg):
    plain = [add_card(conn, cfg, format=f"f{i}") for i in range(6)]
    due = due_quiz(conn, cfg, 2)
    out = batch(conn, cfg, limit=8, served=set(due))
    assert sorted(out) == sorted(plain)


def test_srs_cards_wait_when_the_batch_is_too_short_for_position_three(conn, cfg):
    plain = [add_card(conn, cfg, format="f0") for _ in range(2)]
    due_quiz(conn, cfg, 1)
    assert sorted(batch(conn, cfg, limit=8)) == sorted(plain)


def test_srs_past_batch_end_does_not_shorten_batch(conn, cfg):
    for _ in range(30):
        add_card(conn, cfg)
    due_quiz(conn, cfg, 3)
    out = batch(conn, cfg, limit=5)
    assert len(out) == 5
    assert len(set(out)) == 5


def test_limit_rule_with_small_limit_caps_at_least_one(conn, cfg, monkeypatch):
    charts = [add_card(conn, cfg, format="chart") for _ in range(3)]
    others = [add_card(conn, cfg, format="meme") for _ in range(6)]
    fix_scores(monkeypatch, {**{c: 0.9 for c in charts}, **{o: 0.1 for o in others}})
    add_rule(conn, "limit", "format", "chart", max_share=0.1)
    out = batch(conn, cfg, limit=4)
    assert len(set(out) & set(charts)) == 1
    assert len(out) == 4


def test_limit_rule_zero_share_bans_and_null_share_is_no_cap(conn, cfg, monkeypatch):
    charts = [add_card(conn, cfg, format="chart") for _ in range(3)]
    others = [add_card(conn, cfg, format="meme") for _ in range(6)]
    fix_scores(monkeypatch, {**{c: 0.9 for c in charts}, **{o: 0.1 for o in others}})
    add_rule(conn, "limit", "format", "chart", max_share=0.0)
    assert not set(batch(conn, cfg, limit=4)) & set(charts)
    conn.execute("DELETE FROM rules")
    add_rule(conn, "limit", "format", "chart")
    assert len(set(batch(conn, cfg, limit=3)) & set(charts)) == 3


def test_exploration_uses_probabilistic_rounding_for_small_limits(conn, cfg, monkeypatch):
    ids = [add_card(conn, cfg) for _ in range(20)]
    fix_scores(monkeypatch, {c: 1 - n / 100 for n, c in enumerate(ids)})
    cfg.defaults["exploration_share"] = 0.15  # 0.15 * 4 = 0.6 explored cards per batch
    top = set(ids[:10])
    seeds = range(300)
    explored = sum(len(set(batch(conn, cfg, limit=4, seed=s)) - top) for s in seeds)
    assert 0.45 * len(seeds) < explored < 0.75 * len(seeds)


def test_dir_rules_match_by_path_prefix(conn, cfg, monkeypatch):
    nested = add_card(conn, cfg, format="meme", dirs=["src/api"])
    other = add_card(conn, cfg, format="meme", dirs=["lib/src"])
    fix_scores(monkeypatch, {nested: 0.1, other: 0.9})
    add_rule(conn, "focus", "dir", "src", slots=1)
    assert batch(conn, cfg, limit=1) == [nested]
    add_rule(conn, "ban", "dir", "src/")
    assert batch(conn, cfg) == [other]


def test_dir_rule_accepts_repo_prefix(conn, cfg):
    a = add_card(conn, cfg, format="meme", dirs=["src/api"])
    repo = conn.execute(
        "SELECT value FROM card_features WHERE card_id = ? AND feature = 'repo'", (a,)
    ).fetchone()[0]
    add_rule(conn, "ban", "dir", f"{repo}/src")
    assert batch(conn, cfg) == []

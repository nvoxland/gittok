"""Serving the feed: every card the reader has not seen, oldest first. What the learner learned
shapes which cards get made (the brief), never the order of the cards that exist."""

import random
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from gittok import db, slotter, store
from tests.cards import text_card
from tests.conftest import make_config

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


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


def batch(conn, cfg, limit=10, served=(), seed=1):
    return slotter.build_batch(conn, cfg, limit, set(served), seed, NOW)


def day(n: int) -> str:
    return f"2026-05-{n:02d}T00:00:00Z"


# ---------------------------------------------------------------- what is served, in what order


def test_batch_has_ready_cards_and_skips_served(conn, cfg):
    ids = [add_card(conn, cfg) for _ in range(4)]
    conn.execute("UPDATE cards SET status = 'pending_render' WHERE id = ?", (ids[0],))
    out = batch(conn, cfg, served={ids[1]})
    assert sorted(out) == sorted(ids[2:])


def test_unseen_cards_go_out_oldest_first(conn, cfg):
    newest = add_card(conn, cfg, created_at=day(20))
    oldest = add_card(conn, cfg, created_at=day(2))
    middle = add_card(conn, cfg, created_at=day(10))
    assert batch(conn, cfg) == [oldest, middle, newest]
    assert batch(conn, cfg, limit=2) == [oldest, middle]
    assert batch(conn, cfg, served={oldest, middle}) == [newest]


def test_a_seen_card_never_comes_back(conn, cfg):
    long_ago, recent, fresh = (add_card(conn, cfg) for _ in range(3))
    impress(conn, long_ago, NOW - timedelta(days=60))
    impress(conn, recent, NOW - timedelta(days=1))
    assert batch(conn, cfg) == [fresh]


def test_what_the_learner_learned_does_not_change_the_order(conn, cfg):
    """Strong evidence for one card's features changes nothing: the order is the age."""
    old = add_card(conn, cfg, created_at=day(1), format="chart")
    new = add_card(conn, cfg, created_at=day(20), format="meme")
    conn.execute(
        "INSERT INTO model_weights(feature, value, mean, precision, n, updated_at) "
        "VALUES ('format', 'meme', 5.0, 100.0, 100.0, ?), ('format', 'chart', -5.0, 100.0, "
        "100.0, ?)",
        ("2026-06-01T00:00:00Z", "2026-06-01T00:00:00Z"),
    )
    conn.commit()
    for seed in range(5):
        assert batch(conn, cfg, seed=seed) == [old, new]


@pytest.mark.parametrize(
    "rule",
    [
        ("boost", {"factor": 5.0}),
        ("prefer", {"factor": 5.0}),
        ("limit", {"max_share": 0.0}),
        ("focus", {"slots": 2}),
    ],
)
def test_mix_rules_shape_generation_not_serving(conn, cfg, rule):
    """`less memes` and the like change what gets made (the brief). A card that was made is
    served in its turn."""
    kind, kw = rule
    chart = add_card(conn, cfg, created_at=day(1), format="chart")
    meme = add_card(conn, cfg, created_at=day(2), format="meme")
    add_rule(conn, kind, "format", "meme", **kw)
    assert batch(conn, cfg) == [chart, meme]


# ---------------------------------------------------------------- stories


def _same_story(conn, *ids, key="story-1"):
    for i in ids:
        conn.execute("UPDATE cards SET story_key = ?, format = ? WHERE id = ?", (key, i, i))
    conn.commit()


def test_variants_of_one_story_not_served_within_repeat_window(conn, cfg):
    first, variant, other = (add_card(conn, cfg) for _ in range(3))
    _same_story(conn, first, variant)
    impress(conn, first, NOW - timedelta(days=3))
    assert batch(conn, cfg) == [other]
    conn.execute("DELETE FROM events")  # the impression is now outside the window
    impress(conn, first, NOW - timedelta(days=8))
    assert sorted(batch(conn, cfg)) == sorted([variant, other])  # `first` was seen


def test_one_card_per_story_key_per_batch_the_oldest(conn, cfg):
    a = add_card(conn, cfg, created_at=day(5))
    b = add_card(conn, cfg, created_at=day(3))
    c = add_card(conn, cfg, created_at=day(4))
    _same_story(conn, a, b)
    assert batch(conn, cfg) == [b, c]


# ---------------------------------------------------------------- quiz reviews


def due_quiz(conn, cfg, n):
    from tests.cards import quiz_card

    ids = [add_card_spec(conn, cfg, quiz_card(SimpleNamespace(shas={}))) for _ in range(n)]
    for cid in ids:
        impress(conn, cid, NOW - timedelta(days=1))  # seen, so only a review brings it back
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


def test_due_srs_cards_at_most_two_and_at_position_three_or_later(conn, cfg):
    plain = [add_card(conn, cfg, format=f"f{i}") for i in range(8)]
    due = due_quiz(conn, cfg, 4)
    out = batch(conn, cfg, limit=8)
    positions = [n for n, i in enumerate(out) if i in due]
    assert len(positions) == 2
    assert all(p >= 3 for p in positions)
    assert len(out) == 8 and set(out) - set(due) <= set(plain)


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


# ---------------------------------------------------------------- series


def series(key, part, of=3):
    return {"key": key, "part": part, "of": of}


def test_series_parts_stay_in_order_with_a_gap(conn, cfg):
    p2 = add_card(conn, cfg, created_at=day(1), series=series("saga", 2), hook="part two")
    p1 = add_card(conn, cfg, created_at=day(2), series=series("saga", 1), hook="part one")
    for i in range(4):
        add_card(conn, cfg, created_at=day(3 + i), hook=f"other {i}")
    out = batch(conn, cfg, 6)
    assert out.index(p1) < out.index(p2)
    assert out.index(p2) - out.index(p1) >= slotter.SERIES_GAP


def test_series_part_waits_for_an_unseen_earlier_part(conn, cfg):
    p1 = add_card(conn, cfg, series=series("saga", 1), hook="part one")
    p2 = add_card(conn, cfg, series=series("saga", 2), hook="part two")
    other = add_card(conn, cfg, hook="other")
    retold = add_card(conn, cfg, hook="part one, told before")
    _same_story(conn, p1, retold)
    impress(conn, retold, NOW - timedelta(days=3))  # its story was shown: part 1 must wait
    out = batch(conn, cfg, 5)
    assert p1 not in out and p2 not in out and other in out
    conn.execute("DELETE FROM events")
    conn.commit()
    out = batch(conn, cfg, 5)
    assert out.index(p1) < out.index(p2)
    # A part served on an earlier page counts as seen, even before its impression lands.
    assert p2 in batch(conn, cfg, 5, served={p1})

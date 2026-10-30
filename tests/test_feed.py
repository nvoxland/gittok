import base64
import json
import random
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from codescroll import db, feed, store
from tests.cards import quiz_card, text_card
from tests.conftest import make_config

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
FX = SimpleNamespace(shas={"delete_legacy": "abc"})


@pytest.fixture
def cfg(fixture_repo, tmp_path):
    c = make_config(fixture_repo, tmp_path)
    c.defaults["exploration_share"] = 0.0
    return c


@pytest.fixture
def conn():
    c = db.open_db(":memory:")
    c.execute(
        "INSERT INTO runs(id, status, started_at) VALUES ('r1', 'finished', '2026-05-30T00:00:00Z')"
    )
    yield c
    c.close()


def add(conn, cfg, spec) -> str:
    resolved = {}
    if "interaction" in spec:
        resolved["interaction"] = {"answer_index": spec["interaction"].get("answer_index")}
    acc = SimpleNamespace(card=spec, resolved=resolved, story_key=f"k{random.random()}")
    cid = store.insert_card(conn, cfg, "r1", acc, now="2026-05-31T00:00:00Z")
    conn.commit()
    return cid


def test_cursor_round_trips():
    cursor = feed.encode_cursor(["c_1", "c_2"], 42)
    assert json.loads(base64.urlsafe_b64decode(cursor)) == {"served": ["c_1", "c_2"], "seed": 42}
    assert feed.decode_cursor(cursor) == (["c_1", "c_2"], 42)


def _b64(obj) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode()


@pytest.mark.parametrize(
    "cursor",
    [
        "!!!notbase64", "bm90LWpzb24=", "e30=", "NQ==",
        _b64({"served": "c_1", "seed": 1}),
        _b64({"served": [1], "seed": 1}),
        _b64({"served": [], "seed": "x"}),
        _b64({"served": [], "seed": True}),
        _b64(["c_1", 3]),
    ],
)  # fmt: skip
def test_malformed_cursors_raise(cursor):
    with pytest.raises(feed.InvalidCursor):
        feed.decode_cursor(cursor)


def test_strip_answers_hides_answer_and_explanation_only(conn, cfg):
    cid = add(conn, cfg, quiz_card(FX))
    row = conn.execute("SELECT * FROM cards WHERE id = ?", (cid,)).fetchone()
    full = feed.card_json(row)
    assert full["interaction"]["answer_index"] == 0
    safe = feed.public_card(row)
    assert safe["interaction"] == {
        "question": "Which file defines main()?",
        "choices": ["src/app.py", "src/util.py", "billing/invoice.py"],
    }
    assert "answer_index" not in safe["resolved"]["interaction"]
    assert full["interaction"]["answer_index"] == 0  # the original is not mutated
    plain = add(conn, cfg, text_card(FX))
    row = conn.execute("SELECT * FROM cards WHERE id = ?", (plain,)).fetchone()
    assert "interaction" not in feed.public_card(row)


def test_page_serves_batches_and_tracks_served_in_the_cursor(conn, cfg):
    ids = {add(conn, cfg, text_card(FX)) for _ in range(5)}
    cards, cursor = feed.page(conn, cfg, 2, None, 7, NOW)
    assert len(cards) == 2 and cursor
    more, cursor2 = feed.page(conn, cfg, 2, cursor, 7, NOW)
    last, cursor3 = feed.page(conn, cfg, 2, cursor2, 7, NOW)
    seen = [c["id"] for c in cards + more + last]
    assert set(seen) == ids and len(seen) == 5
    assert cursor3 is None
    assert feed.decode_cursor(cursor2)[1] == 7
    assert len(feed.decode_cursor(cursor2)[0]) == 4


def test_cursor_stores_compact_tokens(conn, cfg):
    for _ in range(3):
        add(conn, cfg, text_card(FX))
    cards, cursor = feed.page(conn, cfg, 2, None, 7, NOW)
    tokens, _ = feed.decode_cursor(cursor)
    assert tokens == [c["id"][-12:] for c in cards]
    assert all(len(t) == 12 for t in tokens)


def test_cursor_served_list_is_capped_at_500(conn, cfg):
    for _ in range(3):
        add(conn, cfg, text_card(FX))
    old = [f"{n:012x}" for n in range(600)]
    cursor = feed.encode_cursor(old, 7)
    cards, cursor2 = feed.page(conn, cfg, 2, cursor, 7, NOW)
    tokens, _ = feed.decode_cursor(cursor2)
    assert len(tokens) == 500
    assert tokens[-2:] == [c["id"][-12:] for c in cards]


def test_page_with_nothing_left_is_empty_with_no_cursor(conn, cfg):
    assert feed.page(conn, cfg, 5, None, 1, NOW) == ([], None)


def test_card_json_always_has_a_comments_list(conn, cfg):
    spec = text_card(FX)
    spec.pop("comments", None)
    cid = add(conn, cfg, spec)
    row = conn.execute("SELECT * FROM cards WHERE id = ?", (cid,)).fetchone()
    assert feed.public_card(row)["comments"] == []

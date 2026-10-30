import json
import random
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from codescroll import db, srs, store
from tests.cards import quiz_card, text_card, this_or_that_card
from tests.conftest import make_config

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
FX = SimpleNamespace(shas={"delete_legacy": "abc"})


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


def add(conn, cfg, spec, answer_index="spec") -> str:
    resolved = {}
    if "interaction" in spec:
        resolved["interaction"] = {"answer_index": spec["interaction"].get("answer_index")}
    acc = SimpleNamespace(card=spec, resolved=resolved, story_key=f"k{random.random()}")
    cid = store.insert_card(conn, cfg, "r1", acc, now="2026-05-31T00:00:00Z")
    conn.commit()
    return cid


def row(conn, cid):
    r = conn.execute("SELECT * FROM srs WHERE card_id = ?", (cid,)).fetchone()
    return dict(r) if r else None


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_wrong_answer_creates_srs_row_due_in_one_day(conn, cfg):
    cid = add(conn, cfg, quiz_card(FX))
    res = srs.record_answer(conn, cid, 1, NOW)
    assert res == {
        "correct": False,
        "answer_index": 0,
        "explanation": "main() lives in src/app.py.",
    }
    assert row(conn, cid) == {
        "card_id": cid, "interval_days": 1, "due_at": iso(NOW + timedelta(days=1)),
        "streak": 0, "mastered": 0,
    }  # fmt: skip


def test_correct_answer_without_srs_row_changes_nothing(conn, cfg):
    cid = add(conn, cfg, quiz_card(FX))
    assert srs.record_answer(conn, cid, 0, NOW)["correct"] is True
    assert row(conn, cid) is None


def test_correct_answers_on_due_card_climb_1_3_7_then_master(conn, cfg):
    cid = add(conn, cfg, quiz_card(FX))
    srs.record_answer(conn, cid, 2, NOW)
    t = NOW
    for interval, streak, mastered in [(3, 1, 0), (7, 2, 0), (7, 3, 1)]:
        t = t + timedelta(days=row(conn, cid)["interval_days"], minutes=1)
        srs.record_answer(conn, cid, 0, t)
        r = row(conn, cid)
        assert (r["interval_days"], r["streak"], r["mastered"]) == (interval, streak, mastered)
    assert srs.due_cards(conn, t + timedelta(days=30)) == []


def test_correct_answer_before_due_does_not_advance(conn, cfg):
    cid = add(conn, cfg, quiz_card(FX))
    srs.record_answer(conn, cid, 2, NOW)
    srs.record_answer(conn, cid, 0, NOW + timedelta(hours=1))
    assert row(conn, cid)["interval_days"] == 1 and row(conn, cid)["streak"] == 0


def test_wrong_answer_resets_interval_and_streak(conn, cfg):
    cid = add(conn, cfg, quiz_card(FX))
    srs.record_answer(conn, cid, 2, NOW)
    later = NOW + timedelta(days=1, minutes=1)
    srs.record_answer(conn, cid, 0, later)
    assert row(conn, cid)["interval_days"] == 3
    much_later = later + timedelta(days=4)
    srs.record_answer(conn, cid, 1, much_later)
    r = row(conn, cid)
    assert (r["interval_days"], r["streak"], r["mastered"]) == (1, 0, 0)
    assert r["due_at"] == iso(much_later + timedelta(days=1))


def test_this_or_that_has_no_correct_answer_and_no_srs(conn, cfg):
    cid = add(conn, cfg, this_or_that_card(FX))
    res = srs.record_answer(conn, cid, 1, NOW)
    assert res["correct"] is None and res["answer_index"] is None
    assert res["explanation"]
    assert row(conn, cid) is None


def test_record_answer_errors(conn, cfg):
    quiz = add(conn, cfg, quiz_card(FX))
    plain = add(conn, cfg, text_card(FX))
    with pytest.raises(srs.UnknownCard):
        srs.record_answer(conn, "c_nope", 0, NOW)
    with pytest.raises(srs.NotInteractive):
        srs.record_answer(conn, plain, 0, NOW)
    for bad in (-1, 3):
        with pytest.raises(srs.BadChoice):
            srs.record_answer(conn, quiz, bad, NOW)


def test_due_cards_lists_unmastered_due_ready_cards_oldest_first(conn, cfg):
    a, b, c = (add(conn, cfg, quiz_card(FX)) for _ in range(3))
    srs.record_answer(conn, a, 1, NOW)
    srs.record_answer(conn, b, 1, NOW - timedelta(days=1))
    srs.record_answer(conn, c, 1, NOW - timedelta(days=5))
    conn.execute("UPDATE srs SET mastered = 1 WHERE card_id = ?", (c,))
    assert srs.due_cards(conn, NOW + timedelta(days=1)) == [b, a]
    assert srs.due_cards(conn, NOW) == [b]
    assert json.dumps(srs.due_cards(conn, NOW))  # plain list of ids

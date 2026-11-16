"""Review fixes in supply.py and the feed watch."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from gittok import db, runs, store, supply
from tests.cards import text_card
from tests.conftest import make_config

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def cfg(fixture_repo, tmp_path):
    return make_config(fixture_repo, tmp_path)


@pytest.fixture
def conn():
    c = db.open_db(":memory:")
    yield c
    c.close()


def _finished_run(conn, cfg, at, cards=0):
    run_id = runs.open_run(conn, cfg, repo=None, brief="b", requested=5, now=at)
    run_id = run_id["run_id"] if isinstance(run_id, dict) else run_id
    for _ in range(cards):
        spec = text_card(SimpleNamespace(shas={"delete_legacy": "abc"}))
        acc = SimpleNamespace(card=spec, resolved={}, story_key=f"k{_}{at}")
        cid = store.insert_card(conn, cfg, run_id, acc, now="2026-05-31T00:00:00Z")
        conn.execute(
            "INSERT INTO events(card_id, type, ts, data, received_at) "
            "VALUES (?, 'impression', 1, '{}', '2026-06-01T00:00:00Z')", (cid,))
    conn.execute("UPDATE runs SET status = 'finished' WHERE id = ?", (run_id,))
    conn.commit()


def test_a_run_that_made_no_cards_does_not_answer_the_last_line(conn, cfg):
    assert supply.signal_wants_cards(conn, cfg, NOW) == 1
    _finished_run(conn, cfg, NOW + timedelta(minutes=5), cards=0)
    assert supply.signal_wants_cards(conn, cfg, NOW + timedelta(minutes=30)) == 0


def test_a_finished_run_with_cards_answers_the_last_line(conn, cfg):
    assert supply.signal_wants_cards(conn, cfg, NOW) == 1
    _finished_run(conn, cfg, NOW + timedelta(minutes=5), cards=1)
    assert supply.signal_wants_cards(conn, cfg, NOW + timedelta(minutes=30)) == 1

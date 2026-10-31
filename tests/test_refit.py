import json
from contextlib import closing
from types import SimpleNamespace

import pytest

from codescroll import db, refit, runs, store
from tests.cards import text_card
from tests.conftest import make_config


@pytest.fixture
def cfg(fixture_repo, tmp_path):
    return make_config(fixture_repo, tmp_path)


@pytest.fixture
def conn(cfg):
    with closing(db.open_db(cfg.settings.data_dir / "codescroll.db")) as c:
        yield c


def put(conn, cfg, card) -> str:
    key = f"k{conn.execute('SELECT COUNT(*) FROM cards').fetchone()[0]}"
    acc = SimpleNamespace(card=card, resolved={"visual": None, "depth": [None]}, story_key=key)
    run_id = runs.open_run(conn, cfg, repo=None, brief="b", requested=1)
    return store.store_card(conn, cfg, run_id, acc)


def long_card(fixture_repo):
    card = text_card(fixture_repo)
    card["visual"]["body"] = "word " * 100
    return card


def test_export_writes_only_cards_that_do_not_fit(conn, cfg, fixture_repo, tmp_path):
    bad = put(conn, cfg, long_card(fixture_repo))
    put(conn, cfg, text_card(fixture_repo))
    out = tmp_path / "refit"
    assert refit.export(conn, out) == [bad]
    data = json.loads((out / f"{bad}.json").read_text())
    assert data["card_id"] == bad
    assert "budget 360" in data["problem"]
    assert data["card"]["visual"]["body"].startswith("word")


def test_apply_replaces_the_card_in_place_after_full_validation(conn, cfg, fixture_repo, tmp_path):
    bad = put(conn, cfg, long_card(fixture_repo))
    out = tmp_path / "refit"
    refit.export(conn, out)
    data = json.loads((out / f"{bad}.json").read_text())
    data["card"]["visual"]["body"] = "Short now."
    (out / f"{bad}.json").write_text(json.dumps(data))
    res = refit.apply(conn, cfg, out)
    assert res == {"replaced": [bad], "rejected": []}
    row = conn.execute("SELECT spec, resolved FROM cards WHERE id = ?", (bad,)).fetchone()
    assert db.loads(row["spec"])["visual"]["body"] == "Short now."
    assert db.loads(row["resolved"]) is not None
    assert conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 1  # no new card


def test_apply_keeps_the_old_card_when_the_rewrite_still_fails(conn, cfg, fixture_repo, tmp_path):
    bad = put(conn, cfg, long_card(fixture_repo))
    out = tmp_path / "refit"
    refit.export(conn, out)  # unchanged file: still too long
    res = refit.apply(conn, cfg, out)
    assert res["replaced"] == []
    assert [(r["card_id"], r["reason"]) for r in res["rejected"]] == [(bad, "too_long")]
    row = conn.execute("SELECT spec FROM cards WHERE id = ?", (bad,)).fetchone()
    assert db.loads(row["spec"])["visual"]["body"].startswith("word")


def test_apply_refuses_a_different_story_type(conn, cfg, fixture_repo, tmp_path):
    bad = put(conn, cfg, long_card(fixture_repo))
    out = tmp_path / "refit"
    refit.export(conn, out)
    data = json.loads((out / f"{bad}.json").read_text())
    data["card"]["visual"]["body"] = "Short."
    data["card"]["story_type"] = "hot_spot"
    (out / f"{bad}.json").write_text(json.dumps(data))
    res = refit.apply(conn, cfg, out)
    assert [r["reason"] for r in res["rejected"]] == ["story_changed"]

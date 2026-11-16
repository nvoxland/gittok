import json
from contextlib import closing
from types import SimpleNamespace

import pytest

from gittok import db, refit, runs
from tests.cards import text_card
from tests.conftest import make_config, store_card


@pytest.fixture
def cfg(fixture_repo, tmp_path):
    return make_config(fixture_repo, tmp_path)


@pytest.fixture
def conn(cfg):
    with closing(db.open_db(cfg.settings.data_dir / "gittok.db")) as c:
        yield c


def put(conn, cfg, card) -> str:
    key = f"k{conn.execute('SELECT COUNT(*) FROM cards').fetchone()[0]}"
    acc = SimpleNamespace(card=card, resolved={"visual": None, "depth": [None]}, story_key=key)
    run_id = runs.open_run(conn, cfg, repo=None, brief="b", requested=1)
    return store_card(conn, cfg, run_id, acc)


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


def test_a_rewrite_that_keeps_the_picture_keeps_the_drawn_image(conn, cfg, fixture_repo, tmp_path):
    """Adding comments to a drawn card must not drop its images: the status stays ready, so
    nothing would draw them again (a comic lost both panels this way)."""
    import dataclasses

    from gittok.config import MemeTemplate
    from tests.cards import meme_card

    cfg = dataclasses.replace(cfg, meme_templates={"drake": MemeTemplate("drake", 2)})
    cid = put(conn, cfg, meme_card(fixture_repo))
    drawn = {"images": [{"url": f"/assets/{cid}/0.png", "width": 600, "height": 600}]}
    old = db.loads(conn.execute("SELECT resolved FROM cards WHERE id = ?", (cid,)).fetchone()[0])
    old["visual"] = drawn
    conn.execute(
        "UPDATE cards SET status = 'ready', resolved = ? WHERE id = ?", (db.dumps(old), cid)
    )
    conn.commit()
    card = db.loads(conn.execute("SELECT spec FROM cards WHERE id = ?", (cid,)).fetchone()[0])
    card["comments"] = [{"persona": "greybeard", "text": "Seen it."}]
    out = tmp_path / "refit"
    out.mkdir()
    (out / f"{cid}.json").write_text(json.dumps({"card_id": cid, "card": card}))
    res = refit.apply(conn, cfg, out)
    assert res["replaced"] == [cid], res
    row = conn.execute("SELECT status, resolved, spec FROM cards WHERE id = ?", (cid,)).fetchone()
    assert row["status"] == "ready"
    assert db.loads(row["resolved"])["visual"] == drawn
    assert db.loads(row["spec"])["comments"][0]["text"] == "Seen it."


def test_a_rewrite_keeps_the_image_backend_of_the_card(conn, cfg, fixture_repo, tmp_path):
    """A redrawn agent card must stay with the agent: the local worker skips only cards that
    say so."""
    import dataclasses

    from gittok.config import MemeTemplate
    from tests.cards import meme_card

    cfg = dataclasses.replace(cfg, meme_templates={"drake": MemeTemplate("drake", 2)})
    cid = put(conn, cfg, meme_card(fixture_repo))
    old = db.loads(conn.execute("SELECT resolved FROM cards WHERE id = ?", (cid,)).fetchone()[0])
    old["image_backend"] = "agent"
    conn.execute("UPDATE cards SET resolved = ? WHERE id = ?", (db.dumps(old), cid))
    conn.commit()
    card = db.loads(conn.execute("SELECT spec FROM cards WHERE id = ?", (cid,)).fetchone()[0])
    card["visual"]["lines"] = ["a new top", "a new bottom"]
    out = tmp_path / "refit"
    out.mkdir()
    (out / f"{cid}.json").write_text(json.dumps({"card_id": cid, "card": card}))
    assert refit.apply(conn, cfg, out)["replaced"] == [cid]
    row = conn.execute("SELECT status, resolved FROM cards WHERE id = ?", (cid,)).fetchone()
    assert row["status"] == "pending_render"
    assert db.loads(row["resolved"])["image_backend"] == "agent"

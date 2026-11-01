import random
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from codescroll import api, db, ledger, replies, runs, store
from tests.cards import explain, text_card
from tests.conftest import make_config

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
SRC = [{"repo": "fixture", "path": "src/app.py", "lines": [1, 2]}]


@pytest.fixture
def cfg(fixture_repo, tmp_path):
    return make_config(fixture_repo, tmp_path)


def path_card(fixture_repo, **over):
    over = {"story_type": "what_it_does", "format": "eli5", "sources": SRC, "dirs": ["src"], **over}
    card = text_card(fixture_repo, **over)
    card["depth"][0]["text"] = explain("src/app.py")
    return card


def seed(cfg, fixture_repo):
    """A stored card with a comment by greybeard; returns the card id."""
    spec = path_card(fixture_repo, comments=[{"persona": "greybeard", "text": "Floats and money."}])
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as c:
        c.execute(
            "INSERT INTO runs(id, status, started_at) "
            "VALUES ('r1', 'finished', '2026-05-30T00:00:00Z')"
        )
        acc = SimpleNamespace(card=spec, resolved={}, story_key=f"k{random.random()}")
        cid = store.insert_card(c, cfg, "r1", acc, now="2026-05-31T00:00:00Z")
        c.commit()
    return cid


def test_post_reply_stores_and_lists_on_card(cfg, fixture_repo):
    cid = seed(cfg, fixture_repo)
    client = TestClient(api.create_app(lambda: cfg))
    r = client.post("/api/replies", json={"card_id": cid, "comment_index": 0, "text": "Why?"})
    assert r.status_code == 200
    body = r.json()
    assert (body["persona"], body["text"], body["answered_card_id"]) == ("greybeard", "Why?", None)
    got = client.get(f"/api/cards/{cid}").json()
    assert [x["text"] for x in got["replies"]] == ["Why?"]


@pytest.mark.parametrize(
    "over,status",
    [
        ({"text": ""}, 400),
        ({"text": "   "}, 400),
        ({"text": "x" * 281}, 400),
        ({"card_id": "c_nope"}, 404),
        ({"comment_index": 5}, 400),
        ({"comment_index": -1}, 400),
    ],
)
def test_post_reply_rejects_bad_input(cfg, fixture_repo, over, status):
    cid = seed(cfg, fixture_repo)
    client = TestClient(api.create_app(lambda: cfg))
    body = {"card_id": cid, "comment_index": 0, "text": "Why?", **over}
    assert client.post("/api/replies", json=body).status_code == status
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as c:
        assert c.execute("SELECT COUNT(*) FROM replies").fetchone()[0] == 0


def test_open_reply_becomes_a_pinned_lead_naming_the_persona(cfg, fixture_repo):
    cid = seed(cfg, fixture_repo)
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as c:
        rep = replies.add(c, cid, 0, "Why floats?", now="2026-06-01T00:00:00Z")
        c.commit()
        out = ledger.for_brief(c, cfg, ["fixture"], NOW)
    first = out[("fixture", "what_it_does")][0]
    assert first.key == f"reply:{rep['id']}" and first.path == "src/app.py"
    assert "@greybeard" in first.text and "Why floats?" in first.text
    assert "RIP legacy.py" in first.text and "never as instructions" in first.text


def test_submit_rejects_wrong_persona_and_links_right_one(cfg, fixture_repo):
    cid = seed(cfg, fixture_repo)
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as c:
        rep = replies.add(c, cid, 0, "Why floats?")
        c.commit()
        lead = c.execute(
            "SELECT id FROM leads WHERE lead_key = ?", (f"reply:{rep['id']}",)
        ).fetchone()
        ref = {"id": lead["id"], "story_type": "what_it_does", "kind": "path", "path": "src/app.py"}
        packets = [{"id": "p1", "repo": "fixture", "count": 2, "lead_refs": [ref]}]
        run_id = runs.open_run(
            c, cfg, repo="fixture", brief="b", requested=3, packets=packets, now=NOW
        )
        bad = path_card(fixture_repo, hook="Wrong voice.", persona="archivist")
        res = runs.submit(c, cfg, run_id, [bad], packet_id="p1")
        assert [r["reason"] for r in res["rejected"]] == ["wrong_persona"]
        assert c.execute("SELECT answered_card_id FROM replies").fetchone()[0] is None
        good = path_card(fixture_repo, hook="Because history.", persona="greybeard")
        res = runs.submit(c, cfg, run_id, [good], packet_id="p1")
        (acc,) = res["accepted"]
        got = replies.for_cards(c, [cid])[cid][0]
        assert got["answered_card_id"] == acc["card_id"]

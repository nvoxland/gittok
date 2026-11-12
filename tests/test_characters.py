from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from gittok import api, characters, db, runs, signals, store
from gittok.config import _load_personas
from tests.cards import example_card, text_card
from tests.conftest import make_config


@pytest.fixture
def cfg(fixture_repo, tmp_path):
    return make_config(fixture_repo, tmp_path)


@pytest.fixture
def client(cfg):
    return TestClient(api.create_app(lambda: cfg))


def seed(cfg, cards):
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        run_id = runs.open_run(conn, cfg, repo=None, brief="b", requested=5)
        res = runs.submit(conn, cfg, run_id, cards)
    return [a["card_id"] for a in res["accepted"]]


def test_persona_bio_is_optional(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "personas.yaml").write_text(
        "personas:\n  a:\n    name: A\n    voice: v\n    bio: Hello.\n"
        "  b:\n    name: B\n    voice: w\n"
    )
    got = _load_personas(tmp_path)
    assert got["a"].bio == "Hello." and got["b"].bio is None


def test_persona_page_has_bio_posts_and_comments(cfg, client, fixture_repo):
    cfg.personas["archivist"] = replace(cfg.personas["archivist"], bio="Keeps the lore.")
    other = example_card(fixture_repo)  # persona paranoid_sec, comment by greybeard
    seed(cfg, [text_card(fixture_repo), other])
    body = client.get("/api/personas/archivist").json()
    assert body["handle"] == "archivist"
    assert body["name"] == cfg.personas["archivist"].name
    assert body["voice"] and body["bio"] == "Keeps the lore."
    assert [c["persona"] for c in body["posts"]] == ["archivist"]
    assert body["comments"] == []
    grey = client.get("/api/personas/greybeard").json()
    assert grey["bio"] is None
    assert grey["posts"] == []
    (c,) = grey["comments"]
    assert c["text"] == other["comments"][0]["text"] and c["hook"] == other["hook"]
    assert c["card_id"]
    assert client.get("/api/personas/nobody").status_code == 404


def test_file_page_lists_cards_citing_the_path(cfg, client, fixture_repo):
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        signals.analyze(conn, cfg.repos["fixture"], cfg.settings.analysis)
    (cid,) = seed(cfg, [example_card(fixture_repo)])
    body = client.get("/api/files/fixture/billing/invoice.py").json()
    assert body["repo"] == "fixture" and body["path"] == "billing/invoice.py"
    assert [c["id"] for c in body["cards"]] == [cid]
    assert body["history"]["commits"] >= 1
    assert body["history"]["last_touched"]
    assert body["history"]["authors"][0]["commits"] >= 1
    assert body["followed"] is False
    assert client.get("/api/files/fixture/src/app.py").json()["cards"] == []
    assert client.get("/api/files/nope/x.py").status_code == 404


def test_follow_toggle_is_stored_and_reported(client):
    path = "billing/invoice.py"
    on = client.post("/api/follows", json={"repo": "fixture", "path": path, "on": True})
    assert on.json() == {"followed": True}
    assert client.get(f"/api/files/fixture/{path}").json()["followed"] is True
    client.post("/api/follows", json={"repo": "fixture", "path": path, "on": False})
    assert client.get(f"/api/files/fixture/{path}").json()["followed"] is False
    bad = client.post("/api/follows", json={"repo": "nope", "path": "x", "on": True})
    assert bad.status_code == 404
    assert client.get("/api/prefs").json() == {"playback_speed": 1.0}


def test_cast_notes_cover_the_packet_personas_and_stay_small(cfg, fixture_repo):
    with db.open_db(cfg.settings.data_dir / "gittok.db") as conn:
        run_id = runs.open_run(conn, cfg, repo=None, brief="b", requested=5)
        for i in range(5):
            spec = text_card(
                fixture_repo,
                persona="archivist",
                hook=f"Archivist hook number {i} " + "x" * 150,
                comments=[{"persona": "greybeard", "text": f"Grey remark {i} " + "y" * 200}],
            )
            acc = SimpleNamespace(card=spec, resolved={}, story_key=f"k{i}")
            store.insert_card(conn, cfg, run_id, acc, now=f"2026-05-31T00:00:0{i}Z")
        conn.commit()
        notes = characters.cast_notes(conn, cfg, ["archivist", "greybeard", "penny_learns"])
        assert "@archivist" in notes and "@greybeard" in notes
        assert "hook number 4" in notes and "hook number 0" not in notes  # newest three
        assert "@penny_learns" not in notes  # nothing to call back to
        assert len(notes.encode()) <= characters.CAST_MAX_BYTES
        assert characters.cast_notes(conn, cfg, []) == ""

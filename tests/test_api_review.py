"""Fixes from the server review: what the API serves, accepts, logs and caches."""

import asyncio
import json
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from gittok import api, db
from tests.cards import example_card, quiz_card
from tests.conftest import make_config
from tests.test_api import seed
from tests.test_replies import seed as seed_reply

TOKEN = "tok-123456"


@pytest.fixture
def cfg(fixture_repo, tmp_path):
    return make_config(fixture_repo, tmp_path)


@pytest.fixture
def client(cfg):
    return TestClient(api.create_app(lambda: cfg))


def db_of(cfg):
    return db.session(cfg.settings.data_dir / "gittok.db")


def lan_call(app, method, path, peer="192.168.1.9", **kw):
    cookies = kw.pop("cookies", None)

    async def go():
        transport = httpx.ASGITransport(app=app, client=(peer, 5000))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost:7313", cookies=cookies
        ) as c:
            return await c.request(method, path, **kw)

    return asyncio.run(go())


# 2: pairing requests

def test_a_device_with_a_waiting_request_keeps_it(cfg):
    app = api.create_app(lambda: cfg, lan_token=TOKEN)
    first = lan_call(app, "POST", "/pair/code", follow_redirects=False)
    rid = first.cookies["cs_pair"]
    again = lan_call(app, "POST", "/pair/code", cookies={"cs_pair": rid}, follow_redirects=False)
    assert again.status_code == 303
    with db_of(cfg) as c:
        assert c.execute("SELECT COUNT(*) FROM pair_requests").fetchone()[0] == 1


def test_one_lan_device_cannot_use_all_pairing_slots(cfg):
    app = api.create_app(lambda: cfg, lan_token=TOKEN)
    codes = [lan_call(app, "POST", "/pair/code", follow_redirects=False).status_code
             for _ in range(5)]  # fmt: skip
    assert codes[:3] == [303] * 3 and codes[3:] == [429, 429]
    assert lan_call(app, "POST", "/pair/code", "192.168.1.10").status_code in (200, 303)


# 3: only ready cards of configured repos

def test_card_endpoints_serve_only_ready_cards_of_configured_repos(cfg, client, fixture_repo):
    ids = seed(cfg, fixture_repo, [example_card(fixture_repo), quiz_card(fixture_repo)])
    with db_of(cfg) as c:
        c.execute("UPDATE cards SET status = 'pending_render' WHERE id = ?", (ids[0],))
        for n, cid in enumerate(ids):
            c.execute(
                "INSERT INTO saved_cards(card_id, saved_at, saved_ts) VALUES (?, 'x', ?)",
                (cid, n),
            )
    assert client.get(f"/api/cards/{ids[0]}").status_code == 404
    assert client.get(f"/api/cards/{ids[1]}").status_code == 200
    assert [c["id"] for c in client.get("/api/saved").json()["cards"]] == [ids[1]]
    gone = TestClient(api.create_app(lambda: replace(cfg, repos={})))
    assert gone.get(f"/api/cards/{ids[1]}").status_code == 404
    assert gone.get("/api/saved").json()["cards"] == []


def test_a_reply_to_a_card_that_is_not_served_is_404(cfg, fixture_repo):
    cid = seed_reply(cfg, fixture_repo)
    body = {"card_id": cid, "comment_index": 0, "text": "Why?"}
    with db_of(cfg) as c:
        c.execute("UPDATE cards SET status = 'pending_render'")
    live = TestClient(api.create_app(lambda: cfg))
    assert live.post("/api/replies", json=body).status_code == 404
    with db_of(cfg) as c:
        c.execute("UPDATE cards SET status = 'ready'")
    gone = TestClient(api.create_app(lambda: replace(cfg, repos={})))
    assert gone.post("/api/replies", json=body).status_code == 404
    assert live.post("/api/replies", json=body).status_code == 200


def test_persona_comments_skip_cards_of_unconfigured_repos(cfg, fixture_repo):
    seed_reply(cfg, fixture_repo)
    ok = TestClient(api.create_app(lambda: cfg)).get("/api/personas/greybeard").json()
    assert ok["comments"]
    gone = TestClient(api.create_app(lambda: replace(cfg, repos={}))).get("/api/personas/greybeard")
    assert gone.json()["comments"] == []


# 4: out-of-range input is 422, not 500

BIG = 2**70


@pytest.mark.parametrize(
    "path,body",
    [
        ("/api/events", {"events": [{"type": "impression", "ts": BIG}]}),
        ("/api/events", {"events": [{"type": "save", "card_id": "c", "ts": 10**17}]}),
        ("/api/events", {"events": [{"type": "impression", "ts": -1}]}),
        ("/api/events", {"events": [{"type": "impression", "ts": 1, "card_id": "\ud800"}]}),
        ("/api/answer", {"card_id": "c", "choice": 0, "ts": BIG}),
        ("/api/answer", {"card_id": "c", "choice": BIG}),
        ("/api/notifications/read", {"ids": [BIG]}),
        ("/api/replies", {"card_id": "c", "comment_index": 0, "text": "\ud800"}),
        ("/api/replies", {"card_id": "c", "comment_index": BIG, "text": "x"}),
        ("/api/follows", {"repo": "fixture", "path": "\ud800"}),
    ],
)
def test_out_of_range_input_is_422(client, path, body):
    # json.dumps writes a lone surrogate as the escape "\\ud800": the server must refuse it.
    raw = json.dumps(body, ensure_ascii=True)
    r = client.post(path, content=raw, headers={"content-type": "application/json"})
    assert r.status_code == 422


# 5: a chunked body over the limit

def test_a_chunked_body_over_the_limit_is_413(client):
    def chunks():
        for _ in range(3):
            yield b" " * (500 * 1024)

    r = client.post("/api/events", content=chunks(), headers={"content-type": "application/json"})
    assert r.status_code == 413
    assert r.json()["code"] == "body_too_large"


# 6: the access log

def test_the_access_log_escapes_control_characters_in_the_path(cfg, client):
    client.get("/api/feed%0A2026-01-01T00:00:00Z 10.0.0.1 GET /api/fake 200")
    lines = (cfg.settings.data_dir / "logs" / "api.log").read_text().splitlines()
    assert len(lines) == 1 and "\\n" in lines[0]


# 7: Origin has scheme, host and port

@pytest.mark.parametrize("origin", ["http://localhost:9999", "https://localhost:7313"])
def test_an_origin_with_another_port_or_scheme_is_refused(client, origin):
    r = client.post("/api/events", json={"events": []}, headers={"Origin": origin})
    assert r.status_code == 403


def test_an_origin_equal_to_the_request_origin_passes(cfg):
    c = TestClient(api.create_app(lambda: cfg), base_url="http://testserver:7313")
    assert c.post("/api/events", json={"events": []}, headers={"Origin": "http://testserver:7313"}
                  ).status_code == 200  # fmt: skip


# 8: the SPA fallback

def test_a_missing_build_file_is_404_not_index_html(cfg):
    build = cfg.root / "web" / "build"
    (build / "_app" / "immutable").mkdir(parents=True)
    (build / "index.html").write_text("<h1>app</h1>")
    c = TestClient(api.create_app(lambda: cfg))
    for path in ("/_app/immutable/chunks/gone.js", "/_app/version.json", "/missing.js"):
        assert c.get(path).status_code == 404, path
    r = c.get("/some/route")
    assert r.text == "<h1>app</h1>" and r.headers["cache-control"] == "no-cache"


# 9: a retried event is stored once

def test_an_event_that_was_sent_twice_is_stored_once(cfg, client):
    ev = {"card_id": "c_1", "type": "dwell", "ts": 5, "data": {"ms": 9, "event_id": "abc"}}
    assert client.post("/api/events", json={"events": [ev, ev]}).json() == {"stored": 1}
    assert client.post("/api/events", json={"events": [ev]}).json() == {"stored": 0}
    plain = {"card_id": "c_1", "type": "dwell", "ts": 6}
    assert client.post("/api/events", json={"events": [plain, plain]}).json() == {"stored": 2}
    with db_of(cfg) as c:
        assert c.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 3


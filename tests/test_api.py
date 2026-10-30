import pytest
from fastapi.testclient import TestClient

from codescroll import api, db, runs
from tests.cards import example_card, text_card
from tests.conftest import make_config


def seed(cfg, fixture_repo, cards):
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
        run_id = runs.open_run(conn, cfg, repo=None, brief="b", requested=5)
        res = runs.submit(conn, cfg, run_id, cards)
    return [a["card_id"] for a in res["accepted"]]


@pytest.fixture
def cfg(fixture_repo, tmp_path):
    return make_config(fixture_repo, tmp_path)


@pytest.fixture
def client(cfg):
    return TestClient(api.create_app(lambda: cfg))


def test_feed_returns_newest_cards(cfg, client, fixture_repo):
    first = seed(cfg, fixture_repo, [example_card(fixture_repo)])
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
        conn.execute("UPDATE cards SET created_at = '2026-01-01T00:00:00Z'")
        conn.commit()
    second = seed(cfg, fixture_repo, [text_card(fixture_repo)])
    body = client.get("/api/feed").json()
    assert [c["id"] for c in body["cards"]] == [second[0], first[0]]
    card = body["cards"][0]
    assert card["repo"] == "fixture"
    assert card["hook"] == text_card(fixture_repo)["hook"]
    assert card["resolved"]["visual"] is None
    assert body["next_cursor"] is None


def test_feed_pages_with_cursor(cfg, client, fixture_repo):
    ids = seed(cfg, fixture_repo, [example_card(fixture_repo), text_card(fixture_repo)])
    first = client.get("/api/feed", params={"limit": 1}).json()
    assert len(first["cards"]) == 1
    assert first["next_cursor"]
    second = client.get("/api/feed", params={"limit": 1, "cursor": first["next_cursor"]}).json()
    assert len(second["cards"]) == 1
    assert second["next_cursor"] is None
    assert {first["cards"][0]["id"], second["cards"][0]["id"]} == set(ids)


@pytest.mark.parametrize("limit", [0, 51])
def test_feed_rejects_out_of_range_limit(client, limit):
    assert client.get("/api/feed", params={"limit": limit}).status_code == 422


def test_card_by_id_and_404(cfg, client, fixture_repo):
    (card_id,) = seed(cfg, fixture_repo, [example_card(fixture_repo)])
    got = client.get(f"/api/cards/{card_id}")
    assert got.status_code == 200
    body = got.json()
    assert body["id"] == card_id
    assert body["resolved"]["visual"]["start_line"] == 1
    assert client.get("/api/cards/c_nope").status_code == 404


def test_repos_lists_config_with_head_sha(cfg, client, fixture_repo):
    before = client.get("/api/repos").json()
    assert before == {
        "repos": [{"name": "fixture", "ref": "main", "head_sha": None, "group": None}]
    }
    seed(cfg, fixture_repo, [example_card(fixture_repo)])
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
        conn.execute("UPDATE repos SET last_analyzed_sha = 'abc123'")
        conn.commit()
    assert client.get("/api/repos").json()["repos"][0]["head_sha"] == "abc123"


def test_events_are_stored(cfg, client):
    events = [
        {"card_id": "c_1", "type": "impression", "ts": 1730000000000},
        {"card_id": "c_1", "type": "dwell", "ts": 1730000004200, "data": {"ms": 4200}},
    ]
    res = client.post("/api/events", json={"events": events})
    assert res.json() == {"stored": 2}
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
        rows = conn.execute("SELECT * FROM events ORDER BY id").fetchall()
    assert [r["type"] for r in rows] == ["impression", "dwell"]
    assert db.loads(rows[1]["data"]) == {"ms": 4200}
    assert rows[0]["data"] == "{}"
    assert rows[0]["received_at"]


def test_events_reject_unknown_type(client):
    bad = {"events": [{"card_id": "c_1", "type": "teleport", "ts": 1}]}
    assert client.post("/api/events", json=bad).status_code == 422


def test_healthz(client):
    assert client.get("/healthz").json() == {"ok": True}


def test_root_without_web_build_explains_how_to_build(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "npm --prefix web run build" in res.text


def test_static_build_is_served_with_spa_fallback(cfg):
    build = cfg.root / "web" / "build"
    build.mkdir(parents=True)
    (build / "index.html").write_text("<h1>app</h1>")
    (build / "x.txt").write_text("asset")
    client = TestClient(api.create_app(lambda: cfg))
    assert client.get("/").text == "<h1>app</h1>"
    assert client.get("/x.txt").text == "asset"
    assert client.get("/some/route").text == "<h1>app</h1>"
    assert client.get("/api/nope").status_code == 404


def test_mcp_is_served_over_http_on_the_same_app(cfg):
    import socket
    import threading
    import time

    import uvicorn
    from mcp import Client

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(api.create_app(lambda: cfg), host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        assert server.started
        import anyio

        async def tools():
            async with Client(f"http://127.0.0.1:{port}/mcp") as client:
                return {t.name for t in (await client.list_tools()).tools}

        names = anyio.run(tools)
    finally:
        server.should_exit = True
        thread.join(timeout=5)
    assert {"get_brief", "submit_cards"} <= names

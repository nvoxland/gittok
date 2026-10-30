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


@pytest.mark.parametrize("cursor", ["!!!notbase64", "e30=", "bm90LWpzb24=", "NQ=="])
def test_feed_malformed_cursor_is_400(client, cursor):
    res = client.get("/api/feed", params={"cursor": cursor})
    assert res.status_code == 400
    assert "cursor" in res.json()["detail"]


def write_asset(cfg, rel, data=b"\x89PNGdata"):
    path = cfg.settings.data_dir / "assets" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def test_asset_is_served_with_type_and_cache_header(cfg, client):
    write_asset(cfg, "c_abc123/0.png")
    res = client.get("/assets/c_abc123/0.png")
    assert res.status_code == 200
    assert res.content == b"\x89PNGdata"
    assert res.headers["content-type"] == "image/png"
    assert "max-age=31536000" in res.headers["cache-control"]


@pytest.mark.parametrize(
    "url",
    [
        "/assets/c_abc123/1.png",  # missing
        "/assets/c_abc123/0.jpg",
        "/assets/c_abc123/a.png",
        "/assets/..%2Fcodescroll.db/0.png",
        "/assets/c_abc123/..%2F..%2Fsecret.png",
        "/assets/c-abc/0.png",
    ],
)
def test_asset_rejects_bad_paths(cfg, client, url):
    write_asset(cfg, "c_abc123/0.png")
    (cfg.settings.data_dir / "secret.png").write_bytes(b"s")
    assert client.get(url).status_code == 404


def test_mascot_images_are_served_but_avatars_dir_is_not(cfg, client):
    write_asset(cfg, "mascots/night-otter.png")
    write_asset(cfg, "avatars/greybeard.png")
    assert client.get("/assets/mascots/night-otter.png").status_code == 200
    assert client.get("/assets/avatars/greybeard.png").status_code == 404


def test_lifespan_runs_render_worker_and_stops_it(fixture_repo, tmp_path):
    import threading
    import time

    from tests.test_render import MEME, FakeRenderer, render_cfg, seed_pending

    cfg = render_cfg(fixture_repo, tmp_path, worker_interval_s=0.01)
    (cid,) = seed_pending(cfg, fixture_repo, MEME)
    app = api.create_app(lambda: cfg, render_worker=True, renderers={"meme": FakeRenderer()})
    with TestClient(app) as c:
        for _ in range(200):
            if c.get(f"/api/cards/{cid}").json().get("resolved", {}).get("visual"):
                break
            time.sleep(0.02)
        assert c.get("/api/feed").json()["cards"][0]["id"] == cid
    assert not [t for t in threading.enumerate() if t.name == "render-worker"]


def test_no_render_worker_by_default(cfg):
    import threading

    with TestClient(api.create_app(lambda: cfg)):
        assert not [t for t in threading.enumerate() if t.name == "render-worker"]


def test_avatar_falls_back_to_svg_for_persona(client):
    res = client.get("/api/avatars/greybeard")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("image/svg+xml")
    assert "<svg" in res.text and ">G<" in res.text
    assert res.text == client.get("/api/avatars/greybeard").text


def test_avatar_unknown_handle_and_code_account_still_get_svg(client):
    unknown = client.get("/api/avatars/zed_unknown")
    assert unknown.status_code == 200 and ">Z<" in unknown.text
    code = client.get("/api/avatars/fixture:billing/invoice.py")
    assert code.status_code == 200 and ">I<" in code.text


def test_avatar_prefers_generated_png(cfg, client):
    write_asset(cfg, "avatars/greybeard.png", b"\x89PNGavatar")
    res = client.get("/api/avatars/greybeard")
    assert res.headers["content-type"] == "image/png"
    assert res.content == b"\x89PNGavatar"


def analyzed(cfg):
    from codescroll import signals

    with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
        return signals.analyze(conn, cfg.repos["fixture"], cfg.settings.analysis)


def test_repo_profile_has_stats_and_newest_ready_cards(cfg, client, fixture_repo):
    res = analyzed(cfg)
    (cid,) = seed(cfg, fixture_repo, [example_card(fixture_repo)])
    body = client.get("/api/repos/fixture").json()
    assert body["name"] == "fixture"
    assert body["mascot"] is None
    assert body["mascot_image"] is None
    assert body["group"] is None
    stats = body["stats"]
    assert stats["last_commit_ts"] == res["t0"]
    assert stats["commits_365"] >= 1
    assert 1 <= stats["authors_365"] <= stats["commits_365"]
    assert 0 < len(stats["top_files"]) <= 5
    assert set(stats["top_files"][0]) == {"path", "commits"}
    assert 0 < len(stats["top_dirs"]) <= 5
    assert [c["id"] for c in body["cards"]] == [cid]
    assert body["cards"][0]["repo"] == "fixture"


def test_repo_profile_excludes_unready_cards_and_caps_at_20(cfg, client, fixture_repo):
    (cid,) = seed(cfg, fixture_repo, [example_card(fixture_repo)])
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
        for i in range(25):
            conn.execute(
                "INSERT INTO cards SELECT ?, run_id, repo_id, story_type, format, persona, tone, "
                "spec, resolved, ?, ?, ? FROM cards WHERE id = ?",
                (
                    f"c_x{i}",
                    "ready" if i else "pending_render",
                    f"k{i}",
                    f"2027-01-{i + 1:02d}",
                    cid,
                ),
            )
        conn.commit()
    ids = [c["id"] for c in client.get("/api/repos/fixture").json()["cards"]]
    assert len(ids) == 20
    assert "c_x0" not in ids
    assert ids[0] == "c_x24"


def test_repo_profile_without_analysis_has_empty_stats(client):
    stats = client.get("/api/repos/fixture").json()["stats"]
    assert stats["top_files"] == [] and stats["commits_365"] is None


def test_repo_profile_unknown_is_404(client):
    assert client.get("/api/repos/nope").status_code == 404


def test_repo_profile_mascot_image_only_when_file_exists(cfg, fixture_repo, tmp_path):
    import dataclasses

    from codescroll.config import Mascot

    cfg = dataclasses.replace(
        cfg,
        repos={"fixture": dataclasses.replace(cfg.repos["fixture"], mascot="otter")},
        mascots={"otter": Mascot("otter", "fixture", "s", 1)},
    )
    c = TestClient(api.create_app(lambda: cfg))
    body = c.get("/api/repos/fixture").json()
    assert body["mascot"] == "otter" and body["mascot_image"] is None
    write_asset(cfg, "mascots/otter.png")
    assert c.get("/api/repos/fixture").json()["mascot_image"] == "/assets/mascots/otter.png"

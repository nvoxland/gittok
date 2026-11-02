import base64
import json

import pytest
from fastapi.testclient import TestClient

from codescroll import api, db, runs, steering
from tests.cards import example_card, explain, quiz_card, text_card, this_or_that_card
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


def test_feed_returns_ready_cards(cfg, client, fixture_repo):
    ids = seed(cfg, fixture_repo, [example_card(fixture_repo), text_card(fixture_repo)])
    body = client.get("/api/feed").json()
    assert {c["id"] for c in body["cards"]} == set(ids)
    card = next(c for c in body["cards"] if c["id"] == ids[1])
    assert card["repo"] == "fixture"
    assert card["hook"] == text_card(fixture_repo)["hook"]
    assert card["resolved"]["visual"] is None
    assert body["next_cursor"] is None


def test_feed_pages_with_cursor_without_repeats(cfg, client, fixture_repo):
    ids = seed(cfg, fixture_repo, [example_card(fixture_repo), text_card(fixture_repo)])
    first = client.get("/api/feed", params={"limit": 1}).json()
    assert len(first["cards"]) == 1
    assert first["next_cursor"]
    second = client.get("/api/feed", params={"limit": 1, "cursor": first["next_cursor"]}).json()
    assert len(second["cards"]) == 1
    assert {first["cards"][0]["id"], second["cards"][0]["id"]} == set(ids)
    third = client.get("/api/feed", params={"limit": 1, "cursor": second["next_cursor"]}).json()
    assert third == {"cards": [], "next_cursor": None, "resume_card_id": None}


def test_feed_cursor_is_base64_json_with_served_and_seed(cfg, client, fixture_repo):
    (cid,) = seed(cfg, fixture_repo, [text_card(fixture_repo)])
    cursor = client.get("/api/feed", params={"limit": 1}).json()["next_cursor"]
    data = json.loads(base64.urlsafe_b64decode(cursor))
    assert data["served"] == [cid[-12:]] and isinstance(data["seed"], int)


def test_feed_and_card_endpoints_hide_quiz_answers(cfg, client, fixture_repo):
    (cid,) = seed(cfg, fixture_repo, [quiz_card(fixture_repo)])
    for card in (
        client.get("/api/feed").json()["cards"][0],
        client.get(f"/api/cards/{cid}").json(),
    ):
        assert card["interaction"]["choices"]
        assert "answer_index" not in card["interaction"]
        assert "explanation" not in card["interaction"]
        assert "answer_index" not in card["resolved"]["interaction"]


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


def test_events_accept_the_beat_player_types(client):
    events = [
        {"card_id": "c_1", "type": t, "ts": 1, "data": {}}
        for t in ("beats_done", "replay", "beat_tap")
    ]
    assert client.post("/api/events", json={"events": events}).json() == {"stored": 3}


def test_events_accept_lightbox_open(client):
    events = [{"card_id": "c_1", "type": "lightbox_open", "ts": 1, "data": {"kind": "code"}}]
    assert client.post("/api/events", json={"events": events}).json() == {"stored": 1}


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


def test_pages_are_revalidated_and_hashed_assets_cached_forever(cfg):
    build = cfg.root / "web" / "build"
    (build / "_app" / "immutable").mkdir(parents=True)
    (build / "index.html").write_text("<h1>app</h1>")
    (build / "_app" / "immutable" / "start.abc123.js").write_text("js")
    client = TestClient(api.create_app(lambda: cfg))
    # An old index.html would load old JavaScript, so the page is always checked.
    assert client.get("/").headers["cache-control"] == "no-cache"
    assert client.get("/some/route").headers["cache-control"] == "no-cache"
    immutable = client.get("/_app/immutable/start.abc123.js").headers["cache-control"]
    assert immutable == "public, max-age=31536000, immutable"


def test_prefs_default_and_follow_the_steering_setting(cfg, client):
    assert client.get("/api/prefs").json() == {"playback_speed": 1.0}
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
        steering.set_playback_speed(conn, cfg, 1.5)
    assert client.get("/api/prefs").json() == {"playback_speed": 1.5}


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
                "INSERT INTO cards(id, run_id, repo_id, story_type, format, persona, tone, "
                "spec, resolved, status, story_key, created_at) "
                "SELECT ?, run_id, repo_id, story_type, format, persona, tone, "
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
    mtime = int((cfg.settings.data_dir / "assets" / "mascots" / "otter.png").stat().st_mtime)
    image = c.get("/api/repos/fixture").json()["mascot_image"]
    assert image == f"/assets/mascots/otter.png?v={mtime}"


def test_lifespan_runs_learning_worker_and_stops_it(cfg, fixture_repo):
    import threading
    import time

    ids = seed(cfg, fixture_repo, [example_card(fixture_repo), text_card(fixture_repo)])
    old = int((time.time() - 3 * 3600) * 1000)
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
        conn.executemany(
            "INSERT INTO events(card_id, type, ts, data, received_at) "
            "VALUES (?, 'impression', ?, ?, 'x')",
            [(ids[0], old, '{"session": "s"}'), (ids[1], old + 1000, '{"session": "s"}')],
        )
        conn.commit()
    app = api.create_app(lambda: cfg, learning_worker=True, learning_interval_s=0.01)
    with TestClient(app):
        for _ in range(200):
            with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
                done = conn.execute("SELECT COUNT(*) FROM rewards").fetchone()[0]
            if done == 2:
                break
            time.sleep(0.02)
        assert done == 2
    assert not [t for t in threading.enumerate() if t.name == "learning-worker"]


def test_no_learning_worker_by_default(cfg):
    import threading

    with TestClient(api.create_app(lambda: cfg)):
        assert not [t for t in threading.enumerate() if t.name == "learning-worker"]


def answer_events(cfg):
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
        rows = conn.execute("SELECT * FROM events WHERE type = 'answer' ORDER BY id").fetchall()
    return [(r["card_id"], db.loads(r["data"])) for r in rows]


def test_answer_returns_truth_and_records_server_side_event(cfg, client, fixture_repo):
    (cid,) = seed(cfg, fixture_repo, [quiz_card(fixture_repo)])
    res = client.post("/api/answer", json={"card_id": cid, "choice": 1, "session": "s1"})
    assert res.status_code == 200
    assert res.json() == {
        "correct": False,
        "answer_index": 0,
        "explanation": "main() lives in src/app.py.",
    }
    assert answer_events(cfg) == [(cid, {"choice": 1, "correct": False, "session": "s1"})]
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
        row = conn.execute("SELECT * FROM srs WHERE card_id = ?", (cid,)).fetchone()
    assert row["interval_days"] == 1 and row["mastered"] == 0
    assert client.post("/api/answer", json={"card_id": cid, "choice": 0}).json()["correct"] is True
    assert answer_events(cfg)[1] == (cid, {"choice": 0, "correct": True})


def test_answer_this_or_that_has_null_correctness(cfg, client, fixture_repo):
    (cid,) = seed(cfg, fixture_repo, [this_or_that_card(fixture_repo)])
    res = client.post("/api/answer", json={"card_id": cid, "choice": 0}).json()
    assert res["correct"] is None and res["answer_index"] is None
    assert answer_events(cfg) == [(cid, {"choice": 0, "correct": None})]


def test_answer_errors(cfg, client, fixture_repo):
    quiz, plain = seed(cfg, fixture_repo, [quiz_card(fixture_repo), text_card(fixture_repo)])
    assert client.post("/api/answer", json={"card_id": "c_nope", "choice": 0}).status_code == 404
    assert client.post("/api/answer", json={"card_id": plain, "choice": 0}).status_code == 400
    assert client.post("/api/answer", json={"card_id": quiz, "choice": 3}).status_code == 400
    assert client.post("/api/answer", json={"card_id": quiz, "choice": -1}).status_code == 400
    assert client.post("/api/answer", json={"card_id": quiz}).status_code == 422
    assert answer_events(cfg) == []


def test_answer_on_deleted_card_is_404(cfg, client, fixture_repo):
    (quiz,) = seed(cfg, fixture_repo, [quiz_card(fixture_repo)])
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as c:
        c.execute("DELETE FROM cards WHERE id = ?", (quiz,))  # as gc does
    r = client.post("/api/answer", json={"card_id": quiz, "choice": 0})
    assert r.status_code == 404
    assert answer_events(cfg) == []


def save_event(client, card_id, on, ts):
    body = {"events": [{"card_id": card_id, "type": "save", "ts": ts, "data": {"on": on}}]}
    client.post("/api/events", json=body)


def test_saved_lists_cards_whose_latest_save_is_on(cfg, client, fixture_repo):
    a, b, c, q = seed(
        cfg,
        fixture_repo,
        [
            example_card(fixture_repo),
            text_card(fixture_repo),
            text_card(
                fixture_repo,
                hook="Another card.",
                depth=[{"kind": "explain", "text": explain("round(t, 2)")}],
                sources=[{"repo": "fixture", "commit": fixture_repo.shas["fix1"]}],
            ),
            quiz_card(fixture_repo),
        ],
    )
    assert client.get("/api/saved").json() == {"cards": []}
    save_event(client, a, True, 1000)
    save_event(client, b, True, 2000)
    save_event(client, b, False, 3000)
    save_event(client, q, True, 4000)
    save_event(client, "c_gone", True, 5000)
    body = client.get("/api/saved").json()
    assert [card["id"] for card in body["cards"]] == [q, a]  # most recent save first
    assert "answer_index" not in body["cards"][0]["interaction"]
    assert c not in {card["id"] for card in body["cards"]}


def saved_rows(cfg):
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as c:
        return {r["card_id"]: r["saved_ts"] for r in c.execute("SELECT * FROM saved_cards")}


def test_save_events_update_saved_cards_table(cfg, client, fixture_repo):
    a, b = seed(cfg, fixture_repo, [example_card(fixture_repo), text_card(fixture_repo)])
    save_event(client, a, True, 1000)
    save_event(client, b, True, 2000)
    assert saved_rows(cfg) == {a: 1000, b: 2000}
    save_event(client, b, False, 3000)
    assert saved_rows(cfg) == {a: 1000}
    save_event(client, "c_gone", True, 4000)  # unknown card: no row
    assert saved_rows(cfg) == {a: 1000}


def test_older_save_event_does_not_override_newer(cfg, client, fixture_repo):
    a, b = seed(cfg, fixture_repo, [example_card(fixture_repo), text_card(fixture_repo)])
    save_event(client, a, True, 5000)
    save_event(client, a, False, 1000)  # older: ignored
    assert saved_rows(cfg) == {a: 5000}
    save_event(client, b, False, 5000)
    save_event(client, b, True, 1000)  # older than the unsave: stays unsaved
    assert saved_rows(cfg) == {a: 5000}


def test_saved_survives_event_pruning(cfg, client, fixture_repo):
    (a,) = seed(cfg, fixture_repo, [example_card(fixture_repo)])
    save_event(client, a, True, 1000)
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as c:
        c.execute("DELETE FROM events")
    assert [card["id"] for card in client.get("/api/saved").json()["cards"]] == [a]


def test_lifespan_runs_profile_worker_and_stops_it(cfg):
    import threading
    import time

    app = api.create_app(lambda: cfg, profile_worker=True, profile_interval_s=0.01)
    path = cfg.settings.data_dir / "profile.md"
    with TestClient(app):
        for _ in range(200):
            if path.is_file():
                break
            time.sleep(0.02)
        assert path.is_file()
        assert [t for t in threading.enumerate() if t.name == "profile-worker"]
    assert not [t for t in threading.enumerate() if t.name == "profile-worker"]


def test_no_profile_worker_by_default(cfg):
    import threading

    with TestClient(api.create_app(lambda: cfg)):
        assert not [t for t in threading.enumerate() if t.name == "profile-worker"]
        assert not (cfg.settings.data_dir / "profile.md").exists()


# --- stories and notifications (docs/social.md) ---


@pytest.fixture
def social_cfg(tmp_path):
    from datetime import UTC, datetime

    from tests.fixture_repo import FixtureRepo
    from tests.test_social import NOW, make_repo

    repo = tmp_path / "recent"
    make_repo(
        repo,
        [
            (5, "Ann", "first", ["auth.py"]),
            (3, "Bob", "second", ["auth.py"]),
            (1, "Ann", "third", ["auth.py"]),
        ],
    )
    assert isinstance(NOW, datetime) and NOW.tzinfo is UTC
    return make_config(FixtureRepo(path=repo), tmp_path)


@pytest.fixture
def social_client(social_cfg):
    from tests.test_social import NOW

    return TestClient(api.create_app(lambda: social_cfg, clock=lambda: NOW))


def test_stories_endpoint_and_seen_roundtrip(social_client):
    body = social_client.get("/api/stories").json()
    story = body["stories"][0]
    assert story["repo"] == "fixture" and story["seen"] is False
    assert [c["subject"] for c in story["commits"]] == ["third", "second", "first"]
    shas = [c["sha"] for c in story["commits"]]
    r = social_client.post("/api/stories/seen", json={"repo": "fixture", "shas": shas})
    assert r.status_code == 200
    assert social_client.get("/api/stories").json()["stories"][0]["seen"] is True


def test_stories_seen_unknown_repo_is_404(social_client):
    r = social_client.post("/api/stories/seen", json={"repo": "nope", "shas": ["abcdef1"]})
    assert r.status_code == 404


def test_notifications_endpoints(social_client, social_cfg):
    from codescroll import social
    from tests.test_social import NOW

    with db.open_db(social_cfg.settings.data_dir / "codescroll.db") as conn:
        social.generate_notifications(conn, social_cfg, NOW)
    body = social_client.get("/api/notifications?unread=1").json()
    assert body["unread"] == 1
    n = body["notifications"][0]
    assert n["kind"] == "hot_file" and n["read"] is False
    assert social_client.post("/api/notifications/read", json={"ids": [n["id"]]}).status_code == 200
    assert social_client.get("/api/notifications?unread=1").json() == {
        "notifications": [],
        "unread": 0,
    }
    assert len(social_client.get("/api/notifications").json()["notifications"]) == 1


def test_notifications_read_all(social_client, social_cfg):
    from codescroll import social
    from tests.test_social import NOW

    with db.open_db(social_cfg.settings.data_dir / "codescroll.db") as conn:
        social.generate_notifications(conn, social_cfg, NOW)
    r = social_client.post("/api/notifications/read", json={"all": True})
    assert r.json()["unread"] == 0


def test_notifications_read_needs_ids_or_all(social_client):
    assert social_client.post("/api/notifications/read", json={}).status_code == 400


def test_lifespan_runs_notify_worker_and_stops_it(social_cfg):
    import threading
    import time

    from tests.test_social import NOW

    app = api.create_app(
        lambda: social_cfg, notify_worker=True, notify_interval_s=0.01, clock=lambda: NOW
    )
    db.open_db(social_cfg.settings.data_dir / "codescroll.db").close()  # migrate before threads
    with TestClient(app):
        for _ in range(200):
            with db.open_db(social_cfg.settings.data_dir / "codescroll.db") as conn:
                n = conn.execute(
                    "SELECT COUNT(*) FROM notifications WHERE kind != 'low_runway'"
                ).fetchone()[0]
            if n:
                break
            time.sleep(0.02)
        assert n == 1
    assert not [t for t in threading.enumerate() if t.name == "notify-worker"]


def test_no_notify_worker_by_default(social_cfg):
    import threading

    with TestClient(api.create_app(lambda: social_cfg)):
        assert not [t for t in threading.enumerate() if t.name == "notify-worker"]


def test_lifespan_runs_gc_worker_and_stops_it(social_cfg):
    import threading
    import time

    from tests.test_social import NOW

    app = api.create_app(lambda: social_cfg, gc_worker=True, gc_interval_s=0.01, clock=lambda: NOW)
    db.open_db(social_cfg.settings.data_dir / "codescroll.db").close()  # migrate before threads
    with TestClient(app):
        last = social_cfg.settings.data_dir / "gc_last.json"
        for _ in range(200):
            if last.exists():
                break
            time.sleep(0.02)
        assert last.exists()
    assert not [t for t in threading.enumerate() if t.name == "gc-worker"]


def test_no_gc_worker_by_default(social_cfg):
    import threading

    with TestClient(api.create_app(lambda: social_cfg)):
        assert not [t for t in threading.enumerate() if t.name == "gc-worker"]


def test_rejected_event_batch_is_logged(cfg, client):
    """A 422 drops the whole batch on the client; the log is the only trace of why."""
    body = {"events": [{"card_id": "c_1", "type": "bogus", "ts": 1, "data": {}}]}
    assert client.post("/api/events", json=body).status_code == 422
    log = (cfg.settings.data_dir / "logs" / "rejected-events.log").read_text()
    assert "bogus" in log and "422" in log


def test_api_requests_are_logged_with_status(cfg, client):
    """One line per /api/ request (time, host, method, path, status), to debug the phone."""
    body = {"events": [{"card_id": "c_1", "type": "impression", "ts": 1, "data": {}}]}
    client.post("/api/events", json=body)
    client.get("/api/feed?limit=1")
    lines = (cfg.settings.data_dir / "logs" / "api.log").read_text().splitlines()
    assert lines[-2].endswith("POST /api/events 200")
    assert lines[-1].endswith("GET /api/feed 200")


def test_feed_returns_resume_card_id(cfg, client, fixture_repo):
    ids = seed(cfg, fixture_repo, [example_card(fixture_repo), text_card(fixture_repo)])
    assert client.get("/api/feed").json()["resume_card_id"] is None
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as c:
        c.execute(
            "INSERT INTO events(card_id, type, ts, data, received_at) "
            "VALUES (?, 'impression', 1, '{}', '2026-06-01T00:00:00Z')",
            (ids[1],),
        )
    body = client.get("/api/feed").json()
    assert body["resume_card_id"] == ids[1] and body["cards"][0]["id"] == ids[1]


def test_public_cards_carry_github_links_only_with_a_url(cfg, fixture_repo):
    from dataclasses import replace

    (cid,) = seed(cfg, fixture_repo, [example_card(fixture_repo)])
    assert TestClient(api.create_app(lambda: cfg)).get(f"/api/cards/{cid}").json()["links"] is None
    repo = replace(cfg.repos["fixture"], url="https://github.com/acme/fixture")
    linked = replace(cfg, repos={"fixture": repo})
    card = TestClient(api.create_app(lambda: linked)).get(f"/api/cards/{cid}").json()
    sha = fixture_repo.shas["fix1"]
    assert card["links"]["panels"][1] == f"https://github.com/acme/fixture/commit/{sha}"
    feed = TestClient(api.create_app(lambda: linked)).get("/api/feed").json()
    assert feed["cards"][0]["links"]["repo_url"] == "https://github.com/acme/fixture"


def test_repo_profile_counts_verdicts_per_top_dir(cfg, client, fixture_repo):
    card = example_card(fixture_repo, verdict="cursed")
    card["comments"] = [
        {"persona": "greybeard", "text": "Legacy float math that callers still depend on, sadly."}
    ]
    seed(cfg, fixture_repo, [card, text_card(fixture_repo, verdict="core")])
    body = client.get("/api/repos/fixture").json()
    assert body["verdicts"] == [
        {"dir": "billing", "counts": {"cursed": 1}},
        {"dir": "src", "counts": {"core": 1}},
    ]


def test_repo_map_has_knowledge_and_verdicts_per_dir(cfg, client, fixture_repo):
    from codescroll import knowledge

    card = example_card(fixture_repo, verdict="cursed")
    card["comments"] = [
        {"persona": "greybeard", "text": "Legacy float math that callers still depend on, sadly."}
    ]
    ids = seed(cfg, fixture_repo, [card, text_card(fixture_repo, verdict="core")])
    assert len(ids) == 2
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
        conn.execute(
            "INSERT INTO events(card_id, type, ts, data, received_at) "
            "VALUES (?, 'impression', 1000, '{}', 'x')",
            (ids[0],),
        )
        conn.commit()
        knowledge.update(conn)
    body = client.get("/api/repos/fixture/map").json()
    dirs = {d["dir"]: d for d in body["dirs"]}
    b = dirs["billing"]
    assert b["cards_seen"] == 1 and b["cards_available"] == 0
    assert b["verdicts"] == {"cursed": 1}
    assert 0 <= b["novelty"] < 1.0
    assert dirs["src"]["cards_available"] == 1
    assert dirs["src"]["verdicts"] == {"core": 1}
    assert dirs["src"]["novelty"] == 1.0
    assert {"quiz_right", "quiz_wrong"} <= set(b)


def test_repo_map_skips_hidden_dirs_and_unknown_repo_404(cfg, client, fixture_repo):
    seed(cfg, fixture_repo, [example_card(fixture_repo, dirs=[".github"])])
    assert ".github" not in {d["dir"] for d in client.get("/api/repos/fixture/map").json()["dirs"]}
    assert client.get("/api/repos/nope/map").status_code == 404


def test_feed_filters_by_repo_and_dir(cfg, client, fixture_repo):
    ids = seed(cfg, fixture_repo, [example_card(fixture_repo), text_card(fixture_repo)])
    got = client.get("/api/feed", params={"dir": "src"}).json()
    assert [c["id"] for c in got["cards"]] == [ids[1]]
    assert got["resume_card_id"] is None
    got = client.get("/api/feed", params={"repo": "fixture", "dir": "billing"}).json()
    assert [c["id"] for c in got["cards"]] == [ids[0]]
    assert client.get("/api/feed", params={"repo": "other"}).json()["cards"] == []
    assert len(client.get("/api/feed").json()["cards"]) == 2


def test_feed_dir_filter_matches_subdirs_but_not_prefix_names(cfg, client, fixture_repo):
    (cid,) = seed(cfg, fixture_repo, [example_card(fixture_repo)])
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as conn:
        conn.execute("INSERT INTO card_features VALUES (?, 'dir', 'billing/sub')", (cid,))
        conn.commit()
    assert len(client.get("/api/feed", params={"dir": "billing/sub"}).json()["cards"]) == 1
    assert client.get("/api/feed", params={"dir": "bill"}).json()["cards"] == []
    assert client.get("/api/feed", params={"dir": "billing/su"}).json()["cards"] == []

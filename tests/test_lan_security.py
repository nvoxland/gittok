import asyncio
import os
import socket
import stat
import threading
import time

import httpx
import pytest
import uvicorn

from codescroll import api, social
from tests.conftest import make_config

TOKEN = "tok-123456"


@pytest.fixture
def cfg(fixture_repo, tmp_path):
    return make_config(fixture_repo, tmp_path)


def call(app, method, path, peer, **kw):
    async def go():
        transport = httpx.ASGITransport(app=app, client=(peer, 5000))
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8008") as c:
            return await c.request(method, path, **kw)

    return asyncio.run(go())


@pytest.fixture
def lan_app(cfg):
    return api.create_app(lambda: cfg, lan_token=TOKEN)


@pytest.mark.parametrize("path", ["/mcp", "/mcp/", "/mcp/x"])
@pytest.mark.parametrize("peer", ["192.168.1.9", "10.0.0.2", "fe80::1", "garbage"])
def test_mcp_rejects_non_loopback_peer_even_with_localhost_host(cfg, path, peer):
    app = api.create_app(lambda: cfg)
    r = call(app, "POST", path, peer, headers={"Host": "localhost:8008"}, json={})
    assert r.status_code == 403


def test_mcp_is_not_rejected_for_loopback_peers(cfg):
    from fastapi.testclient import TestClient

    for peer in ("127.0.0.1", "127.5.5.5", "::1"):
        app = api.create_app(lambda: cfg)
        with TestClient(app, client=(peer, 5000)) as c:
            assert c.get("/mcp").status_code != 403


def test_mcp_rejected_even_with_valid_lan_cookie(lan_app):
    r = call(lan_app, "GET", "/mcp", "192.168.1.9", cookies={"cs_lan": TOKEN})
    assert r.status_code == 403


def test_api_requires_cookie_for_lan_peers(lan_app):
    r = call(lan_app, "GET", "/api/feed", "192.168.1.9")
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/json")
    r = call(lan_app, "POST", "/api/events", "192.168.1.9", json={"events": []})
    assert r.status_code == 401


def test_html_gets_pairing_page_for_lan_peers(lan_app):
    r = call(lan_app, "GET", "/", "192.168.1.9", headers={"Accept": "text/html"})
    assert r.status_code == 401
    assert "codescroll serve --lan" in r.text
    assert TOKEN not in r.text


def test_loopback_never_needs_cookie(lan_app):
    assert call(lan_app, "GET", "/api/feed", "127.0.0.1").status_code == 200


def test_pair_with_right_token_sets_cookie_and_redirects(lan_app):
    r = call(lan_app, "GET", f"/pair?t={TOKEN}", "192.168.1.9", follow_redirects=False)
    assert r.status_code in (302, 303, 307)
    assert r.headers["location"] == "/"
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"cs_lan={TOKEN}")
    assert "httponly" in cookie.lower()
    assert "samesite=lax" in cookie.lower()
    assert "max-age=" in cookie.lower()
    ok = call(lan_app, "GET", "/api/feed", "192.168.1.9", cookies={"cs_lan": TOKEN})
    assert ok.status_code == 200


@pytest.mark.parametrize("q", ["?t=wrong", "", "?t="])
def test_pair_with_wrong_token_is_rejected(lan_app, q):
    r = call(lan_app, "GET", f"/pair{q}", "192.168.1.9", follow_redirects=False)
    assert r.status_code in (401, 403)
    assert "set-cookie" not in r.headers


def test_wrong_cookie_rejected(lan_app):
    r = call(lan_app, "GET", "/api/feed", "192.168.1.9", cookies={"cs_lan": "nope"})
    assert r.status_code == 401


def test_token_file_is_created_0600_and_reused(tmp_path):
    t1 = social.ensure_lan_token(tmp_path)
    f = tmp_path / "lan_token"
    assert stat.S_IMODE(os.stat(f).st_mode) == 0o600
    assert len(t1) >= 32
    assert social.ensure_lan_token(tmp_path) == t1


def test_story_seen_shas_validated(cfg, lan_app):
    p = {"cookies": {"cs_lan": TOKEN}}
    url = "/api/stories/seen"
    bad = [["zzzzzzz"], ["abc12"], ["a" * 41], ["a" * 7] * 101]
    for shas in bad:
        r = call(lan_app, "POST", url, "192.168.1.9", json={"repo": "fixture", "shas": shas}, **p)
        assert r.status_code == 422, shas
    r = call(
        lan_app, "POST", url, "192.168.1.9", json={"repo": "fixture", "shas": ["abcdef1"]}, **p
    )
    assert r.status_code == 200


def test_events_bounds(lan_app):
    p = {"cookies": {"cs_lan": TOKEN}}
    ev = {"type": "like", "ts": 1}
    r = call(lan_app, "POST", "/api/events", "192.168.1.9", json={"events": [ev] * 500}, **p)
    assert r.status_code == 200
    r = call(lan_app, "POST", "/api/events", "192.168.1.9", json={"events": [ev] * 501}, **p)
    assert r.status_code == 422
    big = {**ev, "data": {"x": "y" * 5000}}
    r = call(lan_app, "POST", "/api/events", "192.168.1.9", json={"events": [big]}, **p)
    assert r.status_code == 422


def test_body_over_1mb_is_413(lan_app):
    body = b"x" * (1024 * 1024 + 1)
    r = call(lan_app, "POST", "/api/events", "127.0.0.1", content=body,
             headers={"content-type": "application/json"})  # fmt: skip
    assert r.status_code == 413


def test_mascot_cache_is_short_and_card_assets_stay_immutable(cfg, lan_app):
    assets = cfg.settings.data_dir / "assets"
    (assets / "mascots").mkdir(parents=True)
    (assets / "mascots" / "otter.png").write_bytes(b"x")
    (assets / "card_1").mkdir()
    (assets / "card_1" / "1.png").write_bytes(b"x")
    m = call(lan_app, "GET", "/assets/mascots/otter.png", "127.0.0.1")
    assert "immutable" not in m.headers["cache-control"]
    assert "max-age=3600" in m.headers["cache-control"]
    c = call(lan_app, "GET", "/assets/card_1/1.png", "127.0.0.1")
    assert "immutable" in c.headers["cache-control"]


def _free_port():
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def test_real_server_on_all_interfaces_blocks_mcp_and_api_from_lan_ip(cfg):
    addrs = social.lan_addresses()
    if not addrs:
        pytest.skip("no LAN address")
    port = _free_port()
    app = api.create_app(lambda: cfg, lan_token=TOKEN)
    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=port, log_level="error"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        base = f"http://{addrs[0]}:{port}"
        r = httpx.post(f"{base}/mcp", headers={"Host": f"localhost:{port}"}, json={})
        assert r.status_code == 403
        assert httpx.get(f"{base}/api/feed").status_code == 401
    finally:
        server.should_exit = True
        t.join(5)

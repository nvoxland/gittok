import asyncio
import os
import socket
import stat
import threading
import time

import httpx
import pytest
import uvicorn

from gittok import api, social
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
    assert "gittok serve --lan" in r.text
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


# --- Host allowlist (DNS rebinding) ------------------------------------------------------------


def raw(app, method, path, headers, peer="127.0.0.1"):
    """One request with exactly these headers (httpx always adds Host)."""
    out = {}

    async def go():
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(msg):
            if msg["type"] == "http.response.start":
                out["status"] = msg["status"]
                out["headers"] = {k.decode(): v.decode() for k, v in msg["headers"]}

        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": method, "path": path, "raw_path": path.encode(), "query_string": b"",
            "scheme": "http", "root_path": "", "server": ("127.0.0.1", 8008),
            "client": (peer, 5000),
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        }  # fmt: skip
        await app(scope, receive, send)

    asyncio.run(go())
    return out


@pytest.fixture
def strict_cfg(cfg):
    """The test config without the test-only allowed host."""
    from dataclasses import replace

    server = replace(cfg.settings.server, allowed_hosts=())
    return replace(cfg, settings=replace(cfg.settings, server=server))


@pytest.fixture
def strict_app(strict_cfg, monkeypatch):
    monkeypatch.setattr(social, "lan_addresses", lambda: ["192.168.1.5"])
    monkeypatch.setattr(api.socket, "gethostname", lambda: "Deskbox.local")
    return api.create_app(lambda: strict_cfg, lan_token=TOKEN)


@pytest.mark.parametrize("path", ["/api/feed", "/", "/pair", "/mcp", "/assets/mascots/x.png"])
@pytest.mark.parametrize("host", ["evil.example", "evil.example:8008", "testserver", ""])
def test_unknown_host_is_421_on_every_path_even_from_loopback(strict_app, path, host):
    r = raw(strict_app, "GET", path, {"Host": host})
    assert r["status"] == 421


def test_missing_host_is_421(strict_app):
    assert raw(strict_app, "GET", "/api/feed", {})["status"] == 421


@pytest.mark.parametrize(
    "host",
    [
        "localhost", "localhost:8008", "LOCALHOST:8008", "127.0.0.1", "127.0.0.1:8008",
        "[::1]", "[::1]:8008", "192.168.1.5:8008", "deskbox.local:8008", "Deskbox.local",
        "deskbox:8008", "localhost.",
    ],
)  # fmt: skip
def test_own_names_and_addresses_are_accepted(strict_app, host):
    assert raw(strict_app, "GET", "/api/feed", {"Host": host})["status"] == 200


@pytest.mark.parametrize(
    "host", ["localhost.evil.example", "127.0.0.1.evil.example", "localhost:80@evil", "a b", "[::1"]
)
def test_lookalike_hosts_are_rejected(strict_app, host):
    assert raw(strict_app, "GET", "/api/feed", {"Host": host})["status"] == 421


def test_settings_allowed_hosts_are_accepted(strict_cfg, monkeypatch):
    from dataclasses import replace

    monkeypatch.setattr(social, "lan_addresses", lambda: [])
    server = replace(strict_cfg.settings.server, allowed_hosts=("Feed.Example.net",))
    cfg2 = replace(strict_cfg, settings=replace(strict_cfg.settings, server=server))
    app = api.create_app(lambda: cfg2)
    assert raw(app, "GET", "/api/feed", {"Host": "feed.example.net:8008"})["status"] == 200
    assert raw(app, "GET", "/api/feed", {"Host": "other.example.net"})["status"] == 421


def test_a_new_lan_address_is_accepted_without_a_restart(strict_cfg, monkeypatch):
    addrs = ["192.168.1.5"]
    now = [1000.0]
    monkeypatch.setattr(social, "lan_addresses", lambda: list(addrs))
    monkeypatch.setattr(api, "_now", lambda: now[0])
    app = api.create_app(lambda: strict_cfg)
    assert raw(app, "GET", "/api/feed", {"Host": "192.168.1.5:8008"})["status"] == 200
    assert raw(app, "GET", "/api/feed", {"Host": "10.0.0.7:8008"})["status"] == 421
    addrs[:] = ["10.0.0.7"]
    now[0] += 10
    assert raw(app, "GET", "/api/feed", {"Host": "10.0.0.7:8008"})["status"] == 200


def test_unknown_hosts_do_not_force_a_lookup_per_request(strict_cfg, monkeypatch):
    calls = []
    monkeypatch.setattr(social, "lan_addresses", lambda: calls.append(1) or [])
    monkeypatch.setattr(api, "_now", lambda: 1000.0)
    app = api.create_app(lambda: strict_cfg)
    for _ in range(5):
        raw(app, "GET", "/api/feed", {"Host": "evil.example"})
    assert len(calls) == 1


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
@pytest.mark.parametrize("origin", ["http://evil.example", "null", "http://evil.example:8008"])
def test_state_changing_request_with_foreign_origin_is_403(strict_app, method, origin):
    r = raw(strict_app, method, "/api/events", {"Host": "localhost:8008", "Origin": origin})
    assert r["status"] == 403


def test_origin_in_the_allowlist_or_absent_is_fine(strict_app):
    ok = {"Host": "localhost:8008"}
    body = {"events": []}
    for origin in ("http://localhost:5173", "http://192.168.1.5:8008", "http://[::1]:8008"):
        h = {"Origin": origin}
        r = call(strict_app, "POST", "/api/events", "127.0.0.1", json=body, headers=h)
        assert r.status_code == 200, origin
    assert call(strict_app, "POST", "/api/events", "127.0.0.1", json=body).status_code == 200
    # Reads are not blocked by Origin: the Host check already covers them.
    r = raw(strict_app, "GET", "/api/feed", {**ok, "Origin": "http://evil.example"})
    assert r["status"] == 200


# --- Response headers --------------------------------------------------------------------------


def _web(cfg, html):
    d = cfg.root / "web" / "build"
    d.mkdir(parents=True)
    (d / "index.html").write_text(html)


def test_security_headers_on_every_response(cfg, strict_app):
    _web(cfg, "<!doctype html><title>x</title>")
    responses = [
        call(strict_app, "GET", "/", "127.0.0.1"),
        call(strict_app, "GET", "/api/feed", "127.0.0.1"),
        call(strict_app, "GET", "/api/feed", "192.168.1.9"),  # 401
        call(strict_app, "GET", "/api/feed", "127.0.0.1", headers={"Host": "evil.example"}),  # 421
    ]
    assert [r.status_code for r in responses] == [200, 200, 401, 421]
    for r in responses:
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["referrer-policy"] == "no-referrer"
        csp = r.headers["content-security-policy"]
        assert "frame-ancestors 'none'" in csp
        assert "default-src 'self'" in csp
        assert "object-src 'none'" in csp
        assert "base-uri 'self'" in csp
        assert len(r.headers.get_list("content-security-policy")) == 1


def test_csp_allows_only_the_inline_scripts_of_the_built_page(cfg, strict_app):
    import base64
    import hashlib

    boot = "\n{ start(); }\n"
    _web(cfg, f"<html><body><script>{boot}</script><script src='/x.js'></script></body></html>")
    csp = call(strict_app, "GET", "/", "127.0.0.1").headers["content-security-policy"]
    digest = base64.b64encode(hashlib.sha256(boot.encode()).digest()).decode()
    script = next(p for p in csp.split(";") if p.strip().startswith("script-src"))
    assert f"'sha256-{digest}'" in script
    assert "'unsafe-inline'" not in script and "'unsafe-eval'" not in script
    assert script.count("sha256-") == 1
    # A new build has a new bootstrap script: the header follows the file.
    boot2 = "{ start2(); }"
    index = cfg.root / "web" / "build" / "index.html"
    index.write_text(f"<script>{boot2}</script>")
    os.utime(index, (time.time() + 5, time.time() + 5))
    csp = call(strict_app, "GET", "/", "127.0.0.1").headers["content-security-policy"]
    digest2 = base64.b64encode(hashlib.sha256(boot2.encode()).digest()).decode()
    assert f"'sha256-{digest2}'" in csp and digest not in csp


def test_csp_without_a_web_build_has_no_inline_scripts(strict_app):
    csp = call(strict_app, "GET", "/api/feed", "127.0.0.1").headers["content-security-policy"]
    assert "script-src 'self' 'wasm-unsafe-eval'" in csp and "sha256-" not in csp


# --- Access log --------------------------------------------------------------------------------


def test_access_log_does_not_show_the_pairing_token(cfg):
    import io
    import logging

    api.create_app(lambda: cfg, lan_token=TOKEN)
    api.create_app(lambda: cfg, lan_token=TOKEN)  # a second app adds no second filter
    logger = logging.getLogger("uvicorn.access")
    assert sum(isinstance(f, api.PairTokenFilter) for f in logger.filters) == 1
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    old = logger.level
    logger.setLevel(logging.INFO)
    try:
        fmt = '%s - "%s %s HTTP/%s" %d'
        logger.info(fmt, "192.168.1.9:5000", "GET", f"/pair?t={TOKEN}", "1.1", 303)
        logger.info(fmt, "192.168.1.9:5000", "GET", f"/pair?x=1&t={TOKEN}&y=2", "1.1", 303)
        logger.info(fmt, "192.168.1.9:5000", "GET", "/api/feed?limit=5", "1.1", 200)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old)
    out = buf.getvalue()
    assert TOKEN not in out
    assert out.count("/pair?") == 2 and "/api/feed?limit=5" in out


def test_real_server_access_log_hides_the_token(cfg, capfd):
    port = _free_port()
    app = api.create_app(lambda: cfg, lan_token=TOKEN)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        r = httpx.get(f"http://127.0.0.1:{port}/pair?t={TOKEN}", follow_redirects=False)
        assert r.status_code == 303
    finally:
        server.should_exit = True
        t.join(5)
    logged = "".join(capfd.readouterr())
    assert "/pair" in logged and TOKEN not in logged

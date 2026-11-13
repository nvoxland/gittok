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
    cookies = kw.pop("cookies", None)  # on the client: httpx deprecates cookies per request

    async def go():
        transport = httpx.ASGITransport(app=app, client=(peer, 5000))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost:7313", cookies=cookies
        ) as c:
            return await c.request(method, path, **kw)

    return asyncio.run(go())


@pytest.fixture
def lan_app(cfg):
    return api.create_app(lambda: cfg, lan_token=TOKEN)


@pytest.mark.parametrize("path", ["/mcp", "/mcp/", "/mcp/x"])
def test_there_is_no_mcp_endpoint_for_any_peer(cfg, lan_app, path):
    """MCP is stdio only. `/mcp` is an ordinary unknown path: pairing first, then no route."""
    assert call(lan_app, "POST", path, "192.168.1.9", json={}).status_code == 401
    for peer, cookies in (("192.168.1.9", {"cs_lan": TOKEN}), ("127.0.0.1", None)):
        r = call(lan_app, "POST", path, peer, json={}, cookies=cookies)
        assert r.status_code in (404, 405), (peer, r.status_code)


def test_api_requires_cookie_for_lan_peers(lan_app):
    r = call(lan_app, "GET", "/api/feed", "192.168.1.9")
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/json")
    r = call(lan_app, "POST", "/api/events", "192.168.1.9", json={"events": []})
    assert r.status_code == 401


def test_html_gets_pairing_page_for_lan_peers(lan_app):
    r = call(lan_app, "GET", "/", "192.168.1.9", headers={"Accept": "text/html"})
    assert r.status_code == 401
    assert "ask Claude for the pairing QR code" in r.text
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


def test_real_server_on_all_interfaces_blocks_the_api_from_a_lan_ip(cfg):
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
        assert r.status_code == 401  # no MCP endpoint: the ordinary pairing rule
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
            "scheme": "http", "root_path": "", "server": ("127.0.0.1", 7313),
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


@pytest.mark.parametrize("path", ["/api/feed", "/", "/pair", "/assets/mascots/x.png"])
@pytest.mark.parametrize("host", ["evil.example", "evil.example:7313", "testserver", ""])
def test_unknown_host_is_421_on_every_path_even_from_loopback(strict_app, path, host):
    r = raw(strict_app, "GET", path, {"Host": host})
    assert r["status"] == 421


def test_missing_host_is_421(strict_app):
    assert raw(strict_app, "GET", "/api/feed", {})["status"] == 421


@pytest.mark.parametrize(
    "host",
    [
        "localhost", "localhost:7313", "LOCALHOST:7313", "127.0.0.1", "127.0.0.1:7313",
        "[::1]", "[::1]:7313", "192.168.1.5:7313", "deskbox.local:7313", "Deskbox.local",
        "deskbox:7313", "localhost.",
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
    assert raw(app, "GET", "/api/feed", {"Host": "feed.example.net:7313"})["status"] == 200
    assert raw(app, "GET", "/api/feed", {"Host": "other.example.net"})["status"] == 421


def test_a_new_lan_address_is_accepted_without_a_restart(strict_cfg, monkeypatch):
    addrs = ["192.168.1.5"]
    now = [1000.0]
    monkeypatch.setattr(social, "lan_addresses", lambda: list(addrs))
    monkeypatch.setattr(api, "_now", lambda: now[0])
    app = api.create_app(lambda: strict_cfg)
    assert raw(app, "GET", "/api/feed", {"Host": "192.168.1.5:7313"})["status"] == 200
    assert raw(app, "GET", "/api/feed", {"Host": "10.0.0.7:7313"})["status"] == 421
    addrs[:] = ["10.0.0.7"]
    now[0] += 10
    assert raw(app, "GET", "/api/feed", {"Host": "10.0.0.7:7313"})["status"] == 200


def test_unknown_hosts_do_not_force_a_lookup_per_request(strict_cfg, monkeypatch):
    calls = []
    monkeypatch.setattr(social, "lan_addresses", lambda: calls.append(1) or [])
    monkeypatch.setattr(api, "_now", lambda: 1000.0)
    app = api.create_app(lambda: strict_cfg)
    for _ in range(5):
        raw(app, "GET", "/api/feed", {"Host": "evil.example"})
    assert len(calls) == 1


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
@pytest.mark.parametrize("origin", ["http://evil.example", "null", "http://evil.example:7313"])
def test_state_changing_request_with_foreign_origin_is_403(strict_app, method, origin):
    r = raw(strict_app, method, "/api/events", {"Host": "localhost:7313", "Origin": origin})
    assert r["status"] == 403


def test_origin_in_the_allowlist_or_absent_is_fine(strict_app):
    ok = {"Host": "localhost:7313"}
    body = {"events": []}
    for origin in ("http://localhost:5173", "http://192.168.1.5:7313", "http://[::1]:7313"):
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


def test_token_and_log_files_are_private_in_a_private_new_data_dir(cfg):
    old = os.umask(0o022)
    try:
        data = cfg.settings.data_dir
        assert not data.exists()
        social.ensure_lan_token(data)
        assert stat.S_IMODE(data.stat().st_mode) == 0o700
        assert stat.S_IMODE((data / "lan_token").stat().st_mode) == 0o600
        app = api.create_app(lambda: cfg, lan_token=TOKEN)
        assert call(app, "GET", "/api/prefs", "127.0.0.1").status_code == 200
        bad = {"events": [{"type": "nope", "ts": 1}]}
        assert call(app, "POST", "/api/events", "127.0.0.1", json=bad).status_code == 422
        logs = data / "logs"
        assert stat.S_IMODE(logs.stat().st_mode) == 0o700
        names = {f.name for f in logs.iterdir()}
        assert {"api.log", "rejected-events.log"} <= names
        for f in [*logs.iterdir(), data / "gittok.db"]:
            assert stat.S_IMODE(f.stat().st_mode) == 0o600, f.name
    finally:
        os.umask(old)


def test_a_data_dir_the_user_made_keeps_its_mode(cfg):
    old = os.umask(0o022)
    try:
        data = cfg.settings.data_dir
        data.mkdir(mode=0o750)
        social.ensure_lan_token(data)
        assert stat.S_IMODE(data.stat().st_mode) == 0o750
        assert stat.S_IMODE((data / "lan_token").stat().st_mode) == 0o600
    finally:
        os.umask(old)


# --- A reverse proxy on this machine (tailscale serve, caddy) ------------------------------------

PROXY_HEADERS = [
    {"X-Forwarded-For": "100.64.0.7"},
    {"Forwarded": "for=100.64.0.7;proto=https"},
    {"X-Forwarded-Host": "feed.example.ts.net"},
    {"X-Real-IP": "100.64.0.7"},
    {"X-Forwarded-Proto": "https"},
    {"x-forwarded-for": "127.0.0.1"},  # the value does not matter, the header does
]


@pytest.mark.parametrize("headers", PROXY_HEADERS)
def test_a_proxied_request_from_a_loopback_peer_needs_the_pairing_cookie(lan_app, headers):
    for peer in ("127.0.0.1", "::1"):
        r = call(lan_app, "GET", "/api/feed", peer, headers=headers)
        assert r.status_code == 401
        assert r.json()["detail"] == "pair this device"
        assert call(lan_app, "GET", "/", peer, headers=headers).status_code == 401
        ok = call(lan_app, "GET", "/api/feed", peer, headers=headers, cookies={"cs_lan": TOKEN})
        assert ok.status_code == 200


def test_a_proxied_device_can_still_pair(lan_app):
    headers = {"X-Forwarded-For": "100.64.0.7"}
    r = call(lan_app, "GET", f"/pair?t={TOKEN}", "127.0.0.1", headers=headers)
    assert r.status_code == 303 and "cs_lan=" in r.headers["set-cookie"]


def test_a_direct_loopback_request_is_still_loopback(lan_app):
    assert call(lan_app, "GET", "/api/feed", "127.0.0.1").status_code == 200


@pytest.mark.parametrize("headers", PROXY_HEADERS)
@pytest.mark.parametrize("path", ["/api/feed", "/api/repos", "/", "/healthz", "/pair?t=x"])
def test_a_proxied_request_is_refused_when_the_server_has_no_pairing_token(cfg, headers, path):
    app = api.create_app(lambda: cfg)  # server.lan is off: there is no token to pair with
    for peer in ("127.0.0.1", "::1"):
        r = call(app, "GET", path, peer, headers=headers, cookies={"cs_lan": TOKEN})
        assert r.status_code == 403
        assert r.json()["code"] == "proxy_needs_pairing"
        assert "server.lan: true" in r.json()["detail"]


def test_a_direct_loopback_request_needs_no_token_when_lan_is_off(cfg):
    app = api.create_app(lambda: cfg)
    assert call(app, "GET", "/api/feed", "127.0.0.1").status_code == 200


# --- Machine-readable error codes --------------------------------------------------------------


def test_middleware_errors_carry_a_code_next_to_detail(cfg, lan_app, strict_app):
    def body(r):
        return (r.status_code, r.json())

    lan = "192.168.1.9"
    assert body(call(lan_app, "GET", "/api/feed", lan)) == (
        401, {"detail": "pair this device", "code": "unpaired"},
    )  # fmt: skip
    assert body(call(lan_app, "GET", "/pair?t=wrong", lan)) == (
        401, {"detail": "bad pairing token", "code": "bad_pairing_token"},
    )  # fmt: skip
    evil = {"Origin": "http://evil.example"}
    assert body(call(lan_app, "POST", "/api/events", "127.0.0.1", headers=evil, json={})) == (
        403, {"detail": "cross-origin request", "code": "cross_origin"},
    )  # fmt: skip
    big = call(lan_app, "POST", "/api/events", "127.0.0.1", content=b"x" * (1024 * 1024 + 1))
    assert body(big) == (413, {"detail": "request body too large", "code": "body_too_large"})
    sent = {}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        if msg["type"] == "http.response.body":
            sent["body"] = msg["body"]

    for headers, want in [
        ({"Host": "evil.example"}, b'{"detail":"unknown Host","code":"unknown_host"}'),
        (
            {"Host": "localhost", "Content-Length": "many"},
            b'{"detail":"bad content-length","code":"bad_content_length"}',
        ),
    ]:
        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": "POST", "path": "/api/events", "raw_path": b"/api/events",
            "query_string": b"", "scheme": "http", "root_path": "",
            "server": ("127.0.0.1", 7313), "client": ("127.0.0.1", 5000),
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        }  # fmt: skip
        asyncio.run(strict_app(scope, receive, send))
        assert sent["body"] == want


# --- The pairing page (QR code) ----------------------------------------------------------------


def test_pairing_page_shows_a_qr_code_and_the_link_per_address(lan_app, monkeypatch):
    monkeypatch.setattr(social, "lan_addresses", lambda: ["192.168.1.5", "10.0.0.7"])
    r = call(lan_app, "GET", "/pairing", "127.0.0.1")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert r.headers["cache-control"] == "no-store"
    assert r.text.count("<svg") == 2 and "<script" not in r.text.lower()
    assert f"http://192.168.1.5:7313/pair?t={TOKEN}" in r.text
    assert f"http://10.0.0.7:7313/pair?t={TOKEN}" in r.text
    assert r.text.index("192.168.1.5") < r.text.index("10.0.0.7")  # the primary address first
    assert "Scan with your phone's camera" in r.text and "same network" in r.text
    note = r.text[r.text.rindex("</svg>") :]
    assert "plain HTTP" in note and "network you trust" in note and "turn off phone access" in note
    assert "script-src 'self'" in r.headers["content-security-policy"]


def test_pairing_page_uses_the_port_of_the_request(lan_app, monkeypatch):
    monkeypatch.setattr(social, "lan_addresses", lambda: ["192.168.1.5"])
    r = call(lan_app, "GET", "/pairing", "127.0.0.1", headers={"Host": "127.0.0.1:9123"})
    assert f"http://192.168.1.5:9123/pair?t={TOKEN}" in r.text


def test_pairing_page_says_when_phone_access_is_off(cfg):
    app = api.create_app(lambda: cfg)
    r = call(app, "GET", "/pairing", "127.0.0.1")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert "Phone access is off" in r.text and "Ask Claude" in r.text
    assert "<svg" not in r.text and "pair?t=" not in r.text


def test_pairing_page_without_a_lan_address(lan_app, monkeypatch):
    monkeypatch.setattr(social, "lan_addresses", lambda: [])
    r = call(lan_app, "GET", "/pairing", "127.0.0.1")
    assert r.status_code == 200 and "no LAN address" in r.text
    assert "<svg" not in r.text and TOKEN not in r.text


@pytest.mark.parametrize("peer", ["192.168.1.9", "10.0.0.2", "fe80::1", "garbage"])
def test_pairing_page_is_refused_for_lan_peers_even_when_paired(cfg, lan_app, peer):
    for app in (lan_app, api.create_app(lambda: cfg)):
        for cookies in (None, {"cs_lan": TOKEN}):
            r = call(app, "GET", "/pairing", peer, cookies=cookies)
            assert r.status_code == 403 and r.json()["code"] == "pairing_loopback_only"
            assert TOKEN not in r.text and r.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("headers", PROXY_HEADERS)
def test_pairing_page_is_refused_for_a_proxied_request(cfg, lan_app, headers):
    for app in (lan_app, api.create_app(lambda: cfg)):
        for peer in ("127.0.0.1", "::1"):
            r = call(app, "GET", "/pairing", peer, headers=headers, cookies={"cs_lan": TOKEN})
            assert r.status_code == 403 and r.json()["code"] == "pairing_loopback_only"
            assert TOKEN not in r.text


def test_pairing_page_needs_a_known_host(strict_app):
    r = raw(strict_app, "GET", "/pairing", {"Host": "evil.example"})
    assert r["status"] == 421
    assert raw(strict_app, "GET", "/pairing", {"Host": "127.0.0.1:7313"})["status"] == 200


def test_real_server_access_log_has_no_token_for_the_pairing_page(cfg, capfd, monkeypatch):
    monkeypatch.setattr(social, "lan_addresses", lambda: ["192.168.1.5"])
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
        r = httpx.get(f"http://127.0.0.1:{port}/pairing")
        assert r.status_code == 200 and TOKEN in r.text
    finally:
        server.should_exit = True
        t.join(5)
    logged = "".join(capfd.readouterr())
    assert "/pairing" in logged and TOKEN not in logged


# --- pairing by code ---------------------------------------------------------------------------


def _approve(cfg, code):
    from datetime import UTC, datetime

    from gittok import db, pair_codes

    with db.session(cfg.settings.data_dir / "gittok.db") as conn:
        return pair_codes.approve(conn, code, datetime.now(UTC))


def _code_in(text):

    from gittok import pair_codes

    return pair_codes.CODE_RE.search(text).group(0)


def test_unpaired_page_offers_pairing_with_a_code(lan_app):
    r = call(lan_app, "GET", "/", "192.168.1.9", headers={"Accept": "text/html"})
    assert 'action="/pair/code"' in r.text and 'method="post"' in r.text
    assert "Pair with a code" in r.text


def test_pair_by_code_from_request_to_cookie(cfg, lan_app):
    lan = "192.168.1.9"
    r = call(lan_app, "POST", "/pair/code", lan, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/pair/wait"
    req = r.cookies["cs_pair"]
    assert TOKEN not in r.text

    wait = call(lan_app, "GET", "/pair/wait", lan, cookies={"cs_pair": req})
    assert wait.status_code == 200
    code = _code_in(wait.text)
    assert "http-equiv=refresh" in wait.text.replace('"', "")
    assert TOKEN not in wait.text and wait.headers["cache-control"] == "no-store"
    # Not approved yet: still no cookie, and the feed stays closed.
    assert "cs_lan" not in wait.headers.get("set-cookie", "")
    assert call(lan_app, "GET", "/api/feed", lan).status_code == 401

    assert _approve(cfg, code)["ok"] is True
    done = call(lan_app, "GET", "/pair/wait", lan, cookies={"cs_pair": req}, follow_redirects=False)
    assert done.status_code == 303 and done.headers["location"] == "/"
    cookies = done.headers.get_list("set-cookie")
    assert any(c.startswith(f"cs_lan={TOKEN}") and "httponly" in c.lower() for c in cookies)
    assert call(lan_app, "GET", "/api/feed", lan, cookies={"cs_lan": TOKEN}).status_code == 200
    # The approval is used once: the same request id gets nothing again.
    again = call(lan_app, "GET", "/pair/wait", lan, cookies={"cs_pair": req})
    assert "cs_lan" not in again.headers.get("set-cookie", "")
    assert "Pair with a code" in again.text


def test_pair_wait_without_a_request_offers_a_new_code(lan_app):
    r = call(lan_app, "GET", "/pair/wait", "192.168.1.9")
    assert r.status_code == 200 and "Pair with a code" in r.text
    r = call(lan_app, "GET", "/pair/wait", "192.168.1.9", cookies={"cs_pair": "forged"})
    assert "Pair with a code" in r.text and TOKEN not in r.text


def test_pair_code_refuses_a_cross_origin_post(lan_app):
    r = call(
        lan_app, "POST", "/pair/code", "192.168.1.9", headers={"Origin": "http://evil.example"}
    )
    assert r.status_code == 403


def test_pair_code_when_too_many_wait(cfg, lan_app, monkeypatch):
    from gittok import pair_codes

    monkeypatch.setattr(pair_codes, "MAX_PENDING", 1)
    assert call(lan_app, "POST", "/pair/code", "192.168.1.9").status_code in (200, 303)
    r = call(lan_app, "POST", "/pair/code", "192.168.1.9", follow_redirects=False)
    assert r.status_code == 429


def test_pair_by_code_is_off_without_a_lan_token(cfg):
    app = api.create_app(lambda: cfg)
    assert call(app, "POST", "/pair/code", "127.0.0.1", follow_redirects=False).status_code == 404


def test_pair_pages_let_their_form_send_its_real_origin(lan_app):
    """With `no-referrer`, a browser posts the form with `Origin: null`, which the Origin
    check refuses. The pairing pages use `same-origin`: the real origin goes to this server
    only."""
    lan = "192.168.1.9"
    page = call(lan_app, "GET", "/", lan, headers={"Accept": "text/html"})
    assert page.headers["referrer-policy"] == "same-origin"
    wait = call(lan_app, "GET", "/pair/wait", lan)
    assert wait.headers["referrer-policy"] == "same-origin"
    # Every other page keeps no-referrer.
    assert call(lan_app, "GET", "/api/feed", lan).headers["referrer-policy"] == "no-referrer"
    # The form's real origin passes; a null origin is still refused.
    ok = call(
        lan_app,
        "POST",
        "/pair/code",
        lan,
        headers={"Origin": "http://localhost:7313"},
        follow_redirects=False,
    )
    assert ok.status_code == 303
    bad = call(lan_app, "POST", "/pair/code", lan, headers={"Origin": "null"})
    assert bad.status_code == 403


@pytest.mark.parametrize(
    "path",
    [
        "/apple-touch-icon.png",
        "/icon-192.png",
        "/icon-512.png",
        "/icon-maskable-512.png",
        "/manifest.webmanifest",
    ],
)
def test_an_unpaired_device_gets_the_app_icons(cfg, lan_app, path):
    """A phone adds the app to its home screen with the icon that it can fetch at that
    moment. These files hold no user data, so they need no pairing."""
    r = call(lan_app, "GET", path, "192.168.1.9")
    assert r.status_code != 401, r.text[:80]


def test_an_unpaired_device_gets_nothing_else(lan_app):
    for path in ("/", "/index.html", "/api/feed", "/assets/x/y.png", "/icon-192.png/../api/feed"):
        assert call(lan_app, "GET", path, "192.168.1.9").status_code == 401, path


def test_pair_pages_name_the_app_icon_and_manifest(lan_app):
    for path in ("/", "/pair/wait"):
        text = call(lan_app, "GET", path, "192.168.1.9", headers={"Accept": "text/html"}).text
        assert '<link rel="apple-touch-icon" href="/apple-touch-icon.png">' in text, path
        assert '<link rel="manifest" href="/manifest.webmanifest">' in text, path


def test_the_public_icon_paths_are_the_icon_files_of_the_web_app():
    from pathlib import Path

    static = Path(__file__).parents[1] / "web" / "static"
    files = {f"/{p.name}" for p in static.iterdir() if p.suffix in (".png", ".webmanifest")}
    assert api.APP_ICON_PATHS == files


def test_the_wait_page_has_a_button_that_copies_what_to_tell_claude(lan_app):
    lan = "192.168.1.9"
    req = call(lan_app, "POST", "/pair/code", lan, follow_redirects=False).cookies["cs_pair"]
    wait = call(lan_app, "GET", "/pair/wait", lan, cookies={"cs_pair": req})
    code = _code_in(wait.text)
    assert f'data-copy="pair code {code}"' in wait.text
    assert '<script src="/pair.js"></script>' in wait.text
    assert "<script>" not in wait.text  # no inline script: the CSP allows only files of 'self'
    assert "script-src 'self'" in wait.headers["content-security-policy"]


def test_the_copy_script_is_served_before_pairing(lan_app):
    r = call(lan_app, "GET", "/pair.js", "192.168.1.9")
    assert r.status_code == 200 and "javascript" in r.headers["content-type"]
    # Plain HTTP on the LAN has no navigator.clipboard: the script falls back to execCommand.
    assert "navigator.clipboard" in r.text and "execCommand('copy')" in r.text

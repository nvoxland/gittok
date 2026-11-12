"""FastAPI app: feed API, static web build, and the MCP endpoint in one process."""

from __future__ import annotations

import hmac
import ipaddress
import random
import re
from collections.abc import Callable
from contextlib import asynccontextmanager, closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

from gittok import (
    avatars,
    characters,
    db,
    gc,
    gitq,
    knowledge,
    learning,
    mcp_server,
    profile,
    render,
    replies,
    signals,
    social,
    srs,
    steering,
)
from gittok import feed as feedmod
from gittok.config import Config, load_config
from gittok.feed import InvalidCursor, public_card

EventType = Literal[
    "impression",
    "dwell",
    "skip",
    "scroll_back",
    "depth_open",
    "lightbox_open",
    "like",
    "save",
    "explain_more",
    "answer",
    "source_tap",
    "beats_done",
    "replay",
    "beat_tap",
    "knew_it",
    "teach_more",
]


MAX_EVENT_DATA_BYTES = 4096
MAX_BODY_BYTES = 1024 * 1024
LAN_COOKIE = "cs_lan"
LAN_COOKIE_MAX_AGE = 10 * 365 * 86400
_SHA = re.compile(r"[0-9a-fA-F]{7,40}")

PAIR_HTML = (
    "<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'>"
    "<title>GitTok</title><h1>Pair this device</h1>"
    "<p>Open the pairing URL printed by <code>gittok serve --lan</code>.</p>"
)


class FollowBody(BaseModel):
    repo: str
    path: str = Field(min_length=1, max_length=400)
    on: bool = True


def _sync_saved(c, card_id: str) -> None:
    """Make `saved_cards` match the card's latest `save` event. Ordered by ts, not by arrival."""
    last = c.execute(
        "SELECT ts, data FROM events WHERE card_id = ? AND type = 'save' "
        "ORDER BY ts DESC, id DESC LIMIT 1",
        (card_id,),
    ).fetchone()
    on = bool((db.loads(last["data"]) or {}).get("on", True))
    if on and c.execute("SELECT 1 FROM cards WHERE id = ?", (card_id,)).fetchone():
        c.execute(
            "INSERT INTO saved_cards(card_id, saved_at, saved_ts) VALUES (?, ?, ?) "
            "ON CONFLICT(card_id) DO UPDATE SET saved_at = excluded.saved_at, "
            "saved_ts = excluded.saved_ts",
            (card_id, _iso_ms(last["ts"]), last["ts"]),
        )
    else:
        c.execute("DELETE FROM saved_cards WHERE card_id = ?", (card_id,))


def _iso_ms(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_loopback(scope) -> bool:
    client = scope.get("client")
    if not client:
        return False
    try:
        return ipaddress.ip_address(client[0].split("%")[0]).is_loopback
    except ValueError:
        return False


class SecurityMiddleware:
    """Loopback-only MCP, LAN pairing cookie, and a request body size limit."""

    def __init__(self, app, lan_token: str | None = None, api_log: Callable[[], Any] | None = None):
        self.app = app
        self.token = lan_token
        self.api_log = api_log  # returns the log file path; /api/ requests are logged there

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if self.api_log and scope["path"].startswith("/api/"):
            return await self._logged(scope, receive, send)
        return await self._handle(scope, receive, send)

    async def _logged(self, scope, receive, send):
        status = 0

        async def capture(msg):
            nonlocal status
            if msg["type"] == "http.response.start":
                status = msg["status"]
            await send(msg)

        try:
            await self._handle(scope, receive, capture)
        finally:
            try:
                path = self.api_log()
                path.parent.mkdir(parents=True, exist_ok=True)
                host = (scope.get("client") or ("?",))[0]
                with path.open("a") as f:
                    f.write(f"{db.now_iso()} {host} {scope['method']} {scope['path']} {status}\n")
            except OSError:
                pass  # logging never fails a request

    async def _handle(self, scope, receive, send):
        path = scope["path"]
        loopback = _is_loopback(scope)

        def reply(response):
            return response(scope, receive, send)

        if path == "/mcp" or path.startswith("/mcp/"):
            if not loopback:
                return await reply(JSONResponse({"detail": "MCP is loopback-only"}, 403))
        elif self.token and not loopback and path != "/pair":
            cookie = _cookie(scope, LAN_COOKIE)
            if cookie is None or not hmac.compare_digest(cookie.encode(), self.token.encode()):
                if path.startswith("/api/"):
                    return await reply(JSONResponse({"detail": "pair this device"}, 401))
                return await reply(HTMLResponse(PAIR_HTML, 401))

        headers = dict(scope["headers"])
        try:
            if int(headers.get(b"content-length", b"0")) > MAX_BODY_BYTES:
                return await reply(JSONResponse({"detail": "request body too large"}, 413))
        except ValueError:
            return await reply(JSONResponse({"detail": "bad content-length"}, 400))

        seen = 0
        started = False

        async def counting_receive():
            nonlocal seen
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > MAX_BODY_BYTES:
                    raise _BodyTooLarge
            return msg

        async def tracking_send(msg):
            nonlocal started
            if msg["type"] == "http.response.start":
                started = True
            await send(msg)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _BodyTooLarge:
            if not started:
                await reply(JSONResponse({"detail": "request body too large"}, 413))


class _BodyTooLarge(Exception):
    pass


def _cookie(scope, name: str) -> str | None:
    for k, v in scope["headers"]:
        if k == b"cookie":
            for part in v.decode("latin-1").split(";"):
                key, _, val = part.strip().partition("=")
                if key == name:
                    return val
    return None


class Event(BaseModel):
    card_id: str | None = None
    type: EventType
    ts: int
    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("data")
    @classmethod
    def _data_small(cls, v):
        if len(db.dumps(v)) > MAX_EVENT_DATA_BYTES:
            raise ValueError("event data too large")
        return v


class Answer(BaseModel):
    card_id: str
    choice: int
    session: str | None = None


class StorySeen(BaseModel):
    repo: str
    shas: list[str] = Field(max_length=100)

    @field_validator("shas")
    @classmethod
    def _hex(cls, v):
        if not all(_SHA.fullmatch(s) for s in v):
            raise ValueError("shas must be 7-40 hex characters")
        return v


class ReplyBody(BaseModel):
    card_id: str
    comment_index: int
    text: str


class NotificationsRead(BaseModel):
    ids: list[int] | None = None
    all: bool = False


class EventBatch(BaseModel):
    events: list[Event] = Field(max_length=500)


def _web_dir(cfg: Config) -> Path:
    """The built web app: `web/build` in a clone, `web` in the installed bundle."""
    for rel in (("web", "build"), ("web",)):
        d = cfg.shared_path(*rel)
        if (d / "index.html").is_file():
            return d
    return cfg.shared_path("web", "build")


NO_BUILD_HTML = (
    "<!doctype html><title>GitTok</title>"
    "<h1>GitTok</h1><p>The web app is not built. Run "
    "<code>npm --prefix web run build</code> and reload.</p>"
)


ASSET_CACHE = "public, max-age=31536000, immutable"
MASCOT_CACHE = "public, max-age=3600"
_CARD_DIR = re.compile(r"[A-Za-z0-9_]+")
_CARD_FILE = re.compile(r"[0-9]+\.png")
_MASCOT_FILE = re.compile(r"[A-Za-z0-9_-]+\.png")


def asset_path(root, folder: str, file: str):
    """The file under `root` for a card image or mascot image, else None."""
    if folder == "mascots":
        ok = _MASCOT_FILE.fullmatch(file)
    else:
        ok = _CARD_DIR.fullmatch(folder) and _CARD_FILE.fullmatch(file)
    if not ok:
        return None
    path = root / folder / file
    return path if path.is_file() else None


_HISTORY_COUNTS: dict[tuple[str, str], tuple[int, int]] = {}


def _year_counts(repo, head: str, t0: int) -> tuple[int, int]:
    """(commits, authors) in the year before the last commit. Cached by head sha."""
    key = (repo.name, head)
    if key not in _HISTORY_COUNTS:
        out = gitq.run(
            repo.path, "log", head, "--no-merges", f"--since=@{t0 - 365 * 86400}",
            "--format=%aE", "--",
        )  # fmt: skip
        authors = [ln for ln in out.splitlines() if ln]
        _HISTORY_COUNTS[key] = (len(authors), len(set(authors)))
    return _HISTORY_COUNTS[key]


def _top(churn: dict | None, kind: str) -> list[dict]:
    windows = (churn or {}).get(kind) or {}
    rows = windows.get("365") or windows.get(max(windows, key=int, default=""), [])
    return [{"path": r["path"], "commits": r["commits"]} for r in rows[:5]]


def repo_profile(conn, cfg: Config, name: str) -> dict:
    repo = cfg.repos[name]
    sig = signals.load_signals(conn, name)
    stats: dict[str, Any] = {
        "commits_365": None,
        "authors_365": None,
        "last_commit_ts": None,
        "top_files": [],
        "top_dirs": [],
    }
    head = conn.execute("SELECT last_analyzed_sha FROM repos WHERE name = ?", (name,)).fetchone()
    if sig and head and head["last_analyzed_sha"]:
        sha = head["last_analyzed_sha"]
        try:
            stats["last_commit_ts"] = t0 = gitq.commit_time(repo.path, sha)
            stats["commits_365"], stats["authors_365"] = _year_counts(repo, sha, t0)
        except Exception:  # repo moved or unreadable: serve what the cache has
            pass
        stats["top_files"] = _top(sig.get("churn"), "files")
        stats["top_dirs"] = _top(sig.get("churn"), "dirs")
    mascot, image = social.mascot_info(cfg, name)
    rows = conn.execute(
        "SELECT c.* FROM cards c JOIN repos r ON r.id = c.repo_id "
        "WHERE r.name = ? AND c.status = 'ready' ORDER BY c.created_at DESC, c.id DESC LIMIT 20",
        (name,),
    ).fetchall()
    verdicts: dict[str, dict[str, int]] = {}
    for r in conn.execute(
        "SELECT d.value AS dir, v.value AS verdict, COUNT(DISTINCT c.id) AS n "
        "FROM cards c JOIN repos r ON r.id = c.repo_id "
        "JOIN card_features v ON v.card_id = c.id AND v.feature = 'verdict' "
        "JOIN card_features d ON d.card_id = c.id AND d.feature = 'dir' AND d.value NOT LIKE '%/%' "
        "WHERE r.name = ? AND c.status = 'ready' GROUP BY d.value, v.value",
        (name,),
    ):
        verdicts.setdefault(r["dir"], {})[r["verdict"]] = r["n"]
    return {
        "name": name,
        "verdicts": [
            {"dir": d, "counts": dict(sorted(c.items()))} for d, c in sorted(verdicts.items())
        ],
        "mascot": mascot,
        "mascot_image": image,
        "group": repo.group,
        "stats": stats,
        "cards": [public_card(r, cfg) for r in rows],
    }


class SPAStaticFiles(StaticFiles):
    """Serve the web build; unknown non-API paths fall back to index.html."""

    async def get_response(self, path, scope):
        try:
            res = await super().get_response(path, scope)
        except StarletteHTTPException as e:
            if e.status_code == 404 and not path.startswith("api/"):
                res = await super().get_response("index.html", scope)
            else:
                raise
        # Hashed build files never change; everything else (index.html above all) must be
        # checked each time, or a phone keeps loading old JavaScript after a rebuild.
        immutable = path.startswith("_app/immutable/")
        res.headers["Cache-Control"] = (
            "public, max-age=31536000, immutable" if immutable else "no-cache"
        )
        return res


def create_app(
    get_config: Callable[[], Config] = load_config,
    render_worker: bool = False,
    renderers: dict | None = None,
    learning_worker: bool = False,
    learning_interval_s: float = 30.0,
    profile_worker: bool = False,
    profile_interval_s: float = profile.CHECK_INTERVAL_S,
    notify_worker: bool = False,
    notify_interval_s: float = 60.0,
    gc_worker: bool = False,
    gc_interval_s: float | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    lan_token: str | None = None,
):
    mcp = mcp_server.build_server(get_config)
    mcp_app = mcp.streamable_http_app(
        streamable_http_path="/mcp", stateless_http=True, json_response=True
    )

    @asynccontextmanager
    async def lifespan(_app):
        worker = render.RenderWorker(get_config, renderers) if render_worker else None
        learner = None
        if learning_worker:
            learner = learning.LearningWorker(get_config, learning_interval_s)
        profiler = profile.ProfileWorker(get_config, profile_interval_s) if profile_worker else None
        notifier = (
            social.NotifyWorker(get_config, notify_interval_s, clock) if notify_worker else None
        )
        collector = gc.GcWorker(get_config, gc_interval_s, clock) if gc_worker else None
        workers = (worker, learner, profiler, notifier, collector)
        for w in workers:
            if w:
                w.start()
        try:
            async with mcp.session_manager.run():
                yield
        finally:
            for w in workers:
                if w:
                    w.stop()

    app = FastAPI(title="GitTok", lifespan=lifespan)
    app.add_middleware(
        SecurityMiddleware,
        lan_token=lan_token,
        api_log=lambda: get_config().settings.data_dir / "logs" / "api.log",
    )

    @app.exception_handler(RequestValidationError)
    async def log_rejected_events(request: Request, exc: RequestValidationError):
        # The client drops a rejected event batch whole, so this log is the only trace of why.
        if request.url.path == "/api/events":
            logs = get_config().settings.data_dir / "logs"
            logs.mkdir(parents=True, exist_ok=True)
            host = request.client.host if request.client else "?"
            errors = db.dumps(jsonable_encoder(exc.errors()))[:2000]
            with (logs / "rejected-events.log").open("a") as f:
                f.write(f"{db.now_iso()} 422 {host} {errors}\n")
        return await request_validation_exception_handler(request, exc)

    @app.get("/pair")
    def pair(t: str = ""):
        if not lan_token or not hmac.compare_digest(t.encode(), lan_token.encode()):
            raise HTTPException(401, "bad pairing token")
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(
            LAN_COOKIE, lan_token, max_age=LAN_COOKIE_MAX_AGE, httponly=True, samesite="lax"
        )
        return resp

    def conn():
        return db.open_db(get_config().settings.data_dir / "gittok.db")

    @app.get("/api/feed")
    def feed(
        limit: int = Query(20, ge=1, le=50),
        cursor: str | None = None,
        repo: str | None = None,
        dir: str | None = None,
    ):
        cfg = get_config()
        try:
            with conn() as c:
                cards, next_cursor, resume = feedmod.page(
                    c, cfg, limit, cursor, random.randrange(2**31), datetime.now(UTC), repo, dir
                )
        except InvalidCursor:
            raise HTTPException(400, "invalid cursor") from None
        return {"cards": cards, "next_cursor": next_cursor, "resume_card_id": resume}

    @app.get("/api/cards/{card_id}")
    def card(card_id: str):
        with conn() as c:
            row = c.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
            if row is None:
                raise HTTPException(404, f"unknown card {card_id}")
            card = public_card(row, get_config())
            replies.attach(c, [card])
        return card

    @app.post("/api/answer")
    def answer(body: Answer):
        now = datetime.now(UTC)
        with conn() as c:
            try:
                result = srs.record_answer(c, body.card_id, body.choice, now)
            except srs.UnknownCard:
                raise HTTPException(404, f"unknown card {body.card_id}") from None
            except srs.NotInteractive:
                raise HTTPException(400, "card has no question to answer") from None
            except srs.BadChoice as e:
                raise HTTPException(400, str(e)) from None
            data = {"choice": body.choice, "correct": result["correct"]}
            if body.session:
                data["session"] = body.session
            c.execute(
                "INSERT INTO events(card_id, type, ts, data, received_at) "
                "VALUES (?, 'answer', ?, ?, ?)",
                (body.card_id, int(now.timestamp() * 1000), db.dumps(data), db.now_iso()),
            )
        return result

    @app.get("/api/saved")
    def saved():
        with conn() as c:
            rows = c.execute(
                "SELECT c.* FROM saved_cards s JOIN cards c ON c.id = s.card_id "
                "ORDER BY s.saved_ts DESC, s.card_id"
            ).fetchall()
            cfg = get_config()
            cards = [public_card(r, cfg) for r in rows]
            replies.attach(c, cards)
        return {"cards": cards}

    @app.post("/api/replies")
    def post_reply(body: ReplyBody):
        with conn() as c:
            try:
                return replies.add(c, body.card_id, body.comment_index, body.text)
            except replies.UnknownCard as e:
                raise HTTPException(404, str(e)) from None
            except replies.ReplyError as e:
                raise HTTPException(400, str(e)) from None

    @app.get("/api/stories")
    def stories():
        with closing(conn()) as c:
            return {"stories": social.stories(c, get_config(), clock())}

    @app.post("/api/stories/seen")
    def stories_seen(body: StorySeen):
        if body.repo not in get_config().repos:
            raise HTTPException(404, f"unknown repo {body.repo}")
        with closing(conn()) as c:
            return {"recorded": social.mark_seen(c, body.repo, body.shas, clock())}

    @app.get("/api/notifications")
    def notifications(unread: int = 0):
        with closing(conn()) as c:
            return social.list_notifications(c, unread_only=bool(unread))

    @app.post("/api/notifications/read")
    def notifications_read(body: NotificationsRead):
        if not body.all and not body.ids:
            raise HTTPException(400, "send ids or all")
        with closing(conn()) as c:
            social.mark_read(c, clock(), ids=body.ids, all=body.all)
            return {"unread": social.list_notifications(c)["unread"]}

    @app.get("/api/repos")
    def repos():
        cfg = get_config()
        with conn() as c:
            heads = {
                r["name"]: r["last_analyzed_sha"]
                for r in c.execute("SELECT name, last_analyzed_sha FROM repos")
            }
        return {
            "repos": [
                {"name": r.name, "ref": r.ref, "head_sha": heads.get(r.name), "group": r.group}
                for r in cfg.repos.values()
            ]
        }

    @app.get("/api/repos/{name}")
    def repo_detail(name: str):
        cfg = get_config()
        if name not in cfg.repos:
            raise HTTPException(404, f"unknown repo {name}")
        with conn() as c:
            return repo_profile(c, cfg, name)

    @app.get("/api/personas/{handle}")
    def persona_detail(handle: str):
        with conn() as c:
            page = characters.persona_page(c, get_config(), handle)
        if page is None:
            raise HTTPException(404, f"unknown persona {handle}")
        return page

    @app.get("/api/files/{repo}/{path:path}")
    def file_detail(repo: str, path: str):
        with conn() as c:
            page = characters.file_page(c, get_config(), repo, path)
        if page is None:
            raise HTTPException(404, f"unknown repo {repo}")
        return page

    @app.post("/api/follows")
    def follow(body: FollowBody):
        if body.repo not in get_config().repos:
            raise HTTPException(404, f"unknown repo {body.repo}")
        with conn() as c:
            return {"followed": characters.set_follow(c, body.repo, body.path, body.on)}

    @app.get("/api/repos/{name}/map")
    def repo_map(name: str):
        cfg = get_config()
        if name not in cfg.repos:
            raise HTTPException(404, f"unknown repo {name}")
        with conn() as c:
            return {
                "name": name,
                "dirs": knowledge.repo_map(c, cfg, name),
                "files": knowledge.map_files(c, cfg, name),
            }

    @app.post("/api/events")
    def events(batch: EventBatch):
        now = db.now_iso()
        with conn() as c:
            c.executemany(
                "INSERT INTO events(card_id, type, ts, data, received_at) VALUES (?, ?, ?, ?, ?)",
                [(e.card_id, e.type, e.ts, db.dumps(e.data), now) for e in batch.events],
            )
            for card_id in {e.card_id for e in batch.events if e.type == "save" and e.card_id}:
                _sync_saved(c, card_id)
        return {"stored": len(batch.events)}

    @app.get("/assets/{folder}/{file}")
    def asset(folder: str, file: str):
        path = asset_path(get_config().settings.data_dir / "assets", folder, file)
        if path is None:
            raise HTTPException(404, "unknown asset")
        cache = MASCOT_CACHE if folder == "mascots" else ASSET_CACHE
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": cache})

    @app.get("/api/avatars/{handle:path}")
    def avatar(handle: str):
        cfg = get_config()
        handle = handle.lstrip("@")
        png = avatars.avatar_png(cfg.settings.data_dir, handle)
        if png is not None:
            return FileResponse(png, media_type="image/png", headers={"Cache-Control": "no-cache"})
        persona = cfg.personas.get(handle)
        svg = avatars.avatar_svg(handle, persona.name if persona else None)
        return Response(svg, media_type="image/svg+xml", headers={"Cache-Control": "no-cache"})

    @app.get("/api/prefs")
    def prefs():
        with conn() as c:
            return steering.get_prefs(c)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    # MCP routes go before the static catch-all mount.
    app.router.routes.extend(mcp_app.routes)

    web = _web_dir(get_config())
    if web.is_dir():
        app.mount("/", SPAStaticFiles(directory=web, html=True), name="web")
    else:

        @app.get("/", response_class=HTMLResponse)
        def placeholder():
            return NO_BUILD_HTML

    return app

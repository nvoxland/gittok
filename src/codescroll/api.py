"""FastAPI app: feed API, static web build, and the MCP endpoint in one process."""

from __future__ import annotations

import random
import re
from collections.abc import Callable
from contextlib import asynccontextmanager, closing
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from codescroll import (
    avatars,
    db,
    gitq,
    learning,
    mcp_server,
    profile,
    render,
    signals,
    social,
    srs,
)
from codescroll import feed as feedmod
from codescroll.config import Config, load_config
from codescroll.feed import InvalidCursor, public_card

EventType = Literal[
    "impression",
    "dwell",
    "skip",
    "scroll_back",
    "depth_open",
    "like",
    "save",
    "explain_more",
    "answer",
    "source_tap",
]


class Event(BaseModel):
    card_id: str | None = None
    type: EventType
    ts: int
    data: dict[str, Any] = Field(default_factory=dict)


class Answer(BaseModel):
    card_id: str
    choice: int
    session: str | None = None


class StorySeen(BaseModel):
    repo: str
    shas: list[str]


class NotificationsRead(BaseModel):
    ids: list[int] | None = None
    all: bool = False


class EventBatch(BaseModel):
    events: list[Event]


NO_BUILD_HTML = (
    "<!doctype html><title>CodeScroll</title>"
    "<h1>CodeScroll</h1><p>The web app is not built. Run "
    "<code>npm --prefix web run build</code> and reload.</p>"
)


ASSET_CACHE = "public, max-age=31536000, immutable"
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
    return {
        "name": name,
        "mascot": mascot,
        "mascot_image": image,
        "group": repo.group,
        "stats": stats,
        "cards": [public_card(r) for r in rows],
    }


class SPAStaticFiles(StaticFiles):
    """Serve the web build; unknown non-API paths fall back to index.html."""

    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as e:
            if e.status_code == 404 and not path.startswith("api/"):
                return await super().get_response("index.html", scope)
            raise


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
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
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
        workers = (worker, learner, profiler, notifier)
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

    app = FastAPI(title="CodeScroll", lifespan=lifespan)

    def conn():
        return db.open_db(get_config().settings.data_dir / "codescroll.db")

    @app.get("/api/feed")
    def feed(limit: int = Query(20, ge=1, le=50), cursor: str | None = None):
        cfg = get_config()
        try:
            with conn() as c:
                cards, next_cursor = feedmod.page(
                    c, cfg, limit, cursor, random.randrange(2**31), datetime.now(UTC)
                )
        except InvalidCursor:
            raise HTTPException(400, "invalid cursor") from None
        return {"cards": cards, "next_cursor": next_cursor}

    @app.get("/api/cards/{card_id}")
    def card(card_id: str):
        with conn() as c:
            row = c.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        if row is None:
            raise HTTPException(404, f"unknown card {card_id}")
        return public_card(row)

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
            latest: dict[str, tuple[int, bool]] = {}
            for e in c.execute(
                "SELECT card_id, ts, data FROM events WHERE type = 'save' "
                "AND card_id IS NOT NULL ORDER BY ts, id"
            ):
                latest[e["card_id"]] = (e["ts"], bool((db.loads(e["data"]) or {}).get("on", True)))
            ids = sorted((k for k, (_, on) in latest.items() if on), key=lambda k: -latest[k][0])
            rows = {
                r["id"]: r
                for r in c.execute(
                    f"SELECT * FROM cards WHERE id IN ({','.join('?' * len(ids))})", ids
                )
            }
        return {"cards": [public_card(rows[i]) for i in ids if i in rows]}

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

    @app.post("/api/events")
    def events(batch: EventBatch):
        now = db.now_iso()
        with conn() as c:
            c.executemany(
                "INSERT INTO events(card_id, type, ts, data, received_at) VALUES (?, ?, ?, ?, ?)",
                [(e.card_id, e.type, e.ts, db.dumps(e.data), now) for e in batch.events],
            )
        return {"stored": len(batch.events)}

    @app.get("/assets/{folder}/{file}")
    def asset(folder: str, file: str):
        path = asset_path(get_config().settings.data_dir / "assets", folder, file)
        if path is None:
            raise HTTPException(404, "unknown asset")
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": ASSET_CACHE})

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

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    # MCP routes go before the static catch-all mount.
    app.router.routes.extend(mcp_app.routes)

    web = get_config().root / "web" / "build"
    if web.is_dir():
        app.mount("/", SPAStaticFiles(directory=web, html=True), name="web")
    else:

        @app.get("/", response_class=HTMLResponse)
        def placeholder():
            return NO_BUILD_HTML

    return app

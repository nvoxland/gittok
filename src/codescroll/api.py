"""FastAPI app: feed API, static web build, and the MCP endpoint in one process."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from codescroll import db, mcp_server
from codescroll.config import Config, load_config
from codescroll.feed import ChronologicalRanker, Ranker, card_json

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


class EventBatch(BaseModel):
    events: list[Event]


NO_BUILD_HTML = (
    "<!doctype html><title>CodeScroll</title>"
    "<h1>CodeScroll</h1><p>The web app is not built. Run "
    "<code>npm --prefix web run build</code> and reload.</p>"
)


class SPAStaticFiles(StaticFiles):
    """Serve the web build; unknown non-API paths fall back to index.html."""

    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as e:
            if e.status_code == 404 and not path.startswith("api/"):
                return await super().get_response("index.html", scope)
            raise


def create_app(get_config: Callable[[], Config] = load_config, ranker: Ranker | None = None):
    ranker = ranker or ChronologicalRanker()
    mcp = mcp_server.build_server(get_config)
    mcp_app = mcp.streamable_http_app(
        streamable_http_path="/mcp", stateless_http=True, json_response=True
    )

    @asynccontextmanager
    async def lifespan(_app):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title="CodeScroll", lifespan=lifespan)

    def conn():
        return db.open_db(get_config().settings.data_dir / "codescroll.db")

    @app.get("/api/feed")
    def feed(limit: int = Query(20, ge=1, le=50), cursor: str | None = None):
        with conn() as c:
            cards, next_cursor = ranker.page(c, limit, cursor)
        return {"cards": cards, "next_cursor": next_cursor}

    @app.get("/api/cards/{card_id}")
    def card(card_id: str):
        with conn() as c:
            row = c.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        if row is None:
            raise HTTPException(404, f"unknown card {card_id}")
        return card_json(row)

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

    @app.post("/api/events")
    def events(batch: EventBatch):
        now = db.now_iso()
        with conn() as c:
            c.executemany(
                "INSERT INTO events(card_id, type, ts, data, received_at) VALUES (?, ?, ?, ?, ?)",
                [(e.card_id, e.type, e.ts, db.dumps(e.data), now) for e in batch.events],
            )
        return {"stored": len(batch.events)}

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

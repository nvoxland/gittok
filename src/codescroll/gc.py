"""Garbage collection: delete cards and files that have no further use.

Kept for good: `stories` (duplicate checks), `rewards` and `weights` (learning), `runs` rows.
See docs/learning.md, "Garbage collection".
"""

import json
import logging
import shutil
import threading
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from codescroll import db

log = logging.getLogger(__name__)

LAST_FILE = "gc_last.json"
COUNT_KEYS = (
    "seen",
    "liked",
    "unseen",
    "failed",
    "events",
    "run_files",
    "story_views",
    "notifications",
    "asset_files",
)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _is_liked(like_data: str | None, story_liked: int | None) -> bool:
    """The latest like toggle wins. With no like event left (pruned), the story keeps the answer."""
    if like_data is None:
        return bool(story_liked)
    data = db.loads(like_data)
    return bool(data.get("on", True)) if isinstance(data, dict) else True


def _card_victims(conn, cfg, now: datetime) -> dict[str, list[str]]:
    """Card ids to delete, by rule. Each card is in at most one list."""
    g = cfg.settings.gc
    cut = {
        "failed": _iso(now - timedelta(days=g.failed_after_days)),
        "unseen": _iso(now - timedelta(days=g.unseen_after_days)),
    }
    seen_ms = {
        "seen": _ms(now - timedelta(days=g.seen_after_days)),
        "liked": _ms(now - timedelta(days=g.liked_after_days)),
    }
    protect_until = _iso(now + timedelta(days=g.srs_keep_days))
    out: dict[str, list[str]] = {k: [] for k in ("seen", "liked", "unseen", "failed")}
    rows = conn.execute(
        "SELECT c.id, c.status, c.created_at, s.liked AS story_liked, "
        "  (SELECT MAX(ts) FROM events WHERE card_id = c.id AND type = 'impression') AS last_imp, "
        "  (SELECT MAX(CAST(strftime('%s', computed_at) AS INTEGER)) * 1000 FROM rewards "
        "     WHERE card_id = c.id) AS last_reward, "
        "  (SELECT data FROM events WHERE card_id = c.id AND type = 'like' "
        "     ORDER BY ts DESC, id DESC LIMIT 1) AS like_data, "
        "  EXISTS (SELECT 1 FROM srs WHERE card_id = c.id AND mastered = 0 AND due_at <= ?) "
        "     AS protected, "
        "  EXISTS (SELECT 1 FROM events WHERE card_id = c.id AND type = 'impression') AS shown "
        "FROM cards c LEFT JOIN stories s ON s.story_key = c.story_key",
        (protect_until,),
    ).fetchall()
    for r in rows:
        if r["protected"]:
            continue
        if r["status"] == "render_failed":
            if r["created_at"] < cut["failed"]:
                out["failed"].append(r["id"])
        elif r["last_reward"] is not None:
            last = r["last_imp"] if r["last_imp"] is not None else r["last_reward"]
            kind = "liked" if _is_liked(r["like_data"], r["story_liked"]) else "seen"
            if last < seen_ms[kind]:
                out[kind].append(r["id"])
        elif not r["shown"] and r["created_at"] < cut["unseen"]:
            out["unseen"].append(r["id"])
    return out


_OLD_EVENT = (
    "events.ts < ? AND EXISTS (SELECT 1 FROM rewards r WHERE r.card_id = events.card_id "
    "AND CAST(strftime('%s', r.computed_at) AS INTEGER) * 1000 >= events.ts)"
)


def _run_dirs(conn, cfg, now: datetime) -> list[Path]:
    """Run folders whose run ended long enough ago."""
    cutoff = _iso(now - timedelta(days=cfg.settings.gc.run_files_after_days))
    root = cfg.settings.data_dir / "runs"
    rows = conn.execute(
        "SELECT id FROM runs WHERE status != 'open' AND COALESCE(finished_at, started_at) < ?",
        (cutoff,),
    ).fetchall()
    return [root / r["id"] for r in rows if (root / r["id"]).is_dir()]


def _remove_dir(path: Path) -> int:
    """Remove a folder; return how many files it held."""
    n = sum(1 for p in path.rglob("*") if p.is_file())
    shutil.rmtree(path, ignore_errors=True)
    return n


def collect(
    conn, cfg, now: datetime, dry_run: bool = False, vacuum: bool = False
) -> dict[str, int]:
    """Delete what has no further use. Returns counts per rule; `dry_run` changes nothing."""
    g = cfg.settings.gc
    data_dir = cfg.settings.data_dir
    victims = _card_victims(conn, cfg, now)
    ids = [i for k in ("seen", "liked", "unseen", "failed") for i in victims[k]]
    asset_dirs = [data_dir / "assets" / i for i in ids if (data_dir / "assets" / i).is_dir()]
    run_dirs = _run_dirs(conn, cfg, now)
    event_args = (_ms(now - timedelta(days=g.events_after_days)),)
    social_cut = _iso(now - timedelta(days=g.social_after_days))

    counts = {k: len(v) for k, v in victims.items()}
    counts["run_files"] = len(run_dirs)
    counts["asset_files"] = sum(1 for d in asset_dirs for p in d.rglob("*") if p.is_file())
    counts["events"] = conn.execute(
        f"SELECT COUNT(*) FROM events WHERE {_OLD_EVENT}", event_args
    ).fetchone()[0]
    counts["story_views"] = conn.execute(
        "SELECT COUNT(*) FROM story_views WHERE seen_at < ?", (social_cut,)
    ).fetchone()[0]
    counts["notifications"] = conn.execute(
        "SELECT COUNT(*) FROM notifications WHERE read_at IS NOT NULL AND read_at < ?",
        (social_cut,),
    ).fetchone()[0]
    if dry_run:
        return counts

    with db.immediate(conn):
        marks = ",".join("?" * len(ids))
        if ids:
            conn.execute(f"DELETE FROM srs WHERE card_id IN ({marks})", ids)
            conn.execute(f"UPDATE notifications SET card_id = NULL WHERE card_id IN ({marks})", ids)
            conn.execute(
                f"DELETE FROM cards WHERE id IN ({marks})", ids
            )  # features, assets cascade
        conn.execute(f"DELETE FROM events WHERE {_OLD_EVENT}", event_args)
        conn.execute("DELETE FROM story_views WHERE seen_at < ?", (social_cut,))
        conn.execute(
            "DELETE FROM notifications WHERE read_at IS NOT NULL AND read_at < ?", (social_cut,)
        )
    for d in (*asset_dirs, *run_dirs):
        shutil.rmtree(d, ignore_errors=True)
    conn.execute("PRAGMA optimize")
    if vacuum:
        conn.execute("VACUUM")
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / LAST_FILE).write_text(json.dumps({"at": _iso(now), "counts": counts}))
    return counts


def last_result(cfg) -> dict[str, Any] | None:
    """The last real pass: {"at": ..., "counts": {...}}, or None if none ran yet."""
    try:
        return json.loads((cfg.settings.data_dir / LAST_FILE).read_text())
    except (OSError, ValueError):
        return None


class GcWorker:
    """Background thread that runs `collect` every `interval_s` (the `gc.interval_s` setting)."""

    def __init__(self, get_config: Callable[[], Any], interval_s: float | None = None, clock=None):
        self._get_config = get_config
        self._interval = interval_s
        self._clock = clock or (lambda: datetime.now(UTC))
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="gc-worker", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout)

    def _run(self) -> None:
        while not self._stop.is_set():
            interval = self._interval
            try:
                cfg = self._get_config()
                if interval is None:
                    interval = cfg.settings.gc.interval_s
                with closing(db.open_db(cfg.settings.data_dir / "codescroll.db")) as conn:
                    collect(conn, cfg, self._clock())
            except Exception:
                log.exception("gc pass failed")
            self._stop.wait(interval if interval is not None else 3600.0)

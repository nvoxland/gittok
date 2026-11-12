"""Feed supply: how many unseen cards are left, how fast they go, how many to make
(docs/learning.md section 7)."""

from __future__ import annotations

import math
import os
from datetime import datetime, timedelta
from pathlib import Path

from gittok import gc, social

IMAGE_KINDS = ("meme", "illustration", "comic", "chart", "diagram")
MB = 1024 * 1024
WANTS_FILE = "feed-wants-cards.log"  # the server appends; `gittok feed-watch` waits on it


def unseen_ready(conn, rc, now: datetime) -> list[str]:
    """Ready cards with no impression in the last `repeat_days`, by id."""
    from gittok import slotter  # slotter imports this module

    cutoff_ms = int((now - timedelta(days=slotter._knobs(rc)["repeat_days"])).timestamp() * 1000)
    recent = {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT card_id FROM events WHERE type = 'impression' AND ts >= ? "
            "AND card_id IS NOT NULL",
            (cutoff_ms,),
        )
    }
    rows = conn.execute("SELECT id FROM cards WHERE status = 'ready' ORDER BY id").fetchall()
    return [r["id"] for r in rows if r["id"] not in recent]


def burn_per_day(conn, now: datetime, days: int = 7) -> float:
    """Distinct cards impressed per day, averaged over the last `days` days."""
    since_ms = int((now - timedelta(days=days)).timestamp() * 1000)
    until_ms = int(now.timestamp() * 1000)
    total = conn.execute(
        "SELECT COUNT(*) FROM (SELECT DISTINCT card_id, date(ts / 1000, 'unixepoch') FROM events "
        "WHERE type = 'impression' AND card_id IS NOT NULL AND ts >= ? AND ts <= ?)",
        (since_ms, until_ms),
    ).fetchone()[0]
    return total / days


def _file_mb(path: Path) -> float:
    return round(path.stat().st_size / MB, 1) if path.is_file() else 0


def _dir_mb(path: Path) -> float:
    total = 0
    for root, _, files in os.walk(path):
        total += sum(os.path.getsize(os.path.join(root, f)) for f in files)
    return round(total / MB, 1)


def _image_share(conn, since_ms: int | None = None) -> float:
    """Share of ready cards (or of cards impressed since `since_ms`) with an image kind."""
    marks = ",".join("?" * len(IMAGE_KINDS))
    sql = (
        f"SELECT COUNT(*), COALESCE(SUM(f.value IN ({marks})), 0) FROM cards c "
        "JOIN card_features f ON f.card_id = c.id AND f.feature = 'visual_kind' WHERE "
    )
    if since_ms is None:
        sql += "c.status = 'ready'"
        args = list(IMAGE_KINDS)
    else:
        sql += (
            "c.id IN (SELECT card_id FROM events WHERE type = 'impression' AND ts >= ? "
            "AND card_id IS NOT NULL)"
        )
        args = [*IMAGE_KINDS, since_ms]
    total, images = conn.execute(sql, args).fetchone()
    return round(images / total, 2) if total else 0.0


def feed_health(conn, cfg, now: datetime) -> dict:
    from gittok import learning

    agent = cfg.settings.agent
    backlog = len(unseen_ready(conn, learning.load_reward_config(cfg), now))
    burn = max(burn_per_day(conn, now), agent.min_burn_per_day)
    short = math.ceil(agent.target_runway_days * burn) - backlog
    # A run has a fixed start-up cost: when one is needed, make at least min_run_count cards.
    want = min(max(short, agent.min_run_count), agent.max_count) if short > 0 else 0
    since_ms = int((now - timedelta(days=7)).timestamp() * 1000)
    status = dict(conn.execute("SELECT status, COUNT(*) FROM cards GROUP BY status").fetchall())
    db_file = conn.execute("PRAGMA database_list").fetchone()["file"]
    return {
        "backlog": backlog,
        "burn_per_day": round(burn, 1),
        "runway_days": round(backlog / burn, 1),
        "target_days": agent.target_runway_days,
        "want": want,
        "pending_render": status.get("pending_render", 0),
        "render_failed": status.get("render_failed", 0),
        "image_share": {"ready": _image_share(conn), "shown_7d": _image_share(conn, since_ms)},
        "db_mb": _file_mb(Path(db_file)) if db_file else 0,
        "assets_mb": _dir_mb(cfg.settings.data_dir / "assets"),
        "gc": gc.last_result(cfg),
    }


def notify_low_runway(conn, cfg, now: datetime) -> int:
    """Once per UTC day, add a notification when the backlog lasts under a day. Returns 1 if new."""
    h = feed_health(conn, cfg, now)
    if h["runway_days"] >= 1:
        return 0
    text = f"Feed is running low: {h['backlog']} unseen cards. Ask Claude to /gittok-generate."
    made = social._add(conn, "low_runway", text, f"low_runway:{now.date()}", now)
    conn.commit()
    return made


def signal_wants_cards(conn, cfg, now: datetime) -> int:
    """Append one fixed line to WANTS_FILE when the feed wants cards. Returns 1 if written.

    No line when there are no repos, while a run started in the cooldown is still open, or
    within the cooldown of the last line. The line holds only a time and a count, never repo text.
    """
    if not cfg.repos:
        return 0  # nothing to generate from: do not wake a session
    agent = cfg.settings.agent
    cooldown = timedelta(hours=agent.wake_cooldown_hours)
    path = cfg.settings.data_dir / WANTS_FILE
    if path.exists() and now.timestamp() - path.stat().st_mtime < cooldown.total_seconds():
        return 0
    since = (now - cooldown).strftime("%Y-%m-%dT%H:%M:%SZ")
    if conn.execute(
        "SELECT 1 FROM runs WHERE status = 'open' AND started_at > ?", (since,)
    ).fetchone():
        return 0
    want = feed_health(conn, cfg, now)["want"]
    if want <= 0:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(f"{now.isoformat()} want {want} cards\n")
    os.utime(path, (now.timestamp(), now.timestamp()))
    return 1

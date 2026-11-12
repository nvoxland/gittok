"""Feed supply: how many unseen cards are left, how fast they go, how many to make
(docs/learning.md section 7)."""

from __future__ import annotations

import json
import math
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from gittok import db, gc, private, social

IMAGE_KINDS = ("meme", "illustration", "comic", "chart", "diagram")
MB = 1024 * 1024
WANTS_FILE = "feed-wants-cards.log"  # the server appends; `gittok feed-watch` waits on it


def unconfigured_cards(conn, cfg) -> set[str]:
    """Ids of the cards whose own repo is not configured now. The feed never shows them."""
    return {
        r["id"]
        for r in conn.execute("SELECT c.id, r.name FROM cards c JOIN repos r ON r.id = c.repo_id")
        if r["name"] not in cfg.repos
    }


def repo_card_counts(conn) -> dict[str, dict]:
    """Stored cards per repo, in one query: {name: {cards, last_card_at}}. A repo with no
    card is not in it."""
    rows = conn.execute(
        "SELECT r.name, COUNT(*) AS n, MAX(c.created_at) AS last FROM cards c "
        "JOIN repos r ON r.id = c.repo_id GROUP BY r.name"
    )
    return {r["name"]: {"cards": r["n"], "last_card_at": r["last"]} for r in rows}


def unseen_by_repo(conn, cfg, rc, now: datetime) -> dict[str, int]:
    """Unseen ready cards per configured repo (0 for a repo with none)."""
    ids = unseen_ready(conn, rc, now)
    out = dict.fromkeys(cfg.repos, 0)
    for i in range(0, len(ids), 500):
        chunk = ids[i : i + 500]
        for r in conn.execute(
            "SELECT r.name, COUNT(*) AS n FROM cards c JOIN repos r ON r.id = c.repo_id "
            f"WHERE c.id IN ({','.join('?' * len(chunk))}) GROUP BY r.name",
            chunk,
        ):
            if r["name"] in out:
                out[r["name"]] += r["n"]
    return out


def unseen_ready(conn, rc, now: datetime) -> list[str]:
    """Ready cards with no impression in the last `repeat_days`, by id. Cards of every stored
    repo: a caller that serves or counts the feed takes out `unconfigured_cards`."""
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
    by_repo = unseen_by_repo(conn, cfg, learning.load_reward_config(cfg), now)
    backlog = sum(by_repo.values())  # cards of a repo that is not configured do not count
    burn = max(burn_per_day(conn, now), agent.min_burn_per_day)
    short = math.ceil(agent.target_runway_days * burn) - backlog
    # A run has a fixed start-up cost: when one is needed, make at least min_run_count cards.
    want = min(max(short, agent.min_run_count), agent.max_count) if short > 0 else 0
    since_ms = int((now - timedelta(days=7)).timestamp() * 1000)
    status = dict(conn.execute("SELECT status, COUNT(*) FROM cards GROUP BY status").fetchall())
    db_file = conn.execute("PRAGMA database_list").fetchone()["file"]
    return {
        "backlog": backlog,
        "by_repo": by_repo,
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


def wants_line(now: datetime, want: int) -> str:
    """One line of WANTS_FILE: a JSON object `{"at": <ISO time with zone>, "want": <count>}`."""
    return db.dumps({"at": now.isoformat(), "want": int(want)}) + "\n"


def parse_wants(text: str) -> list[dict]:
    """The signals in WANTS_FILE text, oldest first: `{"at": datetime, "want": int}`.

    Only whole lines count (the text after the last newline may still be in the middle of a
    write), and a line that is not such an object is left out."""
    out = []
    for line in text.split("\n")[:-1]:
        try:
            data = json.loads(line)
            at = datetime.fromisoformat(data["at"])
            want = data["want"]
        except (ValueError, TypeError, KeyError):
            continue
        if at.tzinfo is None or isinstance(want, bool) or not isinstance(want, int) or want < 1:
            continue
        out.append({"at": at, "want": want})
    return out


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def run_open(conn, cfg, now: datetime) -> bool:
    """True when a generation run is open now. A run that started more than
    `agent.wake_cooldown_hours` ago and never finished is abandoned: it does not count."""
    since = _iso(now - timedelta(hours=cfg.settings.agent.wake_cooldown_hours))
    row = conn.execute(
        "SELECT 1 FROM runs WHERE status = 'open' AND started_at > ?", (since,)
    ).fetchone()
    return row is not None


def signal_wants_cards(conn, cfg, now: datetime) -> int:
    """Append one line (`wants_line`) to WANTS_FILE when the feed wants cards. Returns 1 if
    written.

    No line when there are no repos, while a run is open (`run_open`), when the daily run cap
    is reached (a run could not start), or within the cooldown of the last line. One exception
    to the cooldown: the feed is empty (the reader reached its end) and a run started after the
    last line, so that line was answered. The line holds only a time and a count, never repo
    text.
    """
    from gittok import learning, runs  # runs imports modules that import this one

    if not cfg.repos:
        return 0  # nothing to generate from: do not wake a session
    agent = cfg.settings.agent
    path = cfg.settings.data_dir / WANTS_FILE
    if run_open(conn, cfg, now) or runs.cap_reached(conn, cfg, now):
        return 0
    last = path.stat().st_mtime if path.exists() else None
    if last is not None and now.timestamp() - last < agent.wake_cooldown_hours * 3600:
        if any(unseen_by_repo(conn, cfg, learning.load_reward_config(cfg), now).values()):
            return 0
        answered = conn.execute(
            "SELECT 1 FROM runs WHERE started_at > ?", (_iso(datetime.fromtimestamp(last, UTC)),)
        ).fetchone()
        if not answered:
            return 0  # no run answered the last line: a second line says nothing new
    want = feed_health(conn, cfg, now)["want"]
    if want <= 0:
        return 0
    private.make_dir(path.parent)
    with open(path, "a", opener=private.opener) as f:
        f.write(wants_line(now, want))  # one write call: a reader never sees two halves mixed
    os.utime(path, (now.timestamp(), now.timestamp()))
    return 1

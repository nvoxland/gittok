"""Stories row, notifications, and LAN helpers (docs/social.md)."""

from __future__ import annotations

import logging
import socket
import threading
from collections import Counter
from contextlib import closing
from datetime import UTC, datetime
from typing import Any

from codescroll import db, gitq, srs
from codescroll.config import Config

log = logging.getLogger(__name__)

DAY_S = 86400
MAX_STORY_COMMITS = 10
HOT_FILE_COMMITS = 3
FMT = "%Y-%m-%dT%H:%M:%SZ"

_CACHE: dict[tuple[str, str], list[dict]] = {}
_CACHE_LOCK = threading.Lock()


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def mascot_info(cfg: Config, name: str) -> tuple[str | None, str | None]:
    """(mascot name, image url or None) for a repo."""
    repo = cfg.repos[name]
    mascot = repo.mascot or next((m.name for m in cfg.mascots.values() if m.repo == name), None)
    image = None
    if mascot and (cfg.settings.data_dir / "assets" / "mascots" / f"{mascot}.png").is_file():
        image = f"/assets/mascots/{mascot}.png"
    return mascot, image


def recent_commits(cfg: Config, name: str, now: datetime) -> list[dict]:
    """Commits from the last 24 hours, newest first. Git runs once per repo head sha."""
    repo = cfg.repos[name]
    head = gitq.rev_parse(repo.path, repo.ref)
    key = (name, head)
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
    if cached is None:
        cached = gitq.recent_commits(repo.path, head, int(now.timestamp()) - DAY_S)
        with _CACHE_LOCK:
            for k in [k for k in _CACHE if k[0] == name]:
                del _CACHE[k]
            _CACHE[key] = cached
    since = int(now.timestamp()) - DAY_S
    return [c for c in cached if c["ts"] >= since]


def stories(conn, cfg: Config, now: datetime) -> list[dict]:
    out = []
    for name in cfg.repos:
        try:
            commits = recent_commits(cfg, name, now)
        except gitq.GitError:
            continue
        if not commits:
            continue
        shown = commits[:MAX_STORY_COMMITS]
        seen = {
            r["sha"] for r in conn.execute("SELECT sha FROM story_views WHERE repo = ?", (name,))
        }
        mascot, image = mascot_info(cfg, name)
        out.append(
            {
                "repo": name,
                "mascot": mascot,
                "mascot_image": image,
                "commits": [
                    {
                        "sha": c["sha"],
                        "short": c["sha"][:7],
                        "ts": c["ts"],
                        "author": c["author"],
                        "subject": c["subject"],
                        "files": len(c["files"]),
                    }
                    for c in shown
                ],
                "seen": all(c["sha"] in seen for c in shown),
            }
        )
    out.sort(key=lambda s: -s["commits"][0]["ts"])
    return out


def mark_seen(conn, repo: str, shas: list[str], now: datetime) -> int:
    cur = conn.executemany(
        "INSERT OR IGNORE INTO story_views(repo, sha, seen_at) VALUES (?, ?, ?)",
        [(repo, s, now.strftime(FMT)) for s in shas],
    )
    conn.commit()
    return cur.rowcount


# --- notifications -------------------------------------------------------------------------


def _add(conn, kind: str, text: str, key: str, now: datetime, card_id: str | None = None) -> int:
    cur = conn.execute(
        "INSERT OR IGNORE INTO notifications(kind, text, card_id, created_at, dedup_key) "
        "VALUES (?, ?, ?, ?, ?)",
        (kind, text, card_id, now.strftime(FMT), key),
    )
    return cur.rowcount


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def generate_notifications(conn, cfg: Config, now: datetime) -> dict[str, int]:
    """One idempotent pass. Returns how many notifications of each kind were created."""
    made = dict.fromkeys(("new_cards", "srs_due", "hot_file", "new_kind"), 0)

    for r in conn.execute(
        "SELECT r.id, r.accepted, r.finished_at, p.name AS repo FROM runs r "
        "LEFT JOIN repos p ON p.id = r.repo_id "
        "WHERE r.status = 'finished' AND r.accepted > 0 ORDER BY r.finished_at, r.id"
    ).fetchall():
        text = _plural(r["accepted"], "new card", "new cards")
        if r["repo"]:
            text += f" from {r['repo']}"
        made["new_cards"] += _add(conn, "new_cards", text, f"new_cards:{r['id']}", now)

    due = srs.due_cards(conn, now)
    unread = conn.execute(
        "SELECT 1 FROM notifications WHERE kind = 'srs_due' AND read_at IS NULL"
    ).fetchone()
    if due and not unread:
        n = len(due)
        text = (
            "1 quiz card is back for another try"
            if n == 1
            else f"{n} quiz cards are back for another try"
        )
        made["srs_due"] += _add(conn, "srs_due", text, f"srs_due:{now.strftime(FMT)}", now)

    day = now.strftime("%Y-%m-%d")
    for name in cfg.repos:
        try:
            commits = recent_commits(cfg, name, now)
        except gitq.GitError:
            log.warning("hot files: cannot read %s", name)
            continue
        counts = Counter(f for c in commits for f in set(c["files"]))
        for path, n in sorted(counts.items()):
            if n >= HOT_FILE_COMMITS:
                base = path.rsplit("/", 1)[-1]
                made["hot_file"] += _add(
                    conn, "hot_file", f"{base} was in {n} commits today",
                    f"hot_file:{name}:{path}:{day}", now,
                )  # fmt: skip

    for c in conn.execute(
        "SELECT c.id, c.spec, r.name AS repo FROM cards c JOIN repos r ON r.id = c.repo_id "
        "WHERE c.story_type = 'spot_the_bug' AND c.status = 'ready' ORDER BY c.created_at, c.id"
    ).fetchall():
        spec = db.loads(c["spec"]) or {}
        dirs = spec.get("dirs") or []
        where = f"{dirs[0]}/" if dirs else c["repo"]
        made["new_kind"] += _add(
            conn, "new_kind", f"A new Spot the Bug from {where}", f"new_kind:{c['id']}", now,
            card_id=c["id"],
        )  # fmt: skip
    conn.commit()
    return made


def list_notifications(conn, unread_only: bool = False) -> dict[str, Any]:
    where = " WHERE read_at IS NULL" if unread_only else ""
    rows = conn.execute(f"SELECT * FROM notifications{where} ORDER BY created_at DESC, id DESC")
    unread = conn.execute("SELECT COUNT(*) FROM notifications WHERE read_at IS NULL").fetchone()[0]
    return {
        "notifications": [
            {
                "id": r["id"],
                "kind": r["kind"],
                "text": r["text"],
                "card_id": r["card_id"],
                "created_at": r["created_at"],
                "read": r["read_at"] is not None,
            }
            for r in rows
        ],
        "unread": unread,
    }


def mark_read(conn, now: datetime, ids: list[int] | None = None, all: bool = False) -> int:
    stamp = now.strftime(FMT)
    if all:
        cur = conn.execute("UPDATE notifications SET read_at = ? WHERE read_at IS NULL", (stamp,))
    else:
        ids = ids or []
        cur = conn.execute(
            f"UPDATE notifications SET read_at = ? WHERE read_at IS NULL "
            f"AND id IN ({','.join('?' * len(ids))})",
            [stamp, *ids],
        )
    conn.commit()
    return cur.rowcount


class NotifyWorker:
    """Background thread that runs `generate_notifications` every `interval_s`."""

    def __init__(self, get_config, interval_s: float = 60.0, clock=None):
        self._get_config = get_config
        self._interval = interval_s
        self._clock = clock or (lambda: datetime.now(UTC))
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="notify-worker", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                cfg = self._get_config()
                with closing(db.open_db(cfg.settings.data_dir / "codescroll.db")) as conn:
                    generate_notifications(conn, cfg, self._clock())
            except Exception:
                log.exception("notification pass failed")
            self._stop.wait(self._interval)


# --- LAN -----------------------------------------------------------------------------------


def lan_addresses() -> list[str]:
    """Non-loopback IPv4 addresses of this machine (stdlib only), primary address first."""
    found: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # UDP connect sends nothing; it picks the route
            found.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(info[4][0])
    except OSError:
        pass
    out: list[str] = []
    for a in found:
        if not a.startswith(("127.", "0.")) and a not in out:
            out.append(a)
    return out


def lan_urls(port: int, addresses: list[str] | None = None) -> list[str]:
    return [f"http://{a}:{port}" for a in (lan_addresses() if addresses is None else addresses)]

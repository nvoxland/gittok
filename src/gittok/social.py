"""Stories row, notifications, and LAN helpers (docs/social.md)."""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import socket
import threading
from contextlib import closing
from datetime import UTC, datetime, timedelta
from typing import Any

from gittok import db, gitq, links, private, srs
from gittok.config import Config

log = logging.getLogger(__name__)

DAY_S = 86400
MAX_STORY_COMMITS = 10
HOT_FILE_COMMITS = 3
HOT_FILE_SHOWN = 3
FMT = "%Y-%m-%dT%H:%M:%SZ"

_CACHE: dict[tuple[str, str], list[dict]] = {}
_CACHE_LOCK = threading.Lock()


def mascot_info(cfg: Config, name: str) -> tuple[str | None, str | None]:
    """(mascot name, image url or None) for a repo."""
    repo = cfg.repos[name]
    mascot = repo.mascot or next((m.name for m in cfg.mascots.values() if m.repo == name), None)
    image = None
    if mascot and (cfg.settings.data_dir / "assets" / "mascots" / f"{mascot}.png").is_file():
        mtime = int(
            (cfg.settings.data_dir / "assets" / "mascots" / f"{mascot}.png").stat().st_mtime
        )
        image = f"/assets/mascots/{mascot}.png?v={mtime}"
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


def _commit_card(conn, repo: str, sha: str, skip: str | None) -> str | None:
    """Newest ready card of the repo whose sources, visual or depth cite the commit."""
    for c in conn.execute(
        "SELECT c.id, c.spec FROM cards c JOIN repos r ON r.id = c.repo_id "
        "WHERE r.name = ? AND c.status = 'ready' AND c.spec LIKE ? "
        "ORDER BY c.created_at DESC, c.id DESC",
        (repo, f"%{sha[:7]}%"),
    ):
        if c["id"] == skip:
            continue
        spec = db.loads(c["spec"]) or {}
        parts = [*spec.get("sources", []), spec.get("visual") or {}, *spec.get("depth", [])]
        for p in parts:
            cited = (p.get("commit") or "").lower()
            if len(cited) >= 7 and (sha.startswith(cited) or cited.startswith(sha)):
                return c["id"]
    return None


def _digest(conn, repo: str, now: datetime) -> dict | None:
    row = conn.execute(
        "SELECT d.day, d.card_id, c.spec FROM digests d JOIN cards c ON c.id = d.card_id "
        "WHERE d.repo = ? AND d.day = ? AND c.status = 'ready'",
        (repo, str(now.date())),
    ).fetchone()
    if not row:
        return None
    spec = db.loads(row["spec"]) or {}
    return {
        "card_id": row["card_id"],
        "day": row["day"],
        "hook": spec.get("hook", ""),
        "learn": spec.get("learn", ""),
    }


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
        digest = _digest(conn, name, now)
        base = links.repo_url(cfg, name)
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
                        "seen": c["sha"] in seen,
                        "card_id": (
                            cid := _commit_card(conn, name, c["sha"], digest and digest["card_id"])
                        ),
                        "url": None if cid or not base else f"{base}/commit/{c['sha']}",
                    }
                    for c in shown
                ],
                "digest": digest,
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


def _hot_text(repo: str, hot: list[tuple[int, str]]) -> str:
    def base(path: str) -> str:
        return path.rsplit("/", 1)[-1]

    if len(hot) == 1:
        n, path = hot[0]
        return f"{base(path)} was in {n} commits in the last 24 hours"
    (n0, p0), *rest = hot[:HOT_FILE_SHOWN]
    parts = [f"{base(p0)} ({n0} commits)", *(f"{base(p)} ({n})" for n, p in rest)]
    more = len(hot) - HOT_FILE_SHOWN
    return f"Busy day in {repo}: " + ", ".join(parts) + (f" and {more} more" if more > 0 else "")


NOTIF_PREFIX = "notif:"
NOTIF_STRENGTH = 2.0


def _recent_card_about(conn, repo: str, path: str, now: datetime) -> str | None:
    """Newest ready card from the last 24 hours that cites `path` in its sources."""
    for c in conn.execute(
        "SELECT c.id, c.spec FROM cards c JOIN repos r ON r.id = c.repo_id "
        "WHERE r.name = ? AND c.status = 'ready' AND c.created_at >= ? "
        "ORDER BY c.created_at DESC, c.id DESC",
        (repo, (now - timedelta(seconds=DAY_S)).strftime(FMT)),
    ):
        spec = db.loads(c["spec"]) or {}
        if any(s.get("path") == path for s in spec.get("sources", [])):
            return c["id"]
    return None


def _link_hot_file(conn, repo: str, top: tuple[int, str], commits, key: str, now: datetime) -> None:
    """Give a new hot_file notification a card: an existing recent one, else a ledger lead."""
    n, path = top
    nid = conn.execute("SELECT id FROM notifications WHERE dedup_key = ?", (key,)).fetchone()["id"]
    if card_id := _recent_card_about(conn, repo, path, now):
        conn.execute("UPDATE notifications SET card_id = ? WHERE id = ?", (card_id, nid))
        return
    sha = next(c["sha"] for c in commits if path in c["files"])  # commits are newest first
    stamp = now.strftime(FMT)
    text = (
        f"today's hot file: {path} was in {n} commits in the last 24 hours. "
        "Explain what changed and why it matters."
    )
    conn.execute(
        "INSERT INTO leads(repo, story_type, kind, path, commit_sha, lead_key, text, strength, "
        "head_sha, first_seen_at, last_seen_at) "
        "VALUES (?, 'before_after', 'commit', ?, ?, ?, ?, ?, '', ?, ?) "
        "ON CONFLICT(repo, story_type, lead_key) DO NOTHING",
        (repo, path, sha, f"{NOTIF_PREFIX}{nid}", text, NOTIF_STRENGTH, stamp, stamp),
    )


DIGEST_PREFIX = "digest:"
DIGEST_STRENGTH = 2.0


def generate_digests(conn, cfg: Config, now: datetime) -> int:
    """One digest lead per repo per UTC day, for repos with commits in the last 24 hours.

    Idempotent. Unserved leads of earlier days are dropped. Returns the new leads.
    """
    day = str(now.date())
    stamp = now.strftime(FMT)
    made = 0
    for name in cfg.repos:
        conn.execute(
            "DELETE FROM leads WHERE repo = ? AND lead_key LIKE 'digest:%' AND lead_key != ? "
            "AND last_covered_at IS NULL",
            (name, f"{DIGEST_PREFIX}{name}:{day}"),
        )
        conn.execute(
            "DELETE FROM digests WHERE repo = ? AND day != ? AND card_id IS NULL", (name, day)
        )
        try:
            commits = recent_commits(cfg, name, now)
        except gitq.GitError:
            log.warning("digest: cannot read %s", name)
            continue
        if not commits:
            continue
        if not conn.execute(
            "INSERT OR IGNORE INTO digests(repo, day, created_at) VALUES (?, ?, ?)",
            (name, day, stamp),
        ).rowcount:
            continue
        text = (
            f"daily digest for {name} {day}: {_plural(len(commits), 'commit', 'commits')}. "
            "Write one card that says what landed today, grouped by area, why it matters "
            "(use the 'why it changed' material), and who was busy. Cite the newest commit."
        )
        conn.execute(
            "INSERT INTO leads(repo, story_type, kind, path, commit_sha, lead_key, text, strength, "
            "head_sha, first_seen_at, last_seen_at) "
            "VALUES (?, 'before_after', 'commit', '', ?, ?, ?, ?, '', ?, ?) "
            "ON CONFLICT(repo, story_type, lead_key) DO NOTHING",
            (name, commits[0]["sha"], f"{DIGEST_PREFIX}{name}:{day}", text, DIGEST_STRENGTH,
             stamp, stamp),
        )  # fmt: skip
        made += 1
    conn.commit()
    return made


def mark_served(conn, lead_id: int) -> None:
    """If the lead is a "notif:" or "digest:" lead, point its record at the card that covers it.

    The caller owns the transaction. Read state is left as it is.
    """
    row = conn.execute(
        "SELECT l.lead_key, (SELECT c.id FROM cards c WHERE c.lead_id = l.id "
        "ORDER BY c.created_at DESC, c.id DESC LIMIT 1) AS card_id FROM leads l WHERE l.id = ?",
        (lead_id,),
    ).fetchone()
    if row and row["card_id"] and row["lead_key"].startswith(DIGEST_PREFIX):
        repo_day = row["lead_key"][len(DIGEST_PREFIX) :]
        repo, _, day = repo_day.rpartition(":")
        conn.execute(
            "UPDATE digests SET card_id = ? WHERE repo = ? AND day = ?",
            (row["card_id"], repo, day),
        )
    if row and row["card_id"] and row["lead_key"].startswith(NOTIF_PREFIX):
        conn.execute(
            "UPDATE notifications SET card_id = ? WHERE id = ?",
            (row["card_id"], int(row["lead_key"][len(NOTIF_PREFIX) :])),
        )


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
        ids = sorted(due)
        digest = hashlib.sha256("\n".join(ids).encode()).hexdigest()[:16]
        text = (
            "1 quiz card is back for another try"
            if n == 1
            else f"{n} quiz cards are back for another try"
        )
        made["srs_due"] += _add(conn, "srs_due", text, f"srs_due:{digest}", now)

    for name in cfg.repos:
        try:
            commits = recent_commits(cfg, name, now)
        except gitq.GitError:
            log.warning("hot files: cannot read %s", name)
            continue
        counts: dict[str, int] = {}
        for c in commits:
            for f in set(c["files"]):
                if not f.startswith("."):  # .beads/, .claude/ and the like change with every commit
                    counts[f] = counts.get(f, 0) + 1
        hot = sorted(
            ((n, path) for path, n in counts.items() if n >= HOT_FILE_COMMITS),
            key=lambda t: (-t[0], t[1]),
        )
        if hot:
            # One notification per repo per day, however many files or commits follow.
            key = f"hot_file:{name}:{now.date()}"
            if _add(conn, "hot_file", _hot_text(name, hot), key, now):
                made["hot_file"] += 1
                _link_hot_file(conn, name, hot[0], commits, key, now)

    for c in conn.execute(
        "SELECT c.id, c.spec, r.name AS repo FROM cards c JOIN repos r ON r.id = c.repo_id "
        "WHERE c.story_type = 'spot_the_bug' AND c.status = 'ready' AND c.created_at >= ? "
        "ORDER BY c.created_at, c.id",
        ((now - timedelta(seconds=DAY_S)).strftime(FMT),),
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


def _hot_repo(r) -> str:
    return r["dedup_key"].split(":", 1)[1].rsplit(":", 1)[0]


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
                # hot_file keys are "hot_file:<repo>:<date>"; the UI links it to /repo/<name>
                "repo": _hot_repo(r) if r["kind"] == "hot_file" else None,
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
        from gittok import supply  # supply imports this module

        while not self._stop.is_set():
            try:
                cfg = self._get_config()
                with closing(db.open_db(cfg.settings.data_dir / "gittok.db")) as conn:
                    now = self._clock()
                    generate_notifications(conn, cfg, now)
                    generate_digests(conn, cfg, now)
                    supply.notify_low_runway(conn, cfg, now)
                    supply.signal_wants_cards(conn, cfg, now)
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


def ensure_lan_token(data_dir) -> str:
    """The LAN pairing token in `<data_dir>/lan_token` (mode 0600); created when missing."""
    path = data_dir / "lan_token"
    try:
        token = path.read_text().strip()
        if token:
            return token
    except FileNotFoundError:
        pass
    private.make_dir(data_dir)
    token = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token + "\n")
    os.chmod(path, 0o600)
    return token

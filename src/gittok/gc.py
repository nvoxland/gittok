"""Garbage collection: delete cards and files that have no further use.

Kept for good: `stories` (duplicate checks), `rewards` and `weights` (learning), `runs` rows,
covered `leads`, and saved cards (`saved_cards`). A repo that is no longer configured is the
exception: `purge_repo` deletes all that GitTok holds for it, except the weights and the
rewards behind them (unlinked from the cards).
`delete_cards` is the one place that knows how to delete a card.
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

from gittok import db, private
from gittok.characters import FOLLOW_KEY

log = logging.getLogger(__name__)

LAST_FILE = "gc_last.json"


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


# --- deleting cards and repos ----------------------------------------------------------------

# Tables with a `card_id` column. `delete_cards` handles each one.
CARD_TABLES = frozenset({
    "card_features", "assets", "events", "rewards", "srs", "notifications", "saved_cards",
    "knowledge_events", "replies", "digests",
})  # fmt: skip
# Tables with a `repo` (name) or `repo_id` column. `_delete_repo_rows` handles each one.
_BY_NAME = (
    "story_views", "candidates", "candidate_ratings", "scout_batches", "leads", "knowledge",
    "knowledge_symbols", "digests",
)  # fmt: skip
_BY_REPO_ID = (
    "git_signals", "repo_groups", "mascots", "fact_builds", "fact_defines", "fact_calls",
    "fact_imports", "fact_touched", "fact_analyzers", "fact_schema",
)  # fmt: skip
REPO_TABLES = frozenset({*_BY_NAME, *_BY_REPO_ID, "stories", "runs", "cards"})
_FORGET = ("events", "knowledge_events", "saved_cards", "replies")
KEPT_KEY = "kept_repos"  # prefs: repos removed with keep_data, which gc must leave
_CHUNK = 500


def delete_cards(conn, ids: list[str], forget: bool = False) -> None:
    """Delete the rows of these cards. The caller owns the transaction; `card_dirs` gives the
    files, which go after the commit.

    Always: the card, its features, its asset rows and its review schedule (`srs`). Without
    `forget` (a card that got old) what the reader did stays: events, rewards, replies,
    and a notification loses only its link. With `forget` (the repo is gone) all of
    that goes too, and so does a saved mark, except the rewards: they lose the card link
    and keep their feature snapshot, because the learned weights stay."""
    for i in range(0, len(ids), _CHUNK):
        chunk = ids[i : i + _CHUNK]
        marks = ",".join("?" * len(chunk))
        conn.execute(f"DELETE FROM srs WHERE card_id IN ({marks})", chunk)
        if forget:
            for table in _FORGET:
                conn.execute(f"DELETE FROM {table} WHERE card_id IN ({marks})", chunk)
            # The weights keep what these cards taught, so their rewards stay as the evidence
            # (with the feature snapshot) for `relearn`, without a link to the card.
            conn.execute(
                "UPDATE rewards SET card_id = NULL, impression_event_id = NULL "
                f"WHERE card_id IN ({marks})",
                chunk,
            )
            conn.execute(f"DELETE FROM notifications WHERE card_id IN ({marks})", chunk)
            conn.execute(
                f"UPDATE replies SET answered_card_id = NULL WHERE answered_card_id IN ({marks})",
                chunk,
            )
            conn.execute(f"UPDATE digests SET card_id = NULL WHERE card_id IN ({marks})", chunk)
        else:
            conn.execute(
                f"UPDATE notifications SET card_id = NULL WHERE card_id IN ({marks})", chunk
            )
        conn.execute(f"DELETE FROM card_features WHERE card_id IN ({marks})", chunk)
        conn.execute(f"DELETE FROM assets WHERE card_id IN ({marks})", chunk)
        conn.execute(f"DELETE FROM cards WHERE id IN ({marks})", chunk)


def card_dirs(cfg, ids: list[str]) -> list[Path]:
    """The image folders of these cards that exist: <data_dir>/assets/<card id>."""
    root = cfg.settings.data_dir / "assets"
    return [root / i for i in ids if (root / i).is_dir()]


def _file_count(dirs: list[Path]) -> int:
    return sum(1 for d in dirs for p in d.rglob("*") if p.is_file())


def repo_card_ids(conn, name: str) -> list[str]:
    """Ids of the cards whose own repo (the first of their `repos`) is `name`."""
    rows = conn.execute(
        "SELECT c.id FROM cards c JOIN repos r ON r.id = c.repo_id WHERE r.name = ? ORDER BY c.id",
        (name,),
    )
    return [r[0] for r in rows]


def kept_repos(conn) -> set[str]:
    """Repos removed with keep_data: not configured, but their data is kept on purpose."""
    row = conn.execute("SELECT value FROM prefs WHERE key = ?", (KEPT_KEY,)).fetchone()
    return set(json.loads(row["value"])) if row else set()


def set_kept(conn, name: str, keep: bool) -> None:
    """Add `name` to the kept repos or take it out (the caller commits)."""
    names = kept_repos(conn)
    if (name in names) == keep:
        return
    names = names | {name} if keep else names - {name}
    conn.execute(
        "INSERT INTO prefs(key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (KEPT_KEY, json.dumps(sorted(names)), db.now_iso()),
    )


def _stored_repos(conn) -> set[str]:
    """Every repo name the database holds a row for."""
    names = {r[0] for r in conn.execute("SELECT name FROM repos")}
    for table in (*_BY_NAME, "stories"):
        names |= {
            r[0] for r in conn.execute(f"SELECT DISTINCT repo FROM {table}") if r[0] is not None
        }
    return names


def orphan_repos(conn, cfg) -> list[str]:
    """Repos with stored rows that are not configured and were not kept on purpose.

    None when no repo is configured at all: that is more likely a lost or broken
    repos.yaml than a wish to delete every card, so nothing is purged then."""
    if not cfg.repos:
        return []
    return sorted(_stored_repos(conn) - set(cfg.repos) - kept_repos(conn))


def _repo_runs(conn, name: str) -> list[str]:
    rows = conn.execute(
        "SELECT u.id FROM runs u JOIN repos r ON r.id = u.repo_id WHERE r.name = ?", (name,)
    )
    return [r[0] for r in rows]


def _delete_repo_rows(conn, name: str) -> int:
    """Delete every row GitTok holds for the repo `name`, in the caller's transaction.
    Returns how many steering rules went. Learned weights stay: they are about the reader."""
    delete_cards(conn, repo_card_ids(conn, name), forget=True)
    for table in _BY_NAME:
        conn.execute(f"DELETE FROM {table} WHERE repo = ?", (name,))
    # A story row stays only when a card of another repo still tells that story.
    conn.execute(
        "DELETE FROM stories WHERE repo = ? AND story_key NOT IN (SELECT story_key FROM cards)",
        (name,),
    )
    conn.execute("DELETE FROM notifications WHERE dedup_key LIKE ?", (f"hot_file:{name}:%",))
    rules = conn.execute(
        "DELETE FROM rules WHERE feature = 'repo' AND value = ?", (name,)
    ).rowcount
    row = conn.execute("SELECT value FROM prefs WHERE key = ?", (FOLLOW_KEY,)).fetchone()
    if row:
        left = [f for f in json.loads(row["value"]) if f[0] != name]
        conn.execute("UPDATE prefs SET value = ? WHERE key = ?", (json.dumps(left), FOLLOW_KEY))
    set_kept(conn, name, False)
    rid = conn.execute("SELECT id FROM repos WHERE name = ?", (name,)).fetchone()
    if rid is None:
        return rules
    for table in _BY_REPO_ID:
        conn.execute(f"DELETE FROM {table} WHERE repo_id = ?", (rid[0],))
    # Run rows stay (the daily run cap and the run history count them) without the repo's
    # brief; a run that is still open cannot go on.
    conn.execute(
        "UPDATE runs SET repo_id = NULL, brief = NULL, "
        "status = CASE status WHEN 'open' THEN 'expired' ELSE status END WHERE repo_id = ?",
        (rid[0],),
    )
    if conn.execute("SELECT 1 FROM cards WHERE repo_id = ?", (rid[0],)).fetchone() is None:
        conn.execute("DELETE FROM repos WHERE id = ?", (rid[0],))
    return rules


def _repo_plan(conn, cfg, name: str) -> tuple[list[str], list[Path]]:
    """(card ids, folders to delete) for the repo `name`."""
    ids = repo_card_ids(conn, name)
    runs_root = cfg.settings.data_dir / "runs"
    run_dirs = [runs_root / r for r in _repo_runs(conn, name) if (runs_root / r).is_dir()]
    return ids, [*card_dirs(cfg, ids), *run_dirs]


def purge_repo(conn, cfg, name: str) -> dict[str, int]:
    """Delete all that GitTok holds for the repo `name`: its cards with every row that hangs
    off them, the rows keyed by the repo, and then the card image files and run folders.

    The rows go in one transaction. The files go after the commit, so a crash leaves a whole
    database and at most some files with no rows. Returns {cards, files, rules}. The config
    files and the repo's own directory are not touched here."""
    ids, dirs = _repo_plan(conn, cfg, name)
    files = _file_count(dirs)
    with db.immediate(conn):
        rules = _delete_repo_rows(conn, name)
    for d in dirs:
        shutil.rmtree(d, ignore_errors=True)
    return {"cards": len(ids), "files": files, "rules": rules}


# --- the rules for old cards -----------------------------------------------------------------


def _card_victims(conn, cfg, now: datetime) -> dict[str, list[str]]:
    """Card ids to delete, by rule. Each card is in at most one list."""
    g = cfg.settings.gc
    cut = {
        "failed": _iso(now - timedelta(days=g.failed_after_days)),
        "unseen": _iso(now - timedelta(days=g.unseen_after_days)),
    }
    liked_ms = _ms(now - timedelta(days=g.liked_after_days))
    protect_until = _iso(now + timedelta(days=g.srs_keep_days))
    out: dict[str, list[str]] = {k: [] for k in ("seen", "liked", "unseen", "failed")}
    rows = conn.execute(
        "WITH last_imp AS (SELECT card_id, MAX(ts) AS ts FROM events "
        "  WHERE type = 'impression' GROUP BY card_id) "
        "SELECT c.id, c.status, c.created_at, s.liked AS story_liked, "
        "  (SELECT MAX(ts) FROM events WHERE card_id = c.id AND type = 'impression') AS last_imp, "
        "  (SELECT MAX(CAST(strftime('%s', computed_at) AS INTEGER)) * 1000 FROM rewards "
        "     WHERE card_id = c.id) AS last_reward, "
        "  (SELECT data FROM events WHERE card_id = c.id AND type = 'like' "
        "     ORDER BY ts DESC, id DESC LIMIT 1) AS like_data, "
        "  (SELECT COUNT(*) FROM last_imp l WHERE l.ts > COALESCE( "
        "     (SELECT ts FROM last_imp WHERE card_id = c.id), "
        "     (SELECT MAX(CAST(strftime('%s', computed_at) AS INTEGER)) * 1000 FROM rewards "
        "        WHERE card_id = c.id))) AS later, "
        "  EXISTS (SELECT 1 FROM saved_cards WHERE card_id = c.id) AS saved, "
        "  EXISTS (SELECT 1 FROM srs WHERE card_id = c.id AND mastered = 0 AND due_at <= ?) "
        "     AS protected, "
        "  EXISTS (SELECT 1 FROM events WHERE card_id = c.id AND type = 'impression') AS shown "
        "FROM cards c LEFT JOIN stories s ON s.story_key = c.story_key",
        (protect_until,),
    ).fetchall()
    for r in rows:
        if r["protected"] or r["saved"]:
            continue
        if r["status"] == "render_failed":
            if r["created_at"] < cut["failed"]:
                out["failed"].append(r["id"])
        elif r["last_reward"] is not None:
            last = r["last_imp"] if r["last_imp"] is not None else r["last_reward"]
            if _is_liked(r["like_data"], r["story_liked"]):
                if last < liked_ms:
                    out["liked"].append(r["id"])
            elif r["later"] >= g.seen_after_cards:
                out["seen"].append(r["id"])
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


def _big_logs(data_dir, max_kb: int) -> list:
    logs = data_dir / "logs"
    if not logs.is_dir():
        return []
    return [p for p in sorted(logs.glob("*.log")) if p.stat().st_size > max_kb * 1024]


def _trim_log(path, keep_bytes: int) -> None:
    """Keep the newest `keep_bytes` of a log, cut at a line start."""
    data = path.read_bytes()[-keep_bytes:]
    nl = data.find(b"\n")
    path.write_bytes(data[nl + 1 :] if nl >= 0 else data)


def collect(
    conn, cfg, now: datetime, dry_run: bool = False, vacuum: bool = False
) -> dict[str, int]:
    """Delete what has no further use. Returns counts per rule; `dry_run` changes nothing."""
    g = cfg.settings.gc
    data_dir = cfg.settings.data_dir
    victims = _card_victims(conn, cfg, now)
    ids = [i for k in ("seen", "liked", "unseen", "failed") for i in victims[k]]
    asset_dirs = card_dirs(cfg, ids)
    orphans = orphan_repos(conn, cfg)
    orphan_plans = [_repo_plan(conn, cfg, name) for name in orphans]
    orphan_dirs = [d for _, dirs in orphan_plans for d in dirs]
    run_dirs = _run_dirs(conn, cfg, now)
    big_logs = _big_logs(data_dir, g.log_max_kb)
    event_args = (_ms(now - timedelta(days=g.events_after_days)),)
    social_cut = _iso(now - timedelta(days=g.social_after_days))
    lead_cut = _iso(now - timedelta(days=g.leads_after_days))

    counts = {k: len(v) for k, v in victims.items()}
    counts["run_files"] = len(run_dirs)
    counts["log_files"] = len(big_logs)
    counts["asset_files"] = _file_count(asset_dirs)
    # Repos that are no longer configured: all their data goes, whatever its age.
    counts["orphan_repos"] = len(orphans)
    counts["orphan_cards"] = sum(len(i) for i, _ in orphan_plans)
    counts["orphan_files"] = _file_count(orphan_dirs)
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
    counts["leads"] = conn.execute(
        "SELECT COUNT(*) FROM leads WHERE last_seen_at < ? AND times_covered = 0", (lead_cut,)
    ).fetchone()[0]
    if dry_run:
        return counts

    with db.immediate(conn):
        delete_cards(conn, ids)
        for name in orphans:
            _delete_repo_rows(conn, name)
        conn.execute(f"DELETE FROM events WHERE {_OLD_EVENT}", event_args)
        conn.execute("DELETE FROM story_views WHERE seen_at < ?", (social_cut,))
        conn.execute("DELETE FROM leads WHERE last_seen_at < ? AND times_covered = 0", (lead_cut,))
        conn.execute(
            "DELETE FROM notifications WHERE read_at IS NOT NULL AND read_at < ?", (social_cut,)
        )
    for d in (*asset_dirs, *run_dirs, *orphan_dirs):
        shutil.rmtree(d, ignore_errors=True)
    for p in big_logs:
        _trim_log(p, g.log_max_kb * 1024 // 2)
    conn.execute("PRAGMA optimize")
    if vacuum:
        conn.execute("VACUUM")
    private.make_dir(data_dir)
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
                with closing(db.open_db(cfg.settings.data_dir / "gittok.db")) as conn:
                    collect(conn, cfg, self._clock())
            except Exception:
                log.exception("gc pass failed")
            self._stop.wait(interval if interval is not None else 3600.0)

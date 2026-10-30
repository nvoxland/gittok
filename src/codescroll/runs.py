"""Agent run lifecycle: open, submit cards, finish."""

from __future__ import annotations

import json
import secrets
from collections import Counter
from datetime import UTC, datetime, timedelta

from codescroll import db, store, validator


class RunError(Exception):
    """Message is shown to the agent: keep it short and actionable."""


class RunLimitError(RunError):
    pass


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_run_id(now: datetime) -> str:
    return f"r_{int(now.timestamp() * 1000):012x}{secrets.token_hex(4)}"


def open_run(
    conn, cfg, *, repo: str | None, brief: str, requested: int, now: datetime | None = None
) -> str:
    now = now or datetime.now(UTC)
    max_count = cfg.settings.agent.max_count
    if not 1 <= requested <= max_count:
        raise RunError(f"requested must be between 1 and {max_count}; got {requested}")
    expire_stale(conn, now=now)
    limit = cfg.settings.agent.per_day_runs
    recent = [
        r[0]
        for r in conn.execute(
            "SELECT started_at FROM runs WHERE status != 'expired' AND started_at > ? "
            "ORDER BY started_at",
            (_iso(now - timedelta(hours=24)),),
        )
    ]
    if len(recent) >= limit:
        free_at = datetime.strptime(recent[-limit], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        retry = _iso(free_at + timedelta(hours=24))
        raise RunLimitError(f"daily run limit reached ({limit}); try again after {retry}")
    run_id = _new_run_id(now)
    repo_id = store.ensure_repo(conn, cfg.repos[repo]) if repo else None
    with conn:
        conn.execute(
            "INSERT INTO runs(id, repo_id, status, brief, requested, meta, started_at) "
            "VALUES (?, ?, 'open', ?, ?, ?, ?)",
            (run_id, repo_id, brief, requested, db.dumps({"mcp_calls": {}}), _iso(now)),
        )
    return run_id


def get_run(conn, run_id) -> dict | None:
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    out = dict(row)
    out["reject_reasons"] = db.loads(out["reject_reasons"])
    out["meta"] = db.loads(out["meta"])
    return out


MAX_CARDS_PER_CALL = 40


def submit(conn, cfg, run_id: str, cards: list | dict) -> dict:
    raw = cards
    if isinstance(cards, dict):
        cards = cards.get("cards")
    if not isinstance(cards, list):
        raise RunError('submit {"cards": [...]} or a list of card objects')
    if len(cards) > MAX_CARDS_PER_CALL:
        raise RunError(f"at most {MAX_CARDS_PER_CALL} cards per call; got {len(cards)}")
    _check_open(get_run(conn, run_id), run_id)
    # Git validation is slow: do it before taking the write lock.
    accepted, rejected = validator.validate_cards(cards, cfg.repos, list(cfg.personas))
    out_dir = cfg.settings.data_dir / "runs" / run_id
    stored: list[dict] = []
    with db.immediate(conn):
        run = get_run(conn, run_id)
        _check_open(run, run_id)
        n = run["submissions"] + 1
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"submission-{n}.json").write_text(json.dumps(raw, indent=2, ensure_ascii=False))
        quota = run["requested"] - run["accepted"] if run["requested"] is not None else None
        seen: set[str] = set()
        for a in accepted:
            if a.story_key in seen or store.story_key_exists(conn, a.story_key, since_days=36500):
                rejected.append(
                    validator.Rejection(a.index, "duplicate_story", "already in the feed")
                )
            elif quota is not None and len(stored) >= quota:
                rejected.append(
                    validator.Rejection(a.index, "over_quota", "run quota is already filled")
                )
            else:
                seen.add(a.story_key)
                card_id = store.insert_card(conn, cfg, run_id, a)
                stored.append({"index": a.index, "card_id": card_id})
        rejected.sort(key=lambda r: r.index)
        rej = [r.as_dict() for r in rejected]
        reasons = run["reject_reasons"] + [{**r, "submission": n} for r in rej]
        conn.execute(
            "UPDATE runs SET accepted = accepted + ?, rejected = rejected + ?, "
            "submissions = ?, reject_reasons = ? WHERE id = ?",
            (len(stored), len(rej), n, db.dumps(reasons), run_id),
        )
        run = get_run(conn, run_id)
    return {
        "run_id": run_id,
        "submission": n,
        "accepted": stored,
        "rejected": rej,
        "totals": {
            "accepted": run["accepted"],
            "rejected": run["rejected"],
            "requested": run["requested"],
            "remaining": max(0, run["requested"] - run["accepted"]),
        },
    }


def _check_open(run: dict | None, run_id: str) -> None:
    if run is None:
        raise RunError(f"unknown run {run_id}; call get_brief for a new run")
    if run["status"] != "open":
        raise RunError(f"run {run_id} is {run['status']}; call get_brief for a new run")


def _summary(run: dict) -> dict:
    counts = Counter(r["reason"] for r in run["reject_reasons"])
    return {
        "run_id": run["id"],
        "status": run["status"],
        "accepted": run["accepted"],
        "rejected": run["rejected"],
        "submissions": run["submissions"],
        "duration_ms": run["duration_ms"],
        "top_reject_reasons": [[k, v] for k, v in counts.most_common(5)],
        "mcp_calls": run["meta"].get("mcp_calls", {}),
    }


def finish_run(conn, run_id: str, notes: dict | None = None, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    run = get_run(conn, run_id)
    if run is None:
        raise RunError(f"unknown run {run_id}; call get_brief for a new run")
    if run["status"] == "open":
        started = datetime.strptime(run["started_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        duration_ms = int((now - started).total_seconds() * 1000)
        meta = {**run["meta"], "notes": notes}
        with conn:
            conn.execute(
                "UPDATE runs SET status = 'finished', finished_at = ?, duration_ms = ?, "
                "meta = ? WHERE id = ?",
                (_iso(now), duration_ms, db.dumps(meta), run_id),
            )
        run = get_run(conn, run_id)
    return _summary(run)


def expire_stale(conn, hours: int = 24, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    with conn:
        cur = conn.execute(
            "UPDATE runs SET status = 'expired' WHERE status = 'open' AND started_at < ?",
            (_iso(now - timedelta(hours=hours)),),
        )
    return cur.rowcount


def bump_call(conn, run_id: str, tool: str) -> None:
    """Count one tool call on an open run, in a single atomic UPDATE."""
    key = f'"{tool}"'
    with conn:
        conn.execute(
            "UPDATE runs SET meta = json_set(meta, '$.mcp_calls', json_set("
            "COALESCE(json_extract(meta, '$.mcp_calls'), json('{}')), '$.' || ?, "
            "COALESCE(json_extract(meta, '$.mcp_calls.' || ?), 0) + 1)) "
            "WHERE id = ? AND status = 'open'",
            (key, key, run_id),
        )

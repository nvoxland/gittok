"""The lead ledger: every lead the analysis offered, keyed by git identity.

A commit lead is keyed by its sha. A path lead is keyed by path and blob sha, so a changed
file is a new row. Coverage and reward live on the row. See docs/learning.md, "Lead ledger".
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from codescroll import brief, db, learning

WIDE_LIMIT = 50  # leads kept per story type per refresh
UNKNOWN_INTEREST = 0.5


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def refresh(conn, repo_name: str, sig: dict, t0, head_sha: str, blobs: dict, now: datetime) -> int:
    """Upsert every commit and path lead of every story type. Returns the rows touched.

    `blobs` maps path -> blob sha at the analyzed ref. `strength` is 1 / (1 + rank) within
    the story type. Leads of kind "none" have no git identity and are not stored.
    """
    stamp = iso(now)
    types = dict.fromkeys(t for ts in brief.CATEGORY_STORIES.values() for t in ts)
    rows = []
    for t in types:
        for rank, ld in enumerate(brief.lead_refs_for(t, sig, t0, WIDE_LIMIT, repo=repo_name)):
            if ld.kind == "none":
                continue
            rows.append(
                (
                    repo_name,
                    t,
                    ld.kind,
                    ld.path or "",
                    ld.commit or "",
                    blobs.get(ld.path or "", "") if ld.kind == "path" else "",
                    db.dumps(list(ld.lines)) if ld.lines else None,
                    ld.text,
                    1 / (1 + rank),
                    head_sha,
                    stamp,
                    stamp,
                )
            )
    with db.immediate(conn):
        conn.executemany(
            "INSERT INTO leads(repo, story_type, kind, path, commit_sha, blob_sha, lines, text, "
            "strength, head_sha, first_seen_at, last_seen_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(repo, story_type, kind, path, commit_sha, blob_sha) DO UPDATE SET "
            "lines = excluded.lines, text = excluded.text, strength = excluded.strength, "
            "head_sha = excluded.head_sha, last_seen_at = excluded.last_seen_at",
            rows,
        )
    return len(rows)


def _current(conn, repo: str, story_type: str) -> list:
    """Rows seen in the repo's latest refresh, i.e. still present at its current head."""
    return conn.execute(
        "SELECT * FROM leads WHERE repo = ? AND story_type = ? AND last_seen_at = "
        "(SELECT MAX(last_seen_at) FROM leads WHERE repo = ?) ORDER BY id",
        (repo, story_type, repo),
    ).fetchall()


def _interest(path: str, means: dict[str, tuple[float, float]]) -> float:
    """Mean dir interest over the parent dir prefixes of `path` (0.5 where unknown)."""
    parts = path.split("/")[:-1]
    if not parts:
        return UNKNOWN_INTEREST
    prefixes = ["/".join(parts[: i + 1]) for i in range(len(parts))]
    return sum(means[p][0] if p in means else UNKNOWN_INTEREST for p in prefixes) / len(prefixes)


def _lead(r) -> brief.Lead:
    return brief.Lead(
        r["story_type"],
        r["repo"],
        r["kind"],
        commit=r["commit_sha"] or None,
        path=r["path"] or None,
        lines=tuple(json.loads(r["lines"])) if r["lines"] else None,
        text=r["text"],
        id=r["id"],
    )


def ranked(
    conn, cfg, repo: str, story_type: str, now: datetime, limit: int, dir_means: dict | None = None
) -> list[brief.Lead]:
    """Current leads for one story type, best first, without leads still in their cooldown.

    score = interest x strength x 0.5 ** times_covered.
    """
    cutoff = iso(now - timedelta(days=cfg.settings.agent.lead_cooldown_days))
    if dir_means is None:
        dir_means = learning.posterior_means(conn, cfg, "dir", now)
    rows = [
        r
        for r in _current(conn, repo, story_type)
        if r["last_covered_at"] is None or r["last_covered_at"] < cutoff
    ]

    def score(r) -> float:
        return _interest(r["path"], dir_means) * r["strength"] * 0.5 ** r["times_covered"]

    rows.sort(key=lambda r: (-score(r), r["id"]))
    return [_lead(r) for r in rows[:limit]]


def for_brief(conn, cfg, repos, now: datetime, limit: int = WIDE_LIMIT) -> dict:
    """`build_brief(ledger=...)` input: (repo, story type) -> ranked leads.

    A pair is present when the repo has current ledger rows for the type, even if all are in
    cooldown (the list is then empty: nothing fresh to offer). Absent pairs fall back to
    computing leads from signals.
    """
    dir_means = learning.posterior_means(conn, cfg, "dir", now)
    types = dict.fromkeys(t for ts in brief.CATEGORY_STORIES.values() for t in ts)
    out = {}
    for repo in repos:
        for t in types:
            if _current(conn, repo, t):
                out[(repo, t)] = ranked(conn, cfg, repo, t, now, limit, dir_means)
    return out


def _sha_match(a: str, b: str) -> bool:
    """Full or abbreviated shas of one commit (7+ hex chars)."""
    a, b = a.lower(), b.lower()
    return len(a) >= 7 and len(b) >= 7 and (a.startswith(b) or b.startswith(a))


def _cited(card: dict) -> tuple[list[str], list[str]]:
    """Commits and paths a card cites in its sources, visual, and depth panels."""
    parts = [*card.get("sources", []), card.get("visual", {}), *card.get("depth", [])]
    commits = [p["commit"] for p in parts if p.get("commit")]
    paths = [p["path"] for p in parts if p.get("path")]
    return commits, paths


def match_lead(card: dict, lead_refs: list[dict]) -> dict | None:
    """The packet lead (with a ledger id) a card used: by cited commit first, else by path."""
    commits, paths = _cited(card)
    leads = [x for x in lead_refs if x.get("id") is not None]
    for x in leads:
        if x.get("commit") and any(_sha_match(x["commit"], c) for c in commits):
            return x
    for x in leads:
        if x.get("path") and x["path"] in paths:
            return x
    return None


def mark_covered(conn, lead_id: int, now: datetime) -> None:
    """Count one card on a lead (caller owns the transaction)."""
    conn.execute(
        "UPDATE leads SET times_covered = times_covered + 1, last_covered_at = ? WHERE id = ?",
        (iso(now), lead_id),
    )

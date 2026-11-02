"""The lead ledger: every lead the analysis offered, keyed by git identity.

A commit lead is keyed by sha and path, a path lead by its path (an edit to the file keeps its
row and its cooldown), and a lead with no git identity by a synthetic key ("dir:src",
"pair:a|b"). Coverage and reward live on the row. A lead also stays out of the brief while its
story is blocked (`offerable`). See docs/learning.md, "Lead ledger".
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from codescroll import (
    brief,
    candidate_leads,
    db,
    knowledge,
    learning,
    replies,
    requests,
    social,
    store,
    storykey,
)

WIDE_LIMIT = 50  # leads kept per story type per refresh
UNKNOWN_INTEREST = 0.5


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def lead_key(ld: brief.Lead) -> str:
    """The ledger identity of a lead (the `lead_key` column)."""
    if ld.key:
        return ld.key
    if ld.kind == "commit":
        return f"c:{ld.commit or ''}:{ld.path or ''}"
    if ld.kind == "path":
        return f"p:{ld.path or ''}"
    return f"n:{ld.text}"


def _row(repo, ld, blobs, strength, head_sha, stamp) -> tuple:
    return (
        repo,
        ld.story_type,
        ld.kind,
        ld.path or "",
        ld.commit or "",
        blobs.get(ld.path or "", "") if ld.kind == "path" else "",
        lead_key(ld),
        db.dumps(list(ld.lines)) if ld.lines else None,
        ld.text,
        strength,
        head_sha,
        stamp,
        stamp,
    )


def _candidate_rows(
    conn, repo: str, sig: dict, t0, head_sha: str, blobs: dict, stamp: str, files=None
):
    """Rows for the story types that come from rated candidates (candidate_leads)."""
    return [
        _row(repo, ld, blobs, strength, head_sha, stamp)
        for t in brief.CANDIDATE_STORIES
        for ld, strength in candidate_leads.leads_for(conn, repo, t, sig, t0, WIDE_LIMIT, files)
    ]


_UPSERT = (
    "INSERT INTO leads(repo, story_type, kind, path, commit_sha, blob_sha, lead_key, "
    "lines, text, strength, head_sha, first_seen_at, last_seen_at) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
    "ON CONFLICT(repo, story_type, lead_key) DO UPDATE SET "
    "blob_sha = excluded.blob_sha, lines = excluded.lines, text = excluded.text, "
    "strength = excluded.strength, "
    "head_sha = excluded.head_sha, last_seen_at = excluded.last_seen_at"
)


def refresh(
    conn, repo_name: str, sig: dict, t0, head_sha: str, blobs: dict, now: datetime, files=None
) -> int:
    """Upsert every commit and path lead of every story type. Returns the rows touched.

    `blobs` maps path -> blob sha at the analyzed ref. `strength` is 1 / (1 + rank) within
    the story type, except for the candidate story types, whose strength comes from the scout
    rating (candidate_leads). Leads of kind "none" are stored under their synthetic key.
    """
    stamp = iso(now)
    types = dict.fromkeys(t for ts in brief.CATEGORY_STORIES.values() for t in ts)
    rows = []
    for t in types:
        for rank, ld in enumerate(
            brief.lead_refs_for(t, sig, t0, WIDE_LIMIT, repo=repo_name, files=files)
        ):
            rows.append(_row(repo_name, ld, blobs, 1 / (1 + rank), head_sha, stamp))
    rows += _candidate_rows(conn, repo_name, sig, t0, head_sha, blobs, stamp, files)
    with db.immediate(conn):
        conn.executemany(_UPSERT, rows)
    return len(rows)


_SERVER_PREFIXES = (
    requests.KEY_PREFIX,
    social.NOTIF_PREFIX,
    social.DIGEST_PREFIX,
    replies.KEY_PREFIX,
)
# SQL for "a server-made pinned lead" and its negation, built from _SERVER_PREFIXES so a new
# prefix is added in one place.
_PINNED_SQL = "(" + " OR ".join(f"lead_key LIKE '{p}%'" for p in _SERVER_PREFIXES) + ")"
_NOT_PINNED_SQL = " AND ".join(f"lead_key NOT LIKE '{p}%'" for p in _SERVER_PREFIXES)


def refresh_candidates(conn, repo: str, sig: dict, t0, head_sha: str, now: datetime) -> int:
    """Redo the candidate leads of a repo whose latest refresh already ran.

    The scout rates windows after the analysis, so the leads made at refresh time are stale
    by the time of a brief. The rows keep the repo's latest `last_seen_at` (they stay current
    with the other leads); keys the new pass no longer offers are made non-current.
    """
    stamp = conn.execute(
        f"SELECT MAX(last_seen_at) FROM leads WHERE repo = ? AND {_NOT_PINNED_SQL}",
        (repo,),
    ).fetchone()[0]
    if stamp is None:
        return 0
    rows = _candidate_rows(conn, repo, sig, t0, head_sha, {}, stamp)
    keep = {(r[1], r[6]) for r in rows}
    with db.immediate(conn):
        for r in conn.execute(
            "SELECT id, story_type, lead_key FROM leads WHERE repo = ? AND lead_key LIKE 'cand:%' "
            "AND last_seen_at = ?",
            (repo, stamp),
        ).fetchall():
            if (r["story_type"], r["lead_key"]) not in keep:
                conn.execute("UPDATE leads SET last_seen_at = '' WHERE id = ?", (r["id"],))
        conn.executemany(_UPSERT, rows)
    return len(rows)


def _in_files(r, files) -> bool:
    """A stored row whose place the file set does not read (an old row, or a profile written
    since) is dropped. Server-made pinned leads are exempt."""
    return _pinned(r) or brief.place_ok(files, r["path"] or None, r["lead_key"])


def _current(conn, repo: str, story_type: str, files=None) -> list:
    """Rows seen in the repo's latest refresh, i.e. still present at its current head, and
    inside the file set (`files`; the bootstrap set when None).

    Unserved follow-up requests ("req:" keys) always count: no refresh drops them.
    """
    rows = conn.execute(
        "SELECT * FROM leads WHERE repo = ? AND story_type = ? AND (last_seen_at = "
        f"(SELECT MAX(last_seen_at) FROM leads WHERE repo = ? AND {_NOT_PINNED_SQL}) "
        f"OR ({_PINNED_SQL} AND last_covered_at IS NULL)) ORDER BY id",
        (repo, story_type, repo),
    ).fetchall()
    if story_type in brief.CANDIDATE_STORIES:  # churn rows from before candidate leads are dead
        rows = [r for r in rows if r["lead_key"].startswith(("cand:", *_SERVER_PREFIXES))]
    return [r for r in rows if _in_files(r, files)]


def _interest(path: str, means: dict[str, tuple[float, float]]) -> float:
    """Mean dir interest over the parent dir prefixes of `path` (0.5 where unknown)."""
    parts = path.split("/")[:-1]
    if not parts:
        return UNKNOWN_INTEREST
    prefixes = ["/".join(parts[: i + 1]) for i in range(len(parts))]
    return sum(means[p][0] if p in means else UNKNOWN_INTEREST for p in prefixes) / len(prefixes)


def _pinned(r) -> bool:
    """Server-made leads (follow-up requests, hot-file notifications) skip filters and go first."""
    return r["lead_key"].startswith(_SERVER_PREFIXES)


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
        key=r["lead_key"],
    )


def _blocked_stories(conn, cfg, now: datetime) -> list:
    """Stories no card of any format may join now (`store.variant_blocker` rejects every format)."""
    formats = dict.fromkeys([*brief.CATEGORY_FORMATS_FLAT, *brief.CROSS_FORMATS])
    agent = cfg.settings.agent
    return [
        r
        for r in conn.execute("SELECT * FROM stories")
        if all(store.variant_blocker(r, f, agent, now) for f in formats)
    ]


class _StoryBlocks:
    """Blocked stories indexed by (repo, story type): their keys, commits, and paths."""

    def __init__(self, stories: list):
        self.by_type: dict[tuple[str, str], dict] = {}
        for r in stories:
            e = self.by_type.setdefault(
                (r["repo"], r["story_type"]), {"keys": set(), "commits": [], "paths": []}
            )
            e["keys"].add(r["story_key"])
            srcs = [x for x in db.loads(r["sources"]) if x.get("repo", r["repo"]) == r["repo"]]
            e["commits"] += [x["commit"] for x in srcs if x.get("commit")]
            e["paths"].append({x["path"] for x in srcs if x.get("path")})

    def blocks(self, ld: brief.Lead) -> bool:
        """True if a blocked story of the lead's type has its exact key, or cites its place.

        A lead cannot always predict the key (a card may cite another line range, or a second
        source), so a commit lead matches any source with that commit, and a path lead any
        source with that path. A file-pair lead needs both files.
        """
        e = self.by_type.get((ld.repo, ld.story_type))
        if not e:
            return False
        if ld.kind == "commit" and ld.commit:
            key = storykey.story_key(ld.story_type, ld.repo, commit=ld.commit)
            return key in e["keys"] or any(_sha_match(ld.commit, c) for c in e["commits"])
        if ld.kind == "path" and ld.path:
            want = {ld.path}
            if ld.key and ld.key.startswith("pair:"):
                want |= set(ld.key[5:].split("|"))
            return any(want <= paths for paths in e["paths"])
        return False


def card_subject(spec: dict, default_repo: str = "") -> tuple[str, str | None, str | None]:
    """(repo, commit, path) a card is mainly about: its visual's commit or path, else its first
    source's. A visual with neither (a meme, a chart) falls back to the first source."""
    vis = spec.get("visual") or {}
    srcs = spec.get("sources") or []
    for part in (vis, *srcs[:1]):
        if part.get("commit") or part.get("path"):
            repo = part.get("repo") or default_repo
            return repo, part.get("commit") or None, part.get("path") or None
    return default_repo, None, None


class _Subjects:
    """Commits and paths that were the subject of a card made in the subject cooldown window."""

    def __init__(self, conn, cfg, now: datetime):
        cutoff = iso(now - timedelta(days=cfg.settings.agent.subject_cooldown_days))
        self.commits: dict[str, list[str]] = {}
        self.paths: dict[str, set[str]] = {}
        for r in conn.execute(
            "SELECT spec FROM cards WHERE status IN ('ready', 'pending_render') "
            "AND created_at >= ?",
            (cutoff,),
        ):
            spec = db.loads(r["spec"])
            repo, commit, path = card_subject(spec, (spec.get("repos") or [""])[0])
            if commit:
                self.commits.setdefault(repo, []).append(commit)
            if path:
                self.paths.setdefault(repo, set()).add(path)

    def blocks(self, ld: brief.Lead) -> bool:
        """True if the lead's commit or path is a recent card's subject."""
        if ld.commit and any(_sha_match(ld.commit, c) for c in self.commits.get(ld.repo, ())):
            return True
        return bool(ld.path) and ld.path in self.paths.get(ld.repo, ())


def offerable(conn, cfg, now: datetime) -> Callable[[brief.Lead], bool]:
    """Predicate for leads that did not come from the ledger (or came without a check).

    A lead is not offerable while it is in its cooldown, or while its story is blocked.
    """
    cutoff = iso(now - timedelta(days=cfg.settings.agent.lead_cooldown_days))
    covered = {
        (r["repo"], r["story_type"], r["lead_key"]): r["last_covered_at"]
        for r in conn.execute("SELECT * FROM leads WHERE last_covered_at >= ?", (cutoff,))
    }
    blocks = _StoryBlocks(_blocked_stories(conn, cfg, now))
    subjects = _Subjects(conn, cfg, now)

    def ok(ld: brief.Lead) -> bool:
        return (
            (ld.repo, ld.story_type, lead_key(ld)) not in covered
            and not blocks.blocks(ld)
            and not subjects.blocks(ld)
        )

    return ok


def ranked(
    conn,
    cfg,
    repo: str,
    story_type: str,
    now: datetime,
    limit: int,
    dir_means: dict | None = None,
    blocks: _StoryBlocks | None = None,
    nmap: dict | None = None,
    subjects: _Subjects | None = None,
    files=None,
) -> list[brief.Lead]:
    """Current leads for one story type, best first, without leads still in their cooldown
    or whose story is blocked.

    score = (0.5 + interest) x strength x novelty x 0.5 ** times_covered x 0.5 ** rejects.

    `rejects` counts the cards rejected on the lead in the last `agent.subject_cooldown_days`.
    A lead is also left out while its commit or path is the subject of a recent card (any
    story type). Server-made leads (requests, notifications) skip both filters.

    Novelty (knowledge.lead_dir; 1.0 for an unknown dir) leads: what the reader has not learned
    comes first. Interest is a mild factor in [0.5, 1.5] so it only breaks near-ties; it stays
    because the learned dir reward is still the best signal of what the reader enjoys. Novelty
    already falls as cards are seen, so `times_covered` is the only other repeat brake.
    """
    cutoff = iso(now - timedelta(days=cfg.settings.agent.lead_cooldown_days))
    if dir_means is None:
        dir_means = learning.posterior_means(conn, cfg, "dir", now)
    if blocks is None:
        blocks = _StoryBlocks(_blocked_stories(conn, cfg, now))
    if subjects is None:
        subjects = _Subjects(conn, cfg, now)
    reject_cutoff = iso(now - timedelta(days=cfg.settings.agent.subject_cooldown_days))
    rows = [
        r
        for r in _current(conn, repo, story_type, files or cfg.fileset(repo))
        if (r["last_covered_at"] is None or r["last_covered_at"] < cutoff)
        and (_pinned(r) or not (blocks.blocks(_lead(r)) or subjects.blocks(_lead(r))))
    ]

    if nmap is None:
        nmap = knowledge.novelty_map(conn, repo, cfg.settings.user.git_identities)

    def score(r) -> float:
        nov = knowledge.lead_dir(r["path"], nmap)[1]
        interest = 0.5 + _interest(r["path"], dir_means)
        rejects = r["times_rejected"] if (r["last_rejected_at"] or "") >= reject_cutoff else 0
        return interest * r["strength"] * nov * 0.5 ** r["times_covered"] * 0.5**rejects

    # Follow-up requests go first: the reader asked for them.
    rows.sort(key=lambda r: (not _pinned(r), -score(r), r["id"]))
    return [_lead(r) for r in rows[:limit]]


def for_brief(
    conn,
    cfg,
    repos,
    now: datetime,
    limit: int = WIDE_LIMIT,
    analyses: dict | None = None,
    filesets: dict | None = None,
) -> dict:
    """`build_brief(ledger=...)` input: (repo, story type) -> ranked leads.

    A pair is present when the repo has current ledger rows for the type, even if all are in
    cooldown (the list is then empty: nothing fresh to offer). Absent pairs fall back to
    computing leads from signals. `analyses` (repo -> signals.analyze result) lets the candidate
    leads be redone first, so ratings made since the last refresh count. `filesets` (repo ->
    FileSet; default: the config's) drops stored rows outside the repo's file set.
    """
    for repo, a in (analyses or {}).items():
        if repo in repos:
            refresh_candidates(
                conn, repo, a.get("signals") or {}, a.get("t0"), a.get("head_sha") or "", now
            )
    dir_means = learning.posterior_means(conn, cfg, "dir", now)
    blocks = _StoryBlocks(_blocked_stories(conn, cfg, now))
    subjects = _Subjects(conn, cfg, now)
    ids = cfg.settings.user.git_identities
    nmaps = {r: knowledge.novelty_map(conn, r, ids) for r in repos}
    types = dict.fromkeys(t for ts in brief.CATEGORY_STORIES.values() for t in ts)
    out = {}
    for repo in repos:
        fs = (filesets or {}).get(repo) or cfg.fileset(repo)
        for t in types:
            if _current(conn, repo, t, fs):
                out[(repo, t)] = ranked(
                    conn, cfg, repo, t, now, limit, dir_means, blocks, nmaps[repo], subjects, fs
                )
    return out


def variants(conn, cfg, now: datetime, limit: int = 30) -> list[dict]:
    """`build_brief(variants=...)` input: stories that may be retold in a new format.

    A story qualifies when it was liked or its best reward is `agent.variant_min_reward`, and
    its last card is `agent.variant_after_days` old. Liked first, then best reward. The hook is
    the newest card's; it is None when gc deleted every card of the story.
    """
    a = cfg.settings.agent
    rows = conn.execute(
        "SELECT * FROM stories WHERE (liked = 1 OR best_reward >= ?) AND last_card_at <= ? "
        "ORDER BY liked DESC, best_reward DESC, last_card_at, story_key LIMIT ?",
        (a.variant_min_reward, iso(now - timedelta(days=a.variant_after_days)), limit),
    ).fetchall()
    out = []
    for r in rows:
        card = conn.execute(
            "SELECT json_extract(spec, '$.hook') AS hook FROM cards WHERE story_key = ? "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            (r["story_key"],),
        ).fetchone()
        out.append(
            {
                "story_key": r["story_key"],
                "story_type": r["story_type"],
                "repo": r["repo"],
                "sources": json.loads(r["sources"]),
                "hook": card["hook"] if card else None,
                "formats_used": json.loads(r["formats"]),
                "best_reward": r["best_reward"],
            }
        )
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
    """The packet lead (with a ledger id) a card used.

    Only leads of the card's story type count. A commit lead matches by a cited commit, a path
    lead by a cited path (any line range), and a dir lead by a dir the card lists. Commits go
    first, then paths, then dirs.
    """
    commits, paths = _cited(card)
    stype = card.get("story_type")
    leads = [
        x
        for x in lead_refs
        if x.get("id") is not None and (stype is None or x.get("story_type") in (None, stype))
    ]
    for x in leads:
        if x.get("commit") and any(_sha_match(x["commit"], c) for c in commits):
            return x
    for x in leads:
        if x.get("path") and x["path"] in paths:
            return x
    dirs = card.get("dirs") or []
    for x in leads:
        if x.get("kind") == "none" and (x.get("key") or "").startswith("dir:"):
            if x["key"][4:] in dirs:
                return x
    return None


def mark_rejected(conn, lead_id: int, now: datetime) -> None:
    """Count one rejected card on a lead; its rank drops for `agent.subject_cooldown_days`."""
    conn.execute(
        "UPDATE leads SET times_rejected = times_rejected + 1, last_rejected_at = ? WHERE id = ?",
        (iso(now), lead_id),
    )


def mark_covered(conn, lead_id: int, now: datetime) -> None:
    """Count one card on a lead (caller owns the transaction)."""
    conn.execute(
        "UPDATE leads SET times_covered = times_covered + 1, last_covered_at = ? WHERE id = ?",
        (iso(now), lead_id),
    )
    requests.mark_served(conn, lead_id, iso(now))
    social.mark_served(conn, lead_id)

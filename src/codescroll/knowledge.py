"""What the reader already knows, per repo and dir prefix (docs/learning.md section 14).

`update` folds new events into the `knowledge` table (idempotent: every counted event is
recorded in `knowledge_events`). `novelty` turns the counts, plus churn and an optional
own-authorship prior, into a number in [0, 1]: 1 means "the reader has not learned this".
"""

from __future__ import annotations

from codescroll import db, signals

MAX_DEPTH = 2  # a card counts toward its dirs and their parents, at most 2 path levels deep
POS_SCALE = 4.0  # familiarity points that halve the base novelty
STRUGGLE_SCALE = 2.0  # struggle events that take the "struggle" lift to one half
CHURN_COMMITS = 10  # commits in 30 days that count as "changed a lot"
CHURN_WEIGHT = 0.3
OWN_WEIGHT = 0.25

_COUNT = {
    "seen": "cards_seen",
    "explain": "explains_opened",
    "right": "quiz_right",
    "wrong": "quiz_wrong",
    "knew_it": "knew_it",
    "teach_more": "teach_more",
}
_ONCE_PER_CARD = ("seen", "explain")
_TYPES = ("impression", "depth_open", "answer", "knew_it", "teach_more")


def _prefixes(dirs) -> set[str]:
    out = set()
    for d in dirs:
        parts = [p for p in d.split("/") if p]
        out |= {"/".join(parts[:i]) for i in range(1, min(len(parts), MAX_DEPTH) + 1)}
    return out


def _explain_panel(spec: dict) -> int | None:
    """Panel 0 is the visual; depth panel i is panel i + 1."""
    for i, p in enumerate(spec.get("depth") or []):
        if p.get("kind") == "explain":
            return i + 1
    return None


def _kind(conn, row, data: dict) -> str | None:
    t = row["type"]
    if t == "impression":
        return "seen"
    if t == "answer":
        return {True: "right", False: "wrong"}.get(data.get("correct"))
    if t == "depth_open":
        card = conn.execute("SELECT spec FROM cards WHERE id = ?", (row["card_id"],)).fetchone()
        panel = data.get("panel")
        explain = _explain_panel(db.loads(card["spec"]))
        return "explain" if explain is not None and panel == explain else None
    return t  # knew_it, teach_more


def update_in_tx(conn) -> int:
    """Count events not counted before. The caller owns the transaction. Returns the count."""
    marks = ",".join("?" * len(_TYPES))
    rows = conn.execute(
        "SELECT e.id, e.ts, e.card_id, e.type, e.data FROM events e "
        f"WHERE e.type IN ({marks}) AND e.card_id IS NOT NULL "
        "AND EXISTS (SELECT 1 FROM cards c WHERE c.id = e.card_id) "
        "AND NOT EXISTS (SELECT 1 FROM knowledge_events k WHERE k.event_id = e.id AND k.ts = e.ts) "
        "ORDER BY e.ts, e.id",
        _TYPES,
    ).fetchall()
    n = 0
    for row in rows:
        try:
            data = db.loads(row["data"])
            kind = _kind(conn, row, data if isinstance(data, dict) else {})
        except Exception:  # one odd event must not stop the rest
            kind = None
        if kind is None:
            continue
        repeat = (
            kind in _ONCE_PER_CARD
            and conn.execute(
                "SELECT 1 FROM knowledge_events WHERE card_id = ? AND kind = ?",
                (row["card_id"], kind),
            ).fetchone()
        )
        conn.execute(
            "INSERT INTO knowledge_events(event_id, ts, card_id, kind) VALUES (?, ?, ?, ?)",
            (row["id"], row["ts"], row["card_id"], kind),
        )
        n += 1
        if repeat:
            continue
        feats = conn.execute(
            "SELECT feature, value FROM card_features WHERE card_id = ? "
            "AND feature IN ('repo', 'dir')",
            (row["card_id"],),
        ).fetchall()
        repos = [f["value"] for f in feats if f["feature"] == "repo"]
        dirs = _prefixes(f["value"] for f in feats if f["feature"] == "dir")
        col = _COUNT[kind]
        for repo in repos:
            for d in dirs:
                conn.execute(
                    f"INSERT INTO knowledge(repo, dir, {col}, last_seen_ts) VALUES (?, ?, 1, ?) "
                    f"ON CONFLICT(repo, dir) DO UPDATE SET {col} = {col} + 1, "
                    "last_seen_ts = MAX(COALESCE(last_seen_ts, 0), excluded.last_seen_ts)",
                    (repo, d, row["ts"]),
                )
    return n


def update(conn) -> int:
    with db.immediate(conn):
        return update_in_tx(conn)


def combine(row, commits_30d: int = 0, own_share: float | None = None) -> float:
    """Novelty in [0, 1] from one dir's counts (formula: docs/learning.md section 14)."""

    def get(key):
        try:
            return row[key] or 0
        except (KeyError, IndexError):
            return 0

    pos = (
        get("cards_seen") + 2 * get("explains_opened") + 2 * get("quiz_right") + 4 * get("knew_it")
    )
    struggle = get("quiz_wrong") + get("teach_more")
    nov = 1 / (1 + pos / POS_SCALE)
    nov += (1 - nov) * struggle / (struggle + STRUGGLE_SCALE)
    nov += (1 - nov) * CHURN_WEIGHT * min(1.0, max(0, commits_30d) / CHURN_COMMITS)
    if own_share:
        nov *= 1 - OWN_WEIGHT * min(1.0, max(0.0, own_share))
    return round(max(0.0, min(1.0, nov)), 4)


def _churn_30d(conn, repo: str) -> dict[str, int]:
    churn = (signals.load_signals(conn, repo) or {}).get("churn") or {}
    return {r["path"]: r["commits"] for r in (churn.get("dirs") or {}).get("30", [])}


def own_shares(conn, repo: str, identities) -> dict[str, float]:
    """Top-level dir -> the reader's share of changed lines (names, case-insensitive)."""
    ids = {i.strip().lower() for i in identities or () if i and i.strip()}
    if not ids:
        return {}
    shares = (signals.load_signals(conn, repo) or {}).get("author_shares") or {}
    return {
        d: sum(a["share"] for a in authors if a["author"].lower() in ids)
        for d, authors in shares.get("by_dir", {}).items()
    }


def _own(shares: dict[str, float], d: str) -> float | None:
    return shares.get(d.split("/")[0])


def novelty(conn, repo: str, dir: str, own_share: float | None = None, identities=()) -> float:
    dir = dir.strip("/")
    row = conn.execute("SELECT * FROM knowledge WHERE repo = ? AND dir = ?", (repo, dir)).fetchone()
    if own_share is None:
        own_share = _own(own_shares(conn, repo, identities), dir)
    return combine(row or {}, _churn_30d(conn, repo).get(dir, 0), own_share)


def novelty_map(conn, repo: str, identities=()) -> dict[str, float]:
    """dir -> novelty for every dir with knowledge or a card in the repo (up to 2 levels)."""
    rows = {r["dir"]: r for r in conn.execute("SELECT * FROM knowledge WHERE repo = ?", (repo,))}
    carded = conn.execute(
        "SELECT DISTINCT d.value FROM card_features d JOIN card_features r "
        "ON r.card_id = d.card_id AND r.feature = 'repo' AND r.value = ? "
        "WHERE d.feature = 'dir'",
        (repo,),
    )
    dirs = set(rows) | _prefixes(r[0] for r in carded)
    churn, own = _churn_30d(conn, repo), own_shares(conn, repo, identities)
    return {d: combine(rows.get(d, {}), churn.get(d, 0), _own(own, d)) for d in sorted(dirs)}


def novelty_maps(conn, cfg, repos) -> dict[str, dict[str, float]]:
    """repo -> novelty_map, for `build_brief(novelty=...)`."""
    ids = cfg.settings.user.git_identities
    return {r: novelty_map(conn, r, ids) for r in repos}


def lead_dir(path: str | None, nmap: dict[str, float]) -> tuple[str | None, float]:
    """(dir, novelty) of a lead path: the deepest known prefix, at most 2 levels deep.

    A file uses its parent dirs; a dir lead (a path that is itself a known dir) uses itself.
    With no known prefix the dir is the path's first two dir levels and novelty is 1.0.
    A root-level file has no dir: (None, 1.0).
    """
    segs = [p for p in (path or "").split("/") if p][:MAX_DEPTH]
    if not segs:
        return None, 1.0
    for i in range(len(segs), 0, -1):
        d = "/".join(segs[:i])
        if d in nmap:
            return d, nmap[d]
    dirs = [p for p in (path or "").split("/") if p][:-1][:MAX_DEPTH]
    return ("/".join(dirs) or None), 1.0


def knowledge_rows(conn, cfg, limit: int = 10) -> list[dict]:
    """The most novel dirs first, for get_profile."""
    ids = cfg.settings.user.git_identities
    out = []
    for repo in cfg.repos:
        for d, v in novelty_map(conn, repo, ids).items():
            out.append({"repo": repo, "dir": d, "novelty": v})
    out.sort(key=lambda r: (-r["novelty"], r["repo"], r["dir"]))
    return out[:limit]

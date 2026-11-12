"""What the reader already knows, per repo and dir prefix (docs/learning.md section 14).

`update` folds new events into the `knowledge` table (idempotent: every counted event is
recorded in `knowledge_events`). `novelty` turns the counts, plus churn and an optional
own-authorship prior, into a number in [0, 1]: 1 means "the reader has not learned this".
"""

from __future__ import annotations

import re

from gittok import db, facts, signals
from gittok.profiles import fileset_for

MAX_DEPTH = 2  # a card counts toward its dirs and their parents, at most 2 path levels deep
POS_SCALE = 4.0  # familiarity points that halve the base novelty
STRUGGLE_SCALE = 2.0  # struggle events that take the "struggle" lift to one half
CHURN_COMMITS = 10  # commits in 30 days that count as "changed a lot"
CHURN_WEIGHT = 0.3
OWN_WEIGHT = 0.25
NEXT_DOOR_BOOST = 1.3  # a lead defines an unseen symbol that calls or is called by a seen one
SEEN_FLOOR = 0.5  # a lead whose symbols are all fully seen keeps this share of its score
MAX_NAME_DEFS = 3  # a backticked name that matches more definitions than this is too vague
_TICKS = re.compile(r"`([^`\s]{2,80})`")

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


_SYMBOL_COL = {"cards_seen": "seen"}


def _count_symbols(conn, row, col: str) -> None:
    col = _SYMBOL_COL.get(col, col)
    for repo, symbol in card_symbols(conn, row["card_id"]):
        conn.execute(
            f"INSERT INTO knowledge_symbols(repo, symbol, {col}, last_seen) VALUES (?, ?, 1, ?) "
            f"ON CONFLICT(repo, symbol) DO UPDATE SET {col} = {col} + 1, "
            "last_seen = MAX(COALESCE(last_seen, 0), excluded.last_seen)",
            (repo, symbol, row["ts"]),
        )


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)


def _innermost_defs(conn, repo_id: int, path: str, start: int, end: int) -> list[dict]:
    """Definitions overlapping lines start..end that hold no other overlapping definition."""
    defs = [
        dict(r)
        for r in conn.execute(
            'SELECT symbol, start, "end" FROM fact_defines '
            'WHERE repo_id = ? AND path = ? AND start <= ? AND "end" >= ? ORDER BY start',
            (repo_id, path, end, start),
        )
    ]
    return [
        d
        for d in defs
        if not any(
            o is not d
            and o["start"] >= d["start"]
            and o["end"] <= d["end"]
            and (o["start"], o["end"]) != (d["start"], d["end"])
            for o in defs
        )
    ]


def _repo_ids(conn) -> dict[str, int]:
    return {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM repos")}


def card_symbols(conn, card_id: str) -> list[tuple[str, str]]:
    """(repo, symbol) pairs a card teaches.

    From `resolved["facts"]` (fact ids) when the card has them and they name symbols. Else
    derived: definitions overlapping the lines of its code visual and code panels, plus
    backticked names that match few definitions in the card's repos.
    """
    row = conn.execute("SELECT spec, resolved FROM cards WHERE id = ?", (card_id,)).fetchone()
    if row is None:
        return []
    spec, resolved = db.loads(row["spec"]), db.loads(row["resolved"]) if row["resolved"] else {}
    ids = _repo_ids(conn)
    names = {v: k for k, v in ids.items()}
    out: dict[tuple[str, str], None] = {}
    for fid in (resolved or {}).get("facts") or []:
        fact = facts.get(conn, fid)
        if fact is None or fact.get("repo_id") not in names:
            continue
        for key in ("symbol", "caller_symbol", "callee_symbol"):
            if fact.get(key):
                out[(names[fact["repo_id"]], fact[key])] = None
    if out:
        return list(out)
    panels = [spec.get("visual") or {}, *(spec.get("depth") or [])]
    for p in panels:
        if p.get("kind") == "code" and p.get("path") and p.get("lines") and p.get("repo") in ids:
            lo, hi = p["lines"][0], p["lines"][-1]
            for d in _innermost_defs(conn, ids[p["repo"]], p["path"], lo, hi):
                out[(p["repo"], d["symbol"])] = None
    texts = [t for key in ("hook", "learn", "visual", "depth") for t in _strings(spec.get(key))]
    for m in dict.fromkeys(x for t in texts for x in _TICKS.findall(t)):
        name = m.removesuffix("()")
        for repo in spec.get("repos") or []:
            if repo not in ids:
                continue
            found = facts.definitions(conn, repo, name)
            if 0 < len(found) <= MAX_NAME_DEFS:
                out.update({(repo, d["symbol"]): None for d in found})
    return list(out)


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
        _count_symbols(conn, row, col=_COUNT[kind])
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
        get("cards_seen")
        + get("seen")
        + 2 * get("explains_opened")
        + 2 * get("quiz_right")
        + 4 * get("knew_it")
    )
    struggle = get("quiz_wrong") + get("teach_more")
    nov = 1 / (1 + pos / POS_SCALE)
    nov += (1 - nov) * struggle / (struggle + STRUGGLE_SCALE)
    nov += (1 - nov) * CHURN_WEIGHT * min(1.0, max(0, commits_30d) / CHURN_COMMITS)
    if own_share:
        nov *= 1 - OWN_WEIGHT * min(1.0, max(0.0, own_share))
    return round(max(0.0, min(1.0, nov)), 4)


class SymbolContext:
    """What the reader has seen in one repo's symbols, for ranking leads.

    `factor(path, lines)` is 1.0 for a window with no known definitions. Otherwise it is
    `SEEN_FLOOR + (1 - SEEN_FLOOR) * novelty` of the window's most novel symbol (fully seen
    symbols damp the lead), times `NEXT_DOOR_BOOST` when the window defines an unseen symbol
    that calls or is called by a seen one ("next door" learning).
    """

    def __init__(self, conn, repo: str):
        self.conn, self.repo = conn, repo
        self.repo_id = _repo_ids(conn).get(repo)
        self.rows = {
            r["symbol"]: r
            for r in conn.execute("SELECT * FROM knowledge_symbols WHERE repo = ?", (repo,))
        }
        self.seen = {s for s, r in self.rows.items() if r["seen"] > 0}
        self.next_door: set[str] = set()
        if self.seen and self.repo_id is not None:
            q = (
                "SELECT c.{a} AS s FROM fact_calls c JOIN knowledge_symbols k ON k.repo = ? "
                "AND k.symbol = c.{b} AND k.seen > 0 WHERE c.repo_id = ? AND c.{a} IS NOT NULL"
            )
            both = q.format(a="callee_symbol", b="caller_symbol")
            both += " UNION " + q.format(a="caller_symbol", b="callee_symbol")
            args = (repo, self.repo_id, repo, self.repo_id)
            self.next_door = {r["s"] for r in conn.execute(both, args)} - self.seen

    @property
    def active(self) -> bool:
        return bool(self.rows) and self.repo_id is not None

    def factor(self, path: str | None, lines=None) -> float:
        if not self.active or not path:
            return 1.0
        lo, hi = (lines[0], lines[-1]) if lines else (1, 10**9)
        syms = [d["symbol"] for d in _innermost_defs(self.conn, self.repo_id, path, lo, hi)]
        if not syms:
            return 1.0
        nov = max(combine(self.rows.get(s) or {}) for s in syms)
        f = SEEN_FLOOR + (1 - SEEN_FLOOR) * nov
        if any(s in self.next_door for s in syms):
            f *= NEXT_DOOR_BOOST
        return f


def map_files(conn, cfg, repo: str, limit: int = 15) -> list[dict]:
    """Per-file symbol coverage for the files with most callable definitions.

    `symbols_seen` counts callable definitions (function, method, class) with a card seen.
    """
    rid = _repo_ids(conn).get(repo)
    if rid is None:
        return []
    files = cfg.fileset(repo)
    marks = ",".join("?" * len(facts.CALLABLE))
    rows = conn.execute(
        "SELECT d.path AS path, COUNT(*) AS defined, "
        "SUM(COALESCE(k.seen, 0) > 0) AS seen FROM fact_defines d "
        "LEFT JOIN knowledge_symbols k ON k.repo = ? AND k.symbol = d.symbol "
        f"WHERE d.repo_id = ? AND d.kind IN ({marks}) GROUP BY d.path",
        (repo, rid, *sorted(facts.CALLABLE)),
    ).fetchall()
    rows = [r for r in rows if _visible(r["path"].rpartition("/")[0] or "", files)]
    rows.sort(key=lambda r: (-r["defined"], r["path"]))
    return [
        {"path": r["path"], "symbols_defined": r["defined"], "symbols_seen": r["seen"] or 0}
        for r in rows[:limit]
    ]


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


def _visible(d: str, files=None) -> bool:
    """False for a dir the repo's file set ignores or classes as fixture, generated, vendored."""
    return not (files or fileset_for(None)).hidden_from_map(d)


def repo_map(conn, cfg, repo: str) -> list[dict]:
    """Per-dir knowledge, card counts and verdict counts for the repo map (up to 2 levels)."""
    files = cfg.fileset(repo)
    nmap = novelty_map(conn, repo, cfg.settings.user.git_identities)
    churn = ((signals.load_signals(conn, repo) or {}).get("churn") or {}).get("dirs") or {}
    window = churn.get("365") or churn.get(max(churn, key=int, default=""), [])
    dirs = {d for d in set(nmap) | _prefixes(r["path"] for r in window[:30]) if _visible(d, files)}
    know = {
        r["dir"]: dict(r) for r in conn.execute("SELECT * FROM knowledge WHERE repo = ?", (repo,))
    }
    cards = conn.execute(
        "SELECT c.id, v.value AS verdict, "
        "EXISTS(SELECT 1 FROM events e WHERE e.card_id = c.id AND e.type = 'impression') AS seen "
        "FROM cards c JOIN repos r ON r.id = c.repo_id LEFT JOIN card_features v "
        "ON v.card_id = c.id AND v.feature = 'verdict' WHERE r.name = ? AND c.status = 'ready'",
        (repo,),
    ).fetchall()
    card_dirs: dict[str, set[str]] = {}
    for r in conn.execute(
        "SELECT card_id, value FROM card_features WHERE feature = 'dir' AND card_id IN "
        "(SELECT c.id FROM cards c JOIN repos r ON r.id = c.repo_id WHERE r.name = ?)",
        (repo,),
    ):
        card_dirs.setdefault(r["card_id"], set()).update(_prefixes([r["value"]]))
    out = {
        d: {
            "dir": d,
            "cards_seen": (know.get(d) or {}).get("cards_seen") or 0,
            "cards_available": 0,
            "quiz_right": (know.get(d) or {}).get("quiz_right") or 0,
            "quiz_wrong": (know.get(d) or {}).get("quiz_wrong") or 0,
            "novelty": nmap.get(d, 1.0),
            "verdicts": {},
        }
        for d in sorted(dirs)
    }
    for c in cards:
        for d in card_dirs.get(c["id"], ()):
            if d not in out:
                continue
            if not c["seen"]:
                out[d]["cards_available"] += 1
            if c["verdict"]:
                v = out[d]["verdicts"]
                v[c["verdict"]] = v.get(c["verdict"], 0) + 1
    return list(out.values())

"""Characters that carry between cards: persona and @file pages, follows, cast notes.

- `persona_page` and `file_page` feed /api/personas/{handle} and /api/files/{repo}/{path}.
- Follows are a JSON list in the `prefs` table under `followed_paths` (kept out of
  steering.PREF_DEFAULTS so /api/prefs keeps its shape). The slotter multiplies the score of a
  card by FOLLOW_BOOST when one of its dirs holds a followed path (docs/social.md).
- `cast_notes` is the "recent posts" text that get_packet gives writers for running jokes.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from posixpath import dirname

from codescroll import db, gitq

FOLLOW_KEY = "followed_paths"
FOLLOW_BOOST = 1.5
CAST_MAX_BYTES = 800
CAST_LINES = 3
CAST_TRIM = 60
PAGE_CARDS = 20
SCAN_CARDS = 200


# --- follows ---------------------------------------------------------------------------------


def follows(conn) -> list[tuple[str, str]]:
    row = conn.execute("SELECT value FROM prefs WHERE key = ?", (FOLLOW_KEY,)).fetchone()
    return [(r, p) for r, p in json.loads(row["value"])] if row else []


def set_follow(conn, repo: str, path: str, on: bool) -> bool:
    path = path.strip("/")
    items = [f for f in follows(conn) if f != (repo, path)]
    if on:
        items.append((repo, path))
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    with conn:
        conn.execute(
            "INSERT INTO prefs(key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "updated_at = excluded.updated_at",
            (FOLLOW_KEY, json.dumps(items), now),
        )
    return on


def followed_dirs(conn) -> list[tuple[str, str]]:
    """(repo, dir) of each followed path; a followed dir is its own dir. Root files give none."""
    out = []
    for repo, path in follows(conn):
        d = dirname(path) if "." in path.rsplit("/", 1)[-1] else path
        if d:
            out.append((repo, d))
    return out


# --- helpers ---------------------------------------------------------------------------------


def _recent_rows(conn, where: str = "", args: tuple = (), limit: int = SCAN_CARDS):
    return conn.execute(
        "SELECT c.*, r.name AS repo_name FROM cards c JOIN repos r ON r.id = c.repo_id "
        f"WHERE c.status = 'ready' {where} ORDER BY c.created_at DESC, c.id DESC LIMIT ?",
        (*args, limit),
    ).fetchall()


def _trim(text: str, n: int = CAST_TRIM) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


# --- persona ---------------------------------------------------------------------------------


def persona_page(conn, cfg, handle: str) -> dict | None:
    from codescroll.feed import public_card

    p = cfg.personas.get(handle)
    if p is None:
        return None
    posts = _recent_rows(conn, "AND c.persona = ?", (handle,), PAGE_CARDS)
    comments = []
    for row in _recent_rows(conn):
        spec = db.loads(row["spec"])
        for c in spec.get("comments") or []:
            if c["persona"] == handle and len(comments) < PAGE_CARDS:
                comments.append(
                    {
                        "card_id": row["id"],
                        "repo": row["repo_name"],
                        "hook": spec["hook"],
                        "text": c["text"],
                    }
                )
    return {
        "handle": handle,
        "name": p.name,
        "voice": p.voice,
        "bio": p.bio,
        "posts": [public_card(r, cfg) for r in posts],
        "comments": comments,
    }


# --- files -----------------------------------------------------------------------------------


def _cited_paths(spec: dict) -> list[tuple[str, str]]:
    """(repo, path) pairs a card cites: sources, the visual, depth panels, the @file account."""
    out = []
    for s in spec.get("sources") or []:
        if s.get("path"):
            out.append((s["repo"], s["path"]))
    for item in [spec.get("visual") or {}, *(spec.get("depth") or [])]:
        if item.get("path"):
            out.append((item.get("repo") or spec["repos"][0], item["path"]))
    acct = spec.get("account")
    if acct and ":" in acct:
        r, _, p = acct.partition(":")
        out.append((r, p.rstrip("/")))
    return out


def cites(spec: dict, repo: str, path: str) -> bool:
    return any(r == repo and (p == path or p.startswith(path + "/")) for r, p in _cited_paths(spec))


def history(cfg, conn, repo: str, path: str) -> dict | None:
    r = cfg.repos[repo]
    head = conn.execute("SELECT last_analyzed_sha FROM repos WHERE name = ?", (repo,)).fetchone()
    ref = (head["last_analyzed_sha"] if head else None) or r.ref
    try:
        out = gitq.run(
            r.path, "log", ref, "--no-merges", "-n", "5000", "--format=%at\t%aN", "--", path
        )
    except Exception:  # repo moved or path unknown: the page still lists its cards
        return None
    rows = [ln.split("\t", 1) for ln in out.splitlines() if "\t" in ln]
    if not rows:
        return {"commits": 0, "last_touched": None, "authors": []}
    last = max(int(t) for t, _ in rows)
    top = Counter(a for _, a in rows).most_common(3)
    return {
        "commits": len(rows),
        "last_touched": datetime.fromtimestamp(last, UTC).strftime("%Y-%m-%d"),
        "authors": [{"name": a, "commits": n} for a, n in top],
    }


def file_page(conn, cfg, repo: str, path: str) -> dict | None:
    from codescroll.feed import public_card

    if repo not in cfg.repos:
        return None
    path = path.strip("/")
    # instr() prefilters on the raw path text; cites() decides.
    rows = _recent_rows(conn, "AND instr(c.spec, ?) > 0", (path,))
    hits = [r for r in rows if cites(db.loads(r["spec"]), repo, path)][:PAGE_CARDS]
    return {
        "repo": repo,
        "path": path,
        "history": history(cfg, conn, repo, path),
        "cards": [public_card(r, cfg) for r in hits],
        "followed": (repo, path) in follows(conn),
    }


# --- cast notes ------------------------------------------------------------------------------


def cast_notes(conn, cfg, personas: list[str], cap: int = CAST_MAX_BYTES) -> str:
    """Each persona's last few hooks and comments, trimmed, for callbacks to running jokes."""
    wanted = list(dict.fromkeys(p for p in personas if p in cfg.personas))
    if not wanted:
        return ""
    lines: dict[str, list[str]] = {p: [] for p in wanted}
    for row in _recent_rows(conn):
        spec = db.loads(row["spec"])
        if row["persona"] in lines:
            lines[row["persona"]].append(f"post: {_trim(spec['hook'])}")
        for c in spec.get("comments") or []:
            if c["persona"] in lines:
                lines[c["persona"]].append(f"comment: {_trim(c['text'])}")
    lines = {p: v[:CAST_LINES] for p, v in lines.items() if v}
    head = "## Cast notes\nRecent lines by the personas in this packet. Call back, do not repeat.\n"

    def render() -> str:
        body = [f"- @{p}: " + " | ".join(v) for p, v in lines.items()]
        return head + "\n".join(body) + "\n" if body else ""

    while lines and len(render().encode()) > cap:
        longest = max(lines, key=lambda p: (len(lines[p]), len(" ".join(lines[p]))))
        lines[longest].pop()
        if not lines[longest]:
            del lines[longest]
    return render()

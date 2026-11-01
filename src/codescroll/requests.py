"""Follow-up requests: the reader tapped "Teach me more" on a card.

`sync_in_tx` (run by the learning worker) turns each `teach_more` event into one `requests`
row per card, plus a ledger lead keyed "req:<id>" with strength above every normal lead
(normal leads are <= 1). `mark_served` closes the request when a card covers that lead.
"""

from __future__ import annotations

from codescroll import db

REQUEST_STRENGTH = 2.0
KEY_PREFIX = "req:"


def _place(spec: dict) -> tuple[str, str]:
    """(path, commit) the card is about: its sources first, then visual and depth panels."""
    parts = [*spec.get("sources", []), spec.get("visual", {}), *spec.get("depth", [])]
    path = next((p["path"] for p in parts if p.get("path")), "")
    commit = next((p["commit"] for p in parts if p.get("commit")), "")
    return path, commit


def _text(path: str, commit: str, hook: str) -> str:
    what = path or f"commit {commit[:10]}"
    return (
        f"follow-up: the reader asked to learn more about {what} after the card '{hook}'. "
        "Go one level deeper: what calls it, why it exists, what breaks without it."
    )


def sync_in_tx(conn, now: str | None = None) -> int:
    """Create a request and lead for each card with a teach_more event and no request yet.

    Idempotent (one request per card). The caller owns the transaction. Returns new requests.
    """
    now = now or db.now_iso()
    rows = conn.execute(
        "SELECT DISTINCT c.id, c.story_type, c.spec FROM events e JOIN cards c ON c.id = e.card_id "
        "WHERE e.type = 'teach_more' "
        "AND NOT EXISTS (SELECT 1 FROM requests r WHERE r.card_id = c.id) ORDER BY c.id"
    ).fetchall()
    for row in rows:
        spec = db.loads(row["spec"])
        repo = spec["repos"][0]
        path, commit = _place(spec)
        if not path and not commit:
            continue
        stype, kind = ("what_it_does", "path") if path else ("before_after", "commit")
        cur = conn.execute(
            "INSERT INTO requests(card_id, repo, story_type, path, commit_sha, dirs, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (row["id"], repo, stype, path, commit, db.dumps(spec.get("dirs") or []), now),
        )
        conn.execute(
            "INSERT INTO leads(repo, story_type, kind, path, commit_sha, lead_key, text, strength, "
            "head_sha, first_seen_at, last_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?) "
            "ON CONFLICT(repo, story_type, lead_key) DO NOTHING",
            (
                repo,
                stype,
                kind,
                path,
                commit if not path else "",
                f"{KEY_PREFIX}{cur.lastrowid}",
                _text(path, commit, spec.get("hook", "")),
                REQUEST_STRENGTH,
                now,
                now,
            ),
        )
    return len(rows)


def mark_served(conn, lead_id: int, now: str) -> None:
    """If the lead is a request lead, set served_at on its request (caller owns the transaction)."""
    row = conn.execute("SELECT lead_key FROM leads WHERE id = ?", (lead_id,)).fetchone()
    if row and row["lead_key"].startswith(KEY_PREFIX):
        conn.execute(
            "UPDATE requests SET served_at = ? WHERE id = ? AND served_at IS NULL",
            (now, int(row["lead_key"][len(KEY_PREFIX) :])),
        )

"""Persist accepted cards and their features."""

from __future__ import annotations

import secrets
import time
from datetime import UTC, datetime, timedelta

from codescroll import db
from codescroll.config import Repo


def new_card_id(now_ms: int | None = None) -> str:
    ms = int(time.time() * 1000) if now_ms is None else now_ms
    return f"c_{ms:012x}{secrets.token_hex(4)}"


def ensure_repo(conn, repo: Repo) -> int:
    conn.execute(
        "INSERT INTO repos(name, path, ref, mascot) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(name) DO UPDATE SET path=excluded.path, ref=excluded.ref, "
        "mascot=excluded.mascot",
        (repo.name, str(repo.path), repo.ref, repo.mascot),
    )
    return conn.execute("SELECT id FROM repos WHERE name = ?", (repo.name,)).fetchone()[0]


def _features(card: dict) -> set[tuple[str, str]]:
    feats = {(k, card[k]) for k in ("story_type", "format", "persona", "tone")}
    feats |= {("repo", r) for r in card["repos"]}
    feats |= {("dir", d.rstrip("/")) for d in card.get("dirs", [])}
    if card.get("difficulty") is not None:
        feats.add(("difficulty", str(card["difficulty"])))
    feats.add(("has_comments", "1" if card.get("comments") else "0"))
    feats.add(("visual_kind", card["visual"]["kind"]))
    if card["visual"]["kind"] == "template":
        feats.add(("template", card["visual"]["template"]))
    return feats


RENDERED_KINDS = frozenset({"meme", "illustration", "comic"})


def store_card(conn, cfg, run_id: str, acc, now: str | None = None) -> str:
    with conn:
        return insert_card(conn, cfg, run_id, acc, now)


def insert_card(conn, cfg, run_id: str, acc, now: str | None = None) -> str:
    """Insert a card and its features without committing (caller owns the transaction)."""
    card = acc.card
    card_id = new_card_id()
    status = "pending_render" if card["visual"]["kind"] in RENDERED_KINDS else "ready"
    repo_id = ensure_repo(conn, cfg.repos[card["repos"][0]])
    conn.execute(
        "INSERT INTO cards(id, run_id, repo_id, story_type, format, persona, tone, "
        "spec, resolved, status, story_key, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            card_id,
            run_id,
            repo_id,
            card["story_type"],
            card["format"],
            card["persona"],
            card["tone"],
            db.dumps(card),
            db.dumps(acc.resolved),
            status,
            acc.story_key,
            now or db.now_iso(),
        ),
    )
    conn.executemany(
        "INSERT INTO card_features(card_id, feature, value) VALUES (?, ?, ?)",
        [(card_id, f, v) for f, v in sorted(_features(card))],
    )
    return card_id


def story_key_exists(conn, key: str, since_days: int = 30, now: datetime | None = None) -> bool:
    cutoff = (now or datetime.now(UTC)) - timedelta(days=since_days)
    row = conn.execute(
        "SELECT 1 FROM cards WHERE story_key = ? AND created_at >= ? LIMIT 1",
        (key, cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")),
    ).fetchone()
    return row is not None

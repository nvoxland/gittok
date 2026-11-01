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


def _card_dirs(card: dict) -> set[str]:
    """The card's `dirs` plus the parent dir of every path it cites, each with all its prefixes."""
    paths = [s["path"] for s in card.get("sources", []) if s.get("path")]
    if card["visual"].get("path"):
        paths.append(card["visual"]["path"])
    paths += [
        p["path"]
        for p in card.get("depth", [])
        if p.get("kind") in ("code", "code_diff") and p.get("path")
    ]
    dirs = [d.strip("/") for d in card.get("dirs", [])]
    dirs += [p.strip("/").rpartition("/")[0] for p in paths]
    out = set()
    for d in dirs:
        parts = [x for x in d.split("/") if x]
        out |= {"/".join(parts[:i]) for i in range(1, len(parts) + 1)}
    return out


def _features(card: dict) -> set[tuple[str, str]]:
    feats = {(k, card[k]) for k in ("story_type", "format", "persona", "tone")}
    feats |= {("repo", r) for r in card["repos"]}
    feats |= {("dir", d) for d in _card_dirs(card)}
    if card.get("difficulty") is not None:
        feats.add(("difficulty", str(card["difficulty"])))
    if "interaction" in card:
        feats.add(("interactive", card["story_type"]))
    feats.add(("has_comments", "1" if card.get("comments") else "0"))
    feats.add(("visual_kind", card["visual"]["kind"]))
    if card["visual"]["kind"] == "template":
        feats.add(("template", card["visual"]["template"]))
    if card["visual"]["kind"] == "meme":
        feats.add(("meme_template", card["visual"]["template"]))
    return feats


def set_features(conn, card_id: str, card: dict) -> None:
    """Replace a card's stored features (caller owns the transaction)."""
    conn.execute("DELETE FROM card_features WHERE card_id = ?", (card_id,))
    conn.executemany(
        "INSERT INTO card_features(card_id, feature, value) VALUES (?, ?, ?)",
        [(card_id, f, v) for f, v in sorted(_features(card))],
    )


def refeature(conn) -> int:
    """Recompute card_features for every card from its stored spec. Returns the card count."""
    rows = conn.execute("SELECT id, spec FROM cards").fetchall()
    with conn:
        for r in rows:
            set_features(conn, r["id"], db.loads(r["spec"]))
    return len(rows)


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
    created = now or db.now_iso()
    conn.execute(
        "INSERT INTO stories(story_key, repo, story_type, sources, first_card_at, last_card_at, "
        "formats) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(story_key) DO UPDATE SET "
        "cards_made = cards_made + 1, last_card_at = excluded.last_card_at",
        (
            acc.story_key,
            card["repos"][0],
            card["story_type"],
            db.dumps(card.get("sources", [])),
            created,
            created,
            db.dumps([card["format"]]),
        ),
    )
    row = conn.execute(
        "SELECT formats FROM stories WHERE story_key = ?", (acc.story_key,)
    ).fetchone()
    used = db.loads(row["formats"])
    if card["format"] not in used:
        conn.execute(
            "UPDATE stories SET formats = ? WHERE story_key = ?",
            (db.dumps([*used, card["format"]]), acc.story_key),
        )
    return card_id


def variant_blocker(story, fmt: str, agent, now: datetime) -> str | None:
    """Why a card of format `fmt` may not join an existing story; None if it may.

    `story` is the `stories` row, or None for a new story (always allowed). A story is told
    again only in a new format, if it did well or was liked, and long enough after its last card.
    """
    if story is None:
        return None
    if fmt in db.loads(story["formats"]):
        return f"story was already told in format {fmt}"
    if not story["liked"] and (story["best_reward"] or 0) < agent.variant_min_reward:
        return f"story reward is below {agent.variant_min_reward} and it is not liked"
    cutoff = (now - timedelta(days=agent.variant_after_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    if story["last_card_at"] > cutoff:
        return f"last card of this story is under {agent.variant_after_days} days old"
    return None


def story_blocker(conn, key: str, fmt: str, agent, now: datetime | None = None) -> str | None:
    """`variant_blocker` for a story looked up by key."""
    story = conn.execute("SELECT * FROM stories WHERE story_key = ?", (key,)).fetchone()
    return variant_blocker(story, fmt, agent, now or datetime.now(UTC))

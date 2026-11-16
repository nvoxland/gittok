"""Persist accepted cards and their features."""

from __future__ import annotations

import random
import secrets
import time
from datetime import UTC, datetime, timedelta

from gittok import config, db
from gittok.config import Repo


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


def _cited_paths(card: dict) -> list[str]:
    """Every path the card cites: visual first, then sources, then code depth panels."""
    paths = [card["visual"]["path"]] if card["visual"].get("path") else []
    paths += [s["path"] for s in card.get("sources", []) if s.get("path")]
    paths += [
        p["path"]
        for p in card.get("depth", [])
        if p.get("kind") in ("code", "code_diff") and p.get("path")
    ]
    return list(dict.fromkeys(p.strip("/") for p in paths))


def main_path(card: dict) -> str | None:
    """The file a card is mostly about: the visual's path, else the first cited path."""
    paths = _cited_paths(card)
    return paths[0] if paths else None


def path_features(path: str | None, fileset=None) -> set[tuple[str, str]]:
    """The features a file gives a card or a lead: `file`, `language`, and (with the repo's
    file set) `kind`: test, fixture, generated, docs, vendored or source."""
    if not path:
        return set()
    feats = {("file", path)}
    if lang := config.language_of(path):
        feats.add(("language", lang))
    if fileset is not None:
        feats.add(("kind", fileset.kind(path) or "source"))
    return feats


def _features(card: dict, fileset=None) -> set[tuple[str, str]]:
    """The features of a card for the learner (docs/learning.md section 4). `fileset` is the
    file set of the card's first repo; without it there is no `kind`."""
    feats = {(k, card[k]) for k in ("story_type", "format", "persona", "tone")}
    feats |= {("repo", r) for r in card["repos"]}
    feats |= {("dir", d) for d in _card_dirs(card)}
    if card.get("angle"):
        feats.add(("angle", card["angle"]))
    feats |= path_features(main_path(card), fileset)
    feats |= {("language", lang) for p in _cited_paths(card) if (lang := config.language_of(p))}
    if "interaction" in card:
        feats.add(("interactive", card["story_type"]))
    if card.get("verdict"):
        feats.add(("verdict", card["verdict"]))
    feats.add(("has_comments", "1" if card.get("comments") else "0"))
    feats.add(("visual_kind", card["visual"]["kind"]))
    if card["visual"]["kind"] == "template":
        feats.add(("template", card["visual"]["template"]))
    if card["visual"]["kind"] == "meme":
        feats.add(("meme_template", card["visual"]["template"]))
    return feats


def _fileset(cfg, card: dict):
    repo = (card.get("repos") or [None])[0]
    return cfg.fileset(repo) if cfg is not None and repo in cfg.repos else None


def set_features(conn, card_id: str, card: dict, cfg=None) -> None:
    """Replace a card's stored features (caller owns the transaction), its lead's included."""
    conn.execute("DELETE FROM card_features WHERE card_id = ?", (card_id,))
    conn.executemany(
        "INSERT INTO card_features(card_id, feature, value) VALUES (?, ?, ?)",
        [(card_id, f, v) for f, v in sorted(_features(card, _fileset(cfg, card)))],
    )
    row = conn.execute("SELECT lead_id FROM cards WHERE id = ?", (card_id,)).fetchone()
    if row and row["lead_id"] is not None:
        add_lead_features(conn, card_id, row["lead_id"])


def lead_tag(lead_key: str | None) -> str | None:
    """The detector tag of a candidate lead ("cand:<path>:<line>:<tag>"), else None."""
    if not lead_key or not lead_key.startswith("cand:"):
        return None
    return lead_key.rsplit(":", 1)[1] or None


def add_lead_features(conn, card_id: str, lead_id: int) -> None:
    """Add what the card's lead knows: the `tag` of the detector that found it."""
    row = conn.execute("SELECT lead_key FROM leads WHERE id = ?", (lead_id,)).fetchone()
    if row and (tag := lead_tag(row["lead_key"])):
        conn.execute(
            "INSERT OR IGNORE INTO card_features(card_id, feature, value) VALUES (?, 'tag', ?)",
            (card_id, tag),
        )


def refeature(conn, cfg=None) -> int:
    """Recompute card_features for every card from its stored spec and its lead. Returns the
    card count. Run `gittok relearn` after it so the model learns from the new features."""
    rows = conn.execute("SELECT id, spec FROM cards").fetchall()
    with conn:
        for r in rows:
            set_features(conn, r["id"], db.loads(r["spec"]), cfg)
    return len(rows)


RENDERED_KINDS = frozenset({"meme", "illustration", "comic"})


# Tests that pin choice positions turn this off (tests/conftest.py); the app always shuffles.
SHUFFLE = True


def shuffle_choices(card: dict, resolved: dict, seed: str) -> tuple[dict, dict]:
    """Copies of a validated card with its quiz choices in a seeded random order, the answer
    index (in the spec and in `resolved`) following the right choice. Writers tend to put the
    answer first or second; the reader should not learn that instead of the code."""
    inter = card.get("interaction")
    if not inter or inter.get("answer_index") is None:
        return card, resolved
    order = list(range(len(inter["choices"])))
    random.Random(seed).shuffle(order)
    answer = order.index(inter["answer_index"])
    card = {
        **card,
        "interaction": {
            **inter,
            "choices": [inter["choices"][i] for i in order],
            "answer_index": answer,
        },
    }
    resolved = {
        **resolved,
        "interaction": {**resolved.get("interaction", {}), "answer_index": answer},
    }
    return card, resolved


def insert_card(conn, cfg, run_id: str, acc, now: str | None = None,
                image_backend: str | None = None) -> str:
    """Insert a card and its features without committing (caller owns the transaction).

    Pass `image_backend` (render.image_backend) when holding a write lock: deciding it may
    start a subprocess."""
    card_id = new_card_id()
    card, resolved = (
        shuffle_choices(acc.card, acc.resolved, card_id) if SHUFFLE else (acc.card, acc.resolved)
    )
    status = "pending_render" if card["visual"]["kind"] in RENDERED_KINDS else "ready"
    if card["visual"]["kind"] in {"illustration", "comic"}:
        if image_backend is None:
            from .render import image_backend as decide

            image_backend = decide(cfg)
        resolved = {**resolved, "image_backend": image_backend}
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
            db.dumps(resolved),
            status,
            acc.story_key,
            now or db.now_iso(),
        ),
    )
    conn.executemany(
        "INSERT INTO card_features(card_id, feature, value) VALUES (?, ?, ?)",
        [(card_id, f, v) for f, v in sorted(_features(card, _fileset(cfg, card)))],
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
    A story with a 👎 is never told again.
    """
    if story is None:
        return None
    if story["disliked"]:
        return "the reader marked this story 👎 (show less like this)"
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

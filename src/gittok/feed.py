"""Feed paging (slotted) and the card JSON shape served to the client."""

from __future__ import annotations

import base64
import copy
import json
from datetime import datetime

from gittok import db, links, replies, secrets, slotter


def card_json(row) -> dict:
    spec = db.loads(row["spec"])
    return {
        **spec,
        "comments": spec.get("comments") or [],  # optional in the schema, a list for the client
        "id": row["id"],
        "created_at": row["created_at"],
        "repo": spec["repos"][0],
        "resolved": db.loads(row["resolved"]),
    }


def strip_answers(card: dict) -> dict:
    """A copy of `card` without the interaction answer and explanation (docs/learning.md 2)."""
    card = copy.deepcopy(card)
    if isinstance(card.get("interaction"), dict):
        card["interaction"].pop("answer_index", None)
        card["interaction"].pop("explanation", None)
    resolved = card.get("resolved")
    if isinstance(resolved, dict) and isinstance(resolved.get("interaction"), dict):
        resolved["interaction"].pop("answer_index", None)
    return card


def public_card(row, cfg=None) -> dict:
    """The card for the client. With `cfg`, `links` holds GitHub URLs (None when there are none)."""
    card = strip_answers(card_json(row))
    if cfg is None or cfg.settings.research.redact_secrets:
        # cards stored before redaction existed may still hold a secret in their code
        card["resolved"] = secrets.redact_value(card["resolved"])
    if cfg is not None:
        card["links"] = links.card_links(cfg, card)
    return card


class InvalidCursor(ValueError):
    pass


# Card ids are "c_" + 12 hex ms + 8 hex random. The last 12 chars (4 ms + 8 random hex) are
# enough to tell cards apart, and keep the cursor small. Only the most recent MAX_SERVED are
# kept; the slotter's repeat_days exclusion covers older ones.
TOKEN_LEN = 12
MAX_SERVED = 500


def token(card_id: str) -> str:
    return card_id[-TOKEN_LEN:]


def encode_cursor(served: list[str], seed: int) -> str:
    raw = json.dumps({"served": served, "seed": seed}).encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_cursor(cursor: str) -> tuple[list[str], int]:
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode()))
    except (ValueError, TypeError) as e:  # bad base64, bad JSON, bad UTF-8
        raise InvalidCursor("invalid cursor") from e
    if not isinstance(data, dict):
        raise InvalidCursor("invalid cursor")
    served, seed = data.get("served"), data.get("seed")
    if (
        not isinstance(served, list)
        or not all(isinstance(s, str) for s in served)
        or not isinstance(seed, int)
        or isinstance(seed, bool)
    ):
        raise InvalidCursor("invalid cursor")
    return served, seed


def last_seen_card(conn, cfg=None) -> str | None:
    """The card of the newest impression that is still a ready card (None when there is none).
    With `cfg`, None also when that card's repo is not configured."""
    row = conn.execute(
        "SELECT c.id, r.name FROM events e JOIN cards c ON c.id = e.card_id "
        "JOIN repos r ON r.id = c.repo_id "
        "WHERE e.type = 'impression' AND c.status = 'ready' ORDER BY e.ts DESC LIMIT 1"
    ).fetchone()
    if row is None or (cfg is not None and row["name"] not in cfg.repos):
        return None
    return row[0]


def filter_excluded(conn, repo: str | None, dir: str | None) -> set[str]:
    """Ids of cards that do not match the repo/dir filter (hidden from the slotter)."""
    dir = (dir or "").strip("/")
    keep = {r[0] for r in conn.execute("SELECT id FROM cards")}
    if repo:
        keep &= {
            r[0]
            for r in conn.execute(
                "SELECT card_id FROM card_features WHERE feature = 'repo' AND value = ?", (repo,)
            )
        }
    if dir:
        keep &= {
            r[0]
            for r in conn.execute("SELECT card_id, value FROM card_features WHERE feature = 'dir'")
            if r[1] == dir or r[1].startswith(dir + "/")
        }
    return {r[0] for r in conn.execute("SELECT id FROM cards")} - keep


def sent_cursor(cursor: str | None, ids: list[str], seed: int) -> str:
    """A cursor of every card sent so far: the ones `cursor` names and `ids`.
    Unlike `next_cursor` it is there when the feed is exhausted too: asked with it later, the
    feed returns only cards made since (a generation run that is still going)."""
    served: list[str] = []
    if cursor:
        served, seed = decode_cursor(cursor)
    return encode_cursor((served + [token(i) for i in ids])[-MAX_SERVED:], seed)


def page(
    conn,
    cfg,
    limit: int,
    cursor: str | None,
    seed: int,
    now: datetime,
    repo: str | None = None,
    dir: str | None = None,
) -> tuple[list[dict], str | None, str | None]:
    """The next batch of public cards, the cursor for the one after (None when exhausted), and
    the resume card id.

    `seed` is used only when there is no cursor; a cursor carries its own seed. Without a
    cursor (a fresh load), the card last seen goes first so a reload resumes on it; that card
    id is the third value, and it is None otherwise.

    A card once sent stays sent: a 👍 or 👎 teaches the learner what to make next, and does
    not reorder the cards the client already holds.
    """
    served: list[str] = []
    resume = None
    if cursor:
        served, seed = decode_cursor(cursor)
    elif not (repo or dir):
        resume = last_seen_card(conn, cfg)
    hidden = filter_excluded(conn, repo, dir) if (repo or dir) else set()
    seen = {token(t) for t in served}
    served_ids = (
        {r[0] for r in conn.execute("SELECT id FROM cards") if token(r[0]) in seen}
        if seen
        else set()
    )
    lead = [resume] if resume else []
    ids = lead + (
        slotter.build_batch(
            conn, cfg, limit - len(lead), served_ids | set(lead) | hidden, seed, now
        )
        if limit > len(lead)
        else []
    )
    rows = {
        r["id"]: r
        for r in conn.execute(f"SELECT * FROM cards WHERE id IN ({','.join('?' * len(ids))})", ids)
    }
    cards = replies.attach(conn, [public_card(rows[i], cfg) for i in ids])
    next_cursor = (
        encode_cursor(([token(t) for t in served] + [token(i) for i in ids])[-MAX_SERVED:], seed)
        if len(ids) >= limit
        else None
    )
    return cards, next_cursor, resume

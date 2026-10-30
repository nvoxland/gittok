"""Feed ranking and the card JSON shape served to the client."""

from __future__ import annotations

import base64
import json
from typing import Protocol

from codescroll import db


class Ranker(Protocol):
    def page(self, conn, limit: int, cursor: str | None) -> tuple[list[dict], str | None]: ...


def card_json(row) -> dict:
    spec = db.loads(row["spec"])
    return {
        **spec,
        "id": row["id"],
        "created_at": row["created_at"],
        "repo": spec["repos"][0],
        "resolved": db.loads(row["resolved"]),
    }


def _encode(created_at: str, card_id: str) -> str:
    raw = json.dumps([created_at, card_id]).encode()
    return base64.urlsafe_b64encode(raw).decode()


class InvalidCursor(ValueError):
    pass


def _decode(cursor: str) -> tuple[str, str]:
    try:
        created_at, card_id = json.loads(base64.urlsafe_b64decode(cursor.encode()))
    except (ValueError, TypeError) as e:  # bad base64, bad JSON, bad shape, bad UTF-8
        raise InvalidCursor("invalid cursor") from e
    if not isinstance(created_at, str) or not isinstance(card_id, str):
        raise InvalidCursor("invalid cursor")
    return created_at, card_id


class ChronologicalRanker:
    """Newest first. The cursor encodes the last card's (created_at, id)."""

    def page(self, conn, limit: int, cursor: str | None) -> tuple[list[dict], str | None]:
        sql = "SELECT * FROM cards WHERE status = 'ready'"
        params: list = []
        if cursor:
            created_at, card_id = _decode(cursor)
            sql += " AND (created_at < ? OR (created_at = ? AND id < ?))"
            params += [created_at, created_at, card_id]
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        rows = conn.execute(sql, [*params, limit + 1]).fetchall()
        more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = _encode(rows[-1]["created_at"], rows[-1]["id"]) if more else None
        return [card_json(r) for r in rows], next_cursor

"""Answer checking and spaced repetition (docs/learning.md section 6)."""

from __future__ import annotations

from datetime import datetime, timedelta

from codescroll import db

FMT = "%Y-%m-%dT%H:%M:%SZ"
LADDER = {1: 3, 3: 7}


class UnknownCard(LookupError):
    pass


class NotInteractive(ValueError):
    pass


class BadChoice(ValueError):
    pass


def _iso(dt: datetime) -> str:
    return dt.strftime(FMT)


def _upsert(conn, card_id: str, interval: int, due: datetime, streak: int, mastered: int) -> None:
    conn.execute(
        "INSERT INTO srs(card_id, interval_days, due_at, streak, mastered) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(card_id) DO UPDATE SET interval_days = excluded.interval_days, "
        "due_at = excluded.due_at, streak = excluded.streak, mastered = excluded.mastered",
        (card_id, interval, _iso(due), streak, mastered),
    )


def record_answer(conn, card_id: str, choice: int, now: datetime) -> dict:
    """Check `choice` against the stored answer and update the card's SRS row."""
    row = conn.execute("SELECT spec, resolved FROM cards WHERE id = ?", (card_id,)).fetchone()
    if row is None:
        raise UnknownCard(card_id)
    spec, resolved = db.loads(row["spec"]), db.loads(row["resolved"]) or {}
    if "interaction" not in spec or "interaction" not in resolved:
        raise NotInteractive(card_id)
    if not 0 <= choice < len(spec["interaction"]["choices"]):
        raise BadChoice(f"choice {choice} is out of range")
    answer = resolved["interaction"].get("answer_index")
    correct = None if answer is None else choice == answer
    if correct is False:
        _upsert(conn, card_id, 1, now + timedelta(days=1), 0, 0)
    elif correct:
        state = conn.execute("SELECT * FROM srs WHERE card_id = ?", (card_id,)).fetchone()
        if state and not state["mastered"] and state["due_at"] <= _iso(now):
            interval = state["interval_days"]
            if interval in LADDER:
                nxt, mastered = LADDER[interval], 0
            else:
                nxt, mastered = interval, 1
            _upsert(conn, card_id, nxt, now + timedelta(days=nxt), state["streak"] + 1, mastered)
    return {
        "correct": correct,
        "answer_index": answer,
        "explanation": spec["interaction"].get("explanation"),
    }


def due_cards(conn, now: datetime) -> list[str]:
    """Ids of ready cards that are due for review, most overdue first."""
    rows = conn.execute(
        "SELECT s.card_id FROM srs s JOIN cards c ON c.id = s.card_id "
        "WHERE s.mastered = 0 AND s.due_at <= ? AND c.status = 'ready' "
        "ORDER BY s.due_at, s.card_id",
        (_iso(now),),
    )
    return [r["card_id"] for r in rows]

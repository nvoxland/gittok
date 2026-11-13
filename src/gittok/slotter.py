"""Serving the feed (docs/learning.md section 5): every card the reader has not seen, oldest
first. What the learner learned shapes which cards get made (the brief); it never orders the
cards that exist, and no steering rule applies here. Only quiz reviews (SRS), story spacing
and series order do."""

from __future__ import annotations

from datetime import datetime, timedelta

from gittok import db, srs, supply

SRS_MIN_POSITION = 3
SERIES_GAP = 3  # parts of one series sit at least this many positions apart


def _knobs(rc) -> dict:
    """The serving knobs (config/reward.yaml `slotting`; the shipped file holds the defaults)."""
    return rc.slotting


def _series_of(conn, ids: list[str]) -> dict[str, tuple]:
    """Card id -> (repo_id, key, part) for the cards that belong to a series."""
    out = {}
    for r in conn.execute(
        "SELECT id, repo_id, spec FROM cards "
        f"WHERE id IN ({','.join('?' * len(ids))}) "
        "AND json_extract(spec, '$.series.key') IS NOT NULL",
        ids,
    ):
        s = db.loads(r["spec"])["series"]
        out[r["id"]] = (r["repo_id"], s["key"], s["part"])
    return out


def _unseen_earlier(conn, served: set[str], series: dict[str, tuple]) -> dict[str, set[str]]:
    """Card id -> ids of earlier parts that are ready, never seen, and not served before."""
    out: dict[str, set[str]] = {}
    for cid, (repo_id, key, part) in series.items():
        out[cid] = {
            r["id"]
            for r in conn.execute(
                "SELECT c.id FROM cards c WHERE c.status = 'ready' AND c.repo_id = ? "
                "AND json_extract(c.spec, '$.series.key') = ? "
                "AND json_extract(c.spec, '$.series.part') < ? "
                "AND NOT EXISTS (SELECT 1 FROM events e WHERE e.card_id = c.id "
                "AND e.type = 'impression')",
                (repo_id, key, part),
            )
        } - served
    return out


def _hold_back_series(conn, ids: list[str], served: set[str], keep: set[str]) -> list[str]:
    """Drop series parts whose unseen earlier parts are not in `keep` (the cards that go out)."""
    series = _series_of(conn, ids) if ids else {}
    waiting = _unseen_earlier(conn, served, series)
    return [i for i in ids if not (waiting.get(i, set()) - keep)]


def _order_series(order: list[str], series: dict[str, tuple]) -> list[str]:
    """Greedy reorder: parts of one series in part order and SERIES_GAP positions apart.

    Takes the first card of `order` that fits; when none fits the gap, the first one whose
    earlier parts are all out (the batch is too small to keep the gap).
    """
    rest, out, last = list(order), [], {}

    def in_order(i: str) -> bool:
        s = series.get(i)
        return not s or not any(
            series[j][:2] == s[:2] and series[j][2] < s[2] for j in rest if j in series
        )

    while rest:
        ready = [i for i in rest if in_order(i)]
        fits = [
            i
            for i in ready
            if i not in series or len(out) - last.get(series[i][:2], -SERIES_GAP) >= SERIES_GAP
        ]
        pick = (fits or ready)[0]
        if pick in series:
            last[series[pick][:2]] = len(out)
        rest.remove(pick)
        out.append(pick)
    return out


def _srs_gap(limit: int) -> int:
    return max(3, limit // 2)


def _placeable(n_normal: int, n_due: int, limit: int) -> int:
    """How many of `n_due` due cards fit when `n_normal` normal cards are available.

    Due card n goes to position 3 + n * gap and needs that many cards in front of it.
    """
    gap = _srs_gap(limit)
    placed = 0
    for n in range(n_due):
        if SRS_MIN_POSITION + n * gap <= min(n_normal, limit - n_due) + placed:
            placed += 1
        else:
            break
    return placed


def _reserve_srs(n_normal: int, due: list[str], limit: int) -> list[str]:
    """Due cards that will really be placed; the other slots go to normal cards."""
    for k in range(len(due), 0, -1):
        if _placeable(n_normal, k, limit) == k:
            return due[:k]
    return []


def _insert_srs(ordered: list[str], due: list[str], limit: int) -> list[str]:
    """Place due cards at positions 3, 3 + gap, ...; a card that would land past the end waits."""
    gap = _srs_gap(limit)
    out = list(ordered)
    for n, card_id in enumerate(due):
        pos = SRS_MIN_POSITION + n * gap
        if pos <= len(out) and len(out) < limit:
            out.insert(pos, card_id)
    return out


def dir_matches(card_dir: str, rule_dir: str) -> bool:
    """Path-prefix match: `src` covers `src` and `src/api`, not `lib/src`."""
    d = rule_dir.strip("/")
    c = card_dir.strip("/")
    return c == d or c.startswith(d + "/")


def _story_keys(conn, ids: list[str]) -> dict[str, str]:
    """Card id -> story key, in one query."""
    return {
        r["id"]: r["story_key"]
        for r in conn.execute(
            f"SELECT id, story_key FROM cards WHERE id IN ({','.join('?' * len(ids))})", ids
        )
    }


def _impressed_stories(conn, since_ms: int) -> set[str]:
    """Story keys of cards that had an impression since `since_ms`."""
    return {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT c.story_key FROM events e JOIN cards c ON c.id = e.card_id "
            "WHERE e.type = 'impression' AND e.ts >= ?",
            (since_ms,),
        )
    }


def _created_order(conn, ids: list[str]) -> list[str]:
    """`ids` oldest first (by created_at, then id)."""
    if not ids:
        return []
    created = dict(
        conn.execute(
            f"SELECT id, created_at FROM cards WHERE id IN ({','.join('?' * len(ids))})", ids
        ).fetchall()
    )
    return sorted(ids, key=lambda i: (created.get(i, ""), i))


def build_batch(conn, cfg, limit: int, served: set[str], seed: int, now: datetime) -> list[str]:
    """The next `limit` cards: unseen ones oldest first, with due quiz reviews placed in.

    No score: the cards that exist go out in the order they were made. `seed` is unused and
    kept for the cursor format."""
    from gittok import learning

    rc = learning.load_reward_config(cfg)
    knobs = _knobs(rc)
    served = served | supply.unconfigured_cards(conn, cfg)  # a removed repo is never shown
    due = [d for d in srs.due_cards(conn, now) if d not in served]
    ids = [i for i in supply.unseen_ready(conn, rc, now) if i not in served and i not in due]
    # Variants of one story are never close together: skip stories shown within repeat_days.
    story_of = _story_keys(conn, ids)
    since_ms = int((now - timedelta(days=knobs["repeat_days"])).timestamp() * 1000)
    shown = _impressed_stories(conn, since_ms)
    ids = [i for i in ids if story_of[i] not in shown]
    ids = _created_order(conn, ids)
    first: dict[str, str] = {}  # one card per story key in a batch: the oldest
    for i in ids:
        first.setdefault(story_of[i], i)
    ids = [i for i in ids if first[story_of[i]] == i]
    ids = _hold_back_series(conn, ids, served, set(ids))
    due = _reserve_srs(len(ids), due[: knobs["max_srs_per_batch"]], limit)
    picked = ids[: limit - len(due)]
    picked = _hold_back_series(conn, picked, served, set(picked))
    ordered = _order_series(picked, _series_of(conn, picked) if picked else {})
    return _insert_srs(ordered, due, limit)

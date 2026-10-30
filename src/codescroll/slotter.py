"""Feed slotting (docs/learning.md section 5)."""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from codescroll import srs

SRS_MIN_POSITION = 3
DEFAULT_KNOBS = {
    "repeat_days": 7,
    "learning_boost_share": 0.10,
    "max_srs_per_batch": 2,
    "fast_formats": ["meme", "text_meme", "fun_fact", "chart", "hot_take"],
    "slow_formats": ["thread", "comic", "code_card", "quiz", "iceberg", "day_in_life"],
}


def _knobs(rc) -> dict:
    return {**DEFAULT_KNOBS, **(rc.slotting or {})}


def _rhythm(order: list[str], format_of: dict[str, str], knobs: dict) -> list[str]:
    """Greedy reorder: no 3 equal formats in a row, fast and slow formats alternate.

    Walks `order` (best first); at each step takes the first card that keeps the run of equal
    formats at 2 or less, preferring the opposite speed of the previous card.
    """
    fast, slow = set(knobs["fast_formats"]), set(knobs["slow_formats"])

    def speed(i: str) -> str | None:
        f = format_of[i]
        return "fast" if f in fast else "slow" if f in slow else None

    rest, out = list(order), []
    while rest:
        allowed = [
            i
            for i in rest
            if not (len(out) >= 2 and format_of[out[-1]] == format_of[out[-2]] == format_of[i])
        ] or rest
        want = {"fast": "slow", "slow": "fast"}.get(speed(out[-1])) if out else None
        pick = next((i for i in allowed if want and speed(i) == want), allowed[0])
        rest.remove(pick)
        out.append(pick)
    return out


def _insert_srs(ordered: list[str], due: list[str], limit: int) -> list[str]:
    """Place due cards at positions 3, 3 + gap, ...; a card that would land past the end waits."""
    gap = max(3, limit // 2)
    out = list(ordered)
    for n, card_id in enumerate(due):
        pos = SRS_MIN_POSITION + n * gap
        if pos <= len(out):
            out.insert(pos, card_id)
    return out


def _dir_coverage(conn) -> dict[str, int]:
    """Impressions per dir, over all time."""
    rows = conn.execute(
        "SELECT f.value AS dir, COUNT(*) AS n FROM events e "
        "JOIN card_features f ON f.card_id = e.card_id AND f.feature = 'dir' "
        "WHERE e.type = 'impression' GROUP BY f.value"
    )
    return {r["dir"]: r["n"] for r in rows}


def _candidates(conn, rc, served: set[str], now: datetime) -> list[str]:
    repeat_days = _knobs(rc)["repeat_days"]
    cutoff_ms = int((now - timedelta(days=repeat_days)).timestamp() * 1000)
    recent = {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT card_id FROM events WHERE type = 'impression' AND ts >= ? "
            "AND card_id IS NOT NULL",
            (cutoff_ms,),
        )
    }
    rows = conn.execute("SELECT id FROM cards WHERE status = 'ready' ORDER BY id").fetchall()
    return [r["id"] for r in rows if r["id"] not in served and r["id"] not in recent]


def _active_rules(conn, now: datetime) -> list:
    iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    return conn.execute(
        "SELECT * FROM rules WHERE expires_at IS NULL OR expires_at > ? ORDER BY id", (iso,)
    ).fetchall()


def build_batch(conn, cfg, limit: int, served: set[str], seed: int, now: datetime) -> list[str]:
    from codescroll import learning

    rc = learning.load_reward_config(cfg)
    rng = random.Random(seed)
    knobs = _knobs(rc)
    due = [d for d in srs.due_cards(conn, now) if d not in served]
    ids = [i for i in _candidates(conn, rc, served, now) if i not in due]
    feats = {i: set(learning.card_features(conn, cfg, i, now=now)) for i in ids + due}
    rules = _active_rules(conn, now)
    for r in rules:
        if r["type"] == "ban":
            ids = [i for i in ids if (r["feature"], r["value"]) not in feats[i]]
            due = [i for i in due if (r["feature"], r["value"]) not in feats[i]]
    due = due[: min(knobs["max_srs_per_batch"], max(0, limit - SRS_MIN_POSITION))]
    slots = limit - len(due)
    scores = learning.score_cards(conn, cfg, ids, rng, now=now)
    for r in rules:
        if r["type"] in ("boost", "prefer"):
            for i in ids:
                if (r["feature"], r["value"]) in feats[i]:
                    scores[i] = scores.get(i, 0.0) * (
                        r["factor"] if r["factor"] is not None else 1.0
                    )
    ids.sort(key=lambda i: (-scores.get(i, 0.0), i))

    caps = [
        ((r["feature"], r["value"]), int((r["max_share"] or 0.0) * limit))
        for r in rules
        if r["type"] == "limit"
    ]
    picked: list[str] = []

    def take(i: str) -> bool:
        if i in picked or len(picked) >= slots:
            return False
        for key, cap in caps:
            if key in feats[i] and sum(key in feats[p] for p in picked) >= cap:
                return False
        picked.append(i)
        return True

    for r in rules:
        if r["type"] == "focus":
            key, want = (r["feature"], r["value"]), r["slots"] or 0
            have = sum(key in feats[p] for p in picked)
            for i in ids:
                if have >= want:
                    break
                if key in feats[i] and take(i):
                    have += 1

    share = float(cfg.defaults.get("exploration_share", 0.18))
    lower = ids[(len(ids) + 1) // 2 :]
    rng.shuffle(lower)
    wanted = round(share * limit)
    done = 0
    for i in lower:
        if done >= wanted:
            break
        if take(i):
            done += 1

    coverage = _dir_coverage(conn)

    def seen(i: str) -> float:
        dirs = [v for f, v in feats[i] if f == "dir"]
        return min((coverage.get(d, 0) for d in dirs), default=float("inf"))

    wanted = round(_knobs(rc)["learning_boost_share"] * limit)
    done = 0
    for i in sorted(ids, key=lambda i: (seen(i), -scores.get(i, 0.0), i)):
        if done >= wanted:
            break
        if take(i):
            done += 1

    for i in ids:
        take(i)
    picked.sort(key=lambda i: (-scores.get(i, 0.0), i))
    formats = {
        r["id"]: r["format"]
        for r in conn.execute(
            f"SELECT id, format FROM cards WHERE id IN ({','.join('?' * len(picked))})", picked
        )
    }
    ordered = _rhythm(picked, formats, knobs)
    return _insert_srs(ordered, due, limit)

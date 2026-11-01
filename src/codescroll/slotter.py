"""Feed slotting (docs/learning.md section 5)."""

from __future__ import annotations

import random
from datetime import datetime

from codescroll import srs, supply

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


def _prob_round(x: float, rng: random.Random) -> int:
    """floor(x), plus 1 with probability equal to the fraction, so small batches still explore."""
    whole = int(x)
    frac = x - whole
    return whole + (1 if frac > 1e-9 and rng.random() < frac else 0)


def _dir_coverage(conn) -> dict[str, int]:
    """Impressions per dir, over all time."""
    rows = conn.execute(
        "SELECT f.value AS dir, COUNT(*) AS n FROM events e "
        "JOIN card_features f ON f.card_id = e.card_id AND f.feature = 'dir' "
        "WHERE e.type = 'impression' GROUP BY f.value"
    )
    return {r["dir"]: r["n"] for r in rows}


def dir_matches(card_dir: str, rule_dir: str) -> bool:
    """Path-prefix match: `src` covers `src` and `src/api`, not `lib/src`."""
    d = rule_dir.strip("/")
    c = card_dir.strip("/")
    return c == d or c.startswith(d + "/")


def rule_matches(feature: str, value: str, feats) -> bool:
    """Does a card with `feats` (set of (feature, value)) match a rule on (feature, value)?

    `dir` uses path-prefix semantics; a rule dir may carry a `repo/` prefix of a card repo.
    """
    if feature != "dir":
        return (feature, value) in feats
    repos = [v for f, v in feats if f == "repo"]
    wants = [value] + [value[len(r) + 1 :] for r in repos if value.startswith(r + "/")]
    return any(dir_matches(v, w) for f, v in feats if f == "dir" for w in wants)


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
    ids = [i for i in supply.unseen_ready(conn, rc, now) if i not in served and i not in due]
    feats = {i: set(learning.card_features(conn, cfg, i, now=now)) for i in ids + due}
    rules = _active_rules(conn, now)
    for r in rules:
        if r["type"] == "ban":
            ids = [i for i in ids if not rule_matches(r["feature"], r["value"], feats[i])]
            due = [i for i in due if not rule_matches(r["feature"], r["value"], feats[i])]
    due = _reserve_srs(len(ids), due[: knobs["max_srs_per_batch"]], limit)
    slots = limit - len(due)
    scores = learning.score_cards(conn, cfg, ids, rng, now=now)
    for r in rules:
        if r["type"] in ("boost", "prefer"):
            for i in ids:
                if rule_matches(r["feature"], r["value"], feats[i]):
                    scores[i] = scores.get(i, 0.0) * (
                        r["factor"] if r["factor"] is not None else 1.0
                    )
    ids.sort(key=lambda i: (-scores.get(i, 0.0), i))

    caps = [
        (
            r,
            0 if r["max_share"] == 0 else max(1, round(r["max_share"] * limit)),
        )
        for r in rules
        if r["type"] == "limit" and r["max_share"] is not None
    ]
    picked: list[str] = []

    def take(i: str) -> bool:
        if i in picked or len(picked) >= slots:
            return False
        for r, cap in caps:
            hit = rule_matches
            if hit(r["feature"], r["value"], feats[i]) and (
                sum(hit(r["feature"], r["value"], feats[p]) for p in picked) >= cap
            ):
                return False
        picked.append(i)
        return True

    for r in rules:
        if r["type"] == "focus":
            f, v, want = r["feature"], r["value"], r["slots"] or 0
            have = sum(rule_matches(f, v, feats[p]) for p in picked)
            for i in ids:
                if have >= want:
                    break
                if rule_matches(f, v, feats[i]) and take(i):
                    have += 1

    share = float(cfg.defaults.get("exploration_share", 0.18))
    lower = ids[(len(ids) + 1) // 2 :]
    rng.shuffle(lower)
    wanted = _prob_round(share * limit, rng)
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

    wanted = _prob_round(knobs["learning_boost_share"] * limit, rng)
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

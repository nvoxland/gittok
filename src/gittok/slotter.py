"""Feed slotting (docs/learning.md section 5)."""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from gittok import characters, db, srs, supply

SRS_MIN_POSITION = 3
QUIZ_WINDOW = 8  # each window of this many cards holds an unseen quiz card when one exists
SERIES_GAP = 3  # parts of one series sit at least this many positions apart


# Read time of every format in docs/formats.md: a glance (fast) or a stop-and-read (slow).
# The fast_formats/slow_formats knobs win; this fills in the formats they leave out.
FORMAT_SPEED = {
    **dict.fromkeys(
        ("meme", "text_meme", "fun_fact", "chart", "hot_take", "text_post", "flags", "horoscope",
         "breaking_news", "listicle", "tier_list"),
        "fast",
    ),
    **dict.fromkeys(
        ("thread", "comic", "code_card", "quiz", "iceberg", "day_in_life", "eli5", "diagram",
         "mascot_scene", "group_chat", "dating_profile", "glow_up"),
        "slow",
    ),
}  # fmt: skip


def format_speed(fmt: str, knobs: dict) -> str | None:
    """ "fast" or "slow" for a format; the knob lists first, then FORMAT_SPEED."""
    if fmt in knobs["fast_formats"]:
        return "fast"
    if fmt in knobs["slow_formats"]:
        return "slow"
    return FORMAT_SPEED.get(fmt)


def _knobs(rc) -> dict:
    """The slotting knobs (config/reward.yaml `slotting`; the shipped file holds the defaults)."""
    return rc.slotting


def _rhythm(order: list[str], format_of: dict[str, str], knobs: dict) -> list[str]:
    """Greedy reorder: no 3 equal formats in a row, fast and slow formats alternate.

    Walks `order` (best first); at each step takes the first card that keeps the run of equal
    formats at 2 or less, preferring the opposite speed of the previous card.
    """

    def speed(i: str) -> str | None:
        return format_speed(format_of[i], knobs)

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


def _quiz_ids(conn, ids: list[str]) -> list[str]:
    """The quiz-format cards among `ids`, in their order."""
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    quiz = {
        r[0]
        for r in conn.execute(
            f"SELECT id FROM cards WHERE format = 'quiz' AND id IN ({marks})", ids
        )
    }
    return [i for i in ids if i in quiz]


def _place_quizzes(order: list[str], quizzes: set[str], due: set[str]) -> list[str]:
    """Make sure each full window of QUIZ_WINDOW cards has an unseen quiz card, if one is later on.

    A quiz from further down moves to the last place of the window. Due (SRS) cards stay put.
    """
    out = list(order)
    for w in range(len(out) // QUIZ_WINDOW):
        lo, hi = w * QUIZ_WINDOW, (w + 1) * QUIZ_WINDOW
        if any(i in quizzes for i in out[lo:hi]):
            continue
        later = next((j for j in range(hi, len(out)) if out[j] in quizzes), None)
        slot = next((j for j in range(hi - 1, lo - 1, -1) if out[j] not in due), None)
        if later is not None and slot is not None:
            out.insert(slot, out.pop(later))
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


FEATURE_CHUNK = 500  # card ids per query (sqlite limits the number of parameters)


def features_for(conn, cfg, ids: list[str], now: datetime) -> dict[str, set[tuple[str, str]]]:
    """Card id -> its features, as the learner sees them at an impression: the stored rows,
    the derived `group` and `recency`, and `familiarity` (how well the reader knows the
    card's code now). Read with two queries per FEATURE_CHUNK cards and not two per card. An
    unknown card has no features."""
    from gittok import learning

    nmaps: dict[str, dict] = {}
    out: dict[str, set[tuple[str, str]]] = {i: set() for i in ids}
    for at in range(0, len(ids), FEATURE_CHUNK):
        chunk = ids[at : at + FEATURE_CHUNK]
        marks = ",".join("?" * len(chunk))
        rows = conn.execute(f"SELECT id, created_at FROM cards WHERE id IN ({marks})", chunk)
        created = dict(rows.fetchall())
        for card_id, feature, value in conn.execute(
            f"SELECT card_id, feature, value FROM card_features WHERE card_id IN ({marks})", chunk
        ):
            if card_id in created:
                out[card_id].add((feature, value))
        for card_id, created_at in created.items():
            feats = out[card_id]
            repos = [v for f, v in feats if f == "repo" and v in cfg.repos]
            feats |= {("group", cfg.repos[r].group) for r in repos if cfg.repos[r].group}
            feats.add(("recency", learning._recency(created_at, now)))
            learning.add_familiarity(conn, cfg, feats, nmaps)
    return out


def build_batch(conn, cfg, limit: int, served: set[str], seed: int, now: datetime) -> list[str]:
    from gittok import learning

    rc = learning.load_reward_config(cfg)
    rng = random.Random(seed)
    knobs = _knobs(rc)
    served = served | supply.unconfigured_cards(conn, cfg)  # a removed repo is never shown
    due = [d for d in srs.due_cards(conn, now) if d not in served]
    ids = [i for i in supply.unseen_ready(conn, rc, now) if i not in served and i not in due]
    # Variants of one story are never close together: skip stories shown within repeat_days.
    story_of = _story_keys(conn, ids)
    since_ms = int((now - timedelta(days=knobs["repeat_days"])).timestamp() * 1000)
    shown = _impressed_stories(conn, since_ms)
    ids = [i for i in ids if story_of[i] not in shown]
    feats = features_for(conn, cfg, ids + due, now)
    rules = _active_rules(conn, now)
    for r in rules:
        if r["type"] == "ban":
            ids = [i for i in ids if not rule_matches(r["feature"], r["value"], feats[i])]
            due = [i for i in due if not rule_matches(r["feature"], r["value"], feats[i])]
    due = _reserve_srs(len(ids), due[: knobs["max_srs_per_batch"]], limit)
    slots = limit - len(due)
    scores = learning.score_cards(conn, cfg, ids, rng, now=now, feats=feats)
    for r in rules:
        if r["type"] in ("boost", "prefer"):
            for i in ids:
                if rule_matches(r["feature"], r["value"], feats[i]):
                    scores[i] = scores.get(i, 0.0) * (
                        r["factor"] if r["factor"] is not None else 1.0
                    )
    follow_dirs = characters.followed_dirs(conn)
    if follow_dirs:  # a followed file or dir lifts its dir's cards (characters.FOLLOW_BOOST)
        for i in ids:
            repos = [v for f, v in feats[i] if f == "repo"]
            card_dirs = [v for f, v in feats[i] if f == "dir"]
            if any(
                r in repos and any(dir_matches(d, fd) for d in card_dirs) for r, fd in follow_dirs
            ):
                scores[i] = scores.get(i, 0.0) * characters.FOLLOW_BOOST
    ids = _hold_back_series(conn, ids, served, set(ids))
    ids.sort(key=lambda i: (-scores.get(i, 0.0), i))
    best: dict[str, str] = {}  # one card per story key in a batch: the best scored
    for i in ids:
        best.setdefault(story_of[i], i)
    ids = [i for i in ids if best[story_of[i]] == i]

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

    # An unseen quiz card for each window of QUIZ_WINDOW cards, best scored first.
    quizzes = _quiz_ids(conn, ids)
    for i in quizzes[: limit // QUIZ_WINDOW]:
        take(i)

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
    picked = _hold_back_series(conn, picked, served, set(picked))
    picked.sort(key=lambda i: (-scores.get(i, 0.0), i))
    formats = {
        r["id"]: r["format"]
        for r in conn.execute(
            f"SELECT id, format FROM cards WHERE id IN ({','.join('?' * len(picked))})", picked
        )
    }
    ordered = _rhythm(picked, formats, knobs)
    ordered = _order_series(ordered, _series_of(conn, picked) if picked else {})
    return _place_quizzes(_insert_srs(ordered, due, limit), set(quizzes) - set(due), set(due))

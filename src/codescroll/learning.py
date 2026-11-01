"""Reward, Thompson-sampling weights, and category shares (docs/learning.md sections 3, 4, 9)."""

from __future__ import annotations

import json
import logging
import math
import threading
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import yaml

from codescroll import db

log = logging.getLogger(__name__)

CAP_MS = 30 * 60 * 1000


@dataclass(frozen=True)
class RewardConfig:
    skip_ms: int = 1000
    weights: dict = field(
        default_factory=lambda: {
            "dwell": 0.45,
            "depth_open": 0.15,
            "explain_more": 0.15,
            "like": 0.25,
            "source_tap": 0.10,
            "scroll_back": 0.35,
            "answer": 0.20,
            "complete": 0.15,
            "replay": 0.30,
        }
    )
    ms_per_word: int = 250
    expected_ms_max: int = 45000
    format_base_ms: dict = field(
        default_factory=lambda: {
            "default": 2500,
            "meme": 1500,
            "text_meme": 1500,
            "fun_fact": 2000,
            "chart": 3000,
            "code_card": 4000,
            "quiz": 4000,
            "thread": 6000,
            "comic": 6000,
            "iceberg": 5000,
            "day_in_life": 5000,
        }
    )
    importance: dict = field(
        default_factory=lambda: {
            "story_type": 1.0,
            "format": 1.0,
            "tone": 0.7,
            "persona": 0.5,
            "repo": 0.8,
            "group": 0.4,
            "dir": 0.6,
            "visual_kind": 0.5,
            "template": 0.5,
            "recency": 0.6,
            "difficulty": 0.3,
            "has_comments": 0.2,
        }
    )
    half_life_days: float = 21
    slotting: dict = field(default_factory=dict)


class RewardConfigError(ValueError):
    pass


def load_reward_config(cfg) -> RewardConfig:
    """Read config/reward.yaml; missing file means built-in defaults, unknown keys are errors."""
    base = RewardConfig()
    path = cfg.root / "config" / "reward.yaml"
    if not path.is_file():
        return base
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        raise RewardConfigError(f"{path} must be a mapping")
    allowed = set(RewardConfig.__dataclass_fields__)
    for key in data:
        if key not in allowed:
            raise RewardConfigError(f"unknown key '{key}' in {path}")
    merged: dict[str, Any] = {}
    for key, value in data.items():
        current = getattr(base, key)
        if isinstance(current, dict) and key != "slotting":
            if not isinstance(value, dict):
                raise RewardConfigError(f"'{key}' must be a mapping in {path}")
            for sub in value:
                if key in ("weights", "importance") and sub not in current:
                    raise RewardConfigError(f"unknown key '{key}.{sub}' in {path}")
            merged[key] = {**current, **value}
        else:
            merged[key] = value
    return RewardConfig(**{**base.__dict__, **merged})


_SKIP_TEXT_KEYS = {"kind", "repo", "path", "commit", "template", "chart", "style", "dir", "mermaid"}


def _strings(value, key=None):
    if isinstance(value, str):
        if key not in _SKIP_TEXT_KEYS:
            yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _strings(v, k)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v, key)


def _first_explain(spec: dict) -> str:
    for panel in spec.get("depth") or []:
        if panel.get("kind") == "explain":
            return panel.get("text", "")
    return ""


def expected_ms(rc: RewardConfig, spec: dict) -> int:
    words = 0
    for text in (spec.get("hook", ""), *_strings(spec.get("visual", {})), _first_explain(spec)):
        words += len(text.split())
    base = rc.format_base_ms.get(spec.get("format"), rc.format_base_ms.get("default", 2500))
    return min(rc.expected_ms_max, base + rc.ms_per_word * words)


def _now(now: datetime | None) -> datetime:
    return (now or datetime.now(UTC)).astimezone(UTC)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


MAX_DWELL_MS = 24 * 60 * 60 * 1000


def _ms(value) -> int:
    """A client-sent duration as clean ms: junk or negative is 0, capped at 24 hours."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return 0
    try:
        ms = float(value)
    except ValueError:
        return 0
    if not math.isfinite(ms) or ms < 0:
        return 0
    return int(min(ms, MAX_DWELL_MS))


def _toggled_on(events: list[tuple[str, dict]], name: str) -> bool:
    toggles = [d.get("on", True) for t, d in events if t == name]
    return bool(toggles and toggles[-1])


def _watch_fraction(rc: RewardConfig, spec: dict, dwell_events: list[dict], dwell_ms: int) -> float:
    """How much of the card was 'watched', 0..1, like a video's watch fraction.

    A beat card reports the time its sequence played (`ms_played`, holds included) and the
    sequence length (`total_ms`); time on screen after playback earns nothing. A static card
    is a one-beat video as long as its expected reading time.
    """
    total = max((_ms(d.get("total_ms", 0)) for d in dwell_events), default=0)
    if total > 0:
        return min(1.0, sum(_ms(d.get("ms_played", 0)) for d in dwell_events) / total)
    return min(1.0, dwell_ms / expected_ms(rc, spec))


def _reward(rc: RewardConfig, spec: dict, events: list[tuple[str, dict]]) -> float:
    w = rc.weights
    dwell_events = [d for t, d in events if t == "dwell"]
    dwell_ms = sum(_ms(d.get("ms", 0)) for d in dwell_events)
    types = {t for t, _ in events}
    skipped = "skip" in types or (
        bool(dwell_events) and dwell_ms < rc.skip_ms and not types - {"dwell", "skip"}
    )
    if skipped and not _toggled_on(events, "like"):
        return 0.0
    r = w["dwell"] * _watch_fraction(rc, spec, dwell_events, dwell_ms)
    for name in ("depth_open", "explain_more", "source_tap", "scroll_back"):
        if name in types:
            r += w[name]
    if "beats_done" in types:
        r += w["complete"]
    if "replay" in types:
        r += w["replay"]
    if "answer" in types:
        r += w["answer"]
    if _toggled_on(events, "like"):
        r += w["like"]
    return max(0.0, min(1.0, r))


def _closed_impressions(conn, now_ms: int):
    """Unprocessed impressions whose window is closed, with their window end, oldest first."""
    rows = conn.execute(
        "SELECT e.id, e.card_id, e.ts, e.data FROM events e WHERE e.type = 'impression' "
        "AND e.card_id IS NOT NULL ORDER BY e.ts, e.id"
    ).fetchall()
    done = {r[0] for r in conn.execute("SELECT impression_event_id FROM rewards")}
    groups: dict[tuple, list] = {}
    for r in rows:
        session = (db.loads(r["data"]) or {}).get("session")
        key = ("s", session) if session else ("c", r["card_id"])
        groups.setdefault(key, []).append(r)
    out = []
    for items in groups.values():
        for i, r in enumerate(items):
            if r["id"] in done:
                continue
            nxt = items[i + 1] if i + 1 < len(items) else None
            if nxt is None and now_ms < r["ts"] + CAP_MS:
                continue
            end = min(nxt["ts"], r["ts"] + CAP_MS) if nxt else r["ts"] + CAP_MS
            out.append((r, end))
    out.sort(key=lambda x: (x[0]["ts"], x[0]["id"]))
    return out


def process_events(conn, cfg, now: datetime | None = None) -> dict:
    """Turn closed, unprocessed impressions into rewards and update weights. Idempotent."""
    now = _now(now)
    rc = load_reward_config(cfg)
    stats = {"impressions": 0, "rewards": 0, "weights": 0}
    touched: set = set()
    with db.immediate(conn):
        for imp, end in _closed_impressions(conn, int(now.timestamp() * 1000)):
            row = conn.execute("SELECT spec FROM cards WHERE id = ?", (imp["card_id"],)).fetchone()
            if row is None:
                continue
            spec = json.loads(row["spec"])
            events = [
                (e["type"], d if isinstance(d := db.loads(e["data"]), dict) else {})
                for e in conn.execute(
                    "SELECT type, data FROM events WHERE card_id = ? AND type != 'impression' "
                    "AND (ts > ? OR (ts = ? AND id > ?)) AND ts <= ? ORDER BY ts, id",
                    (imp["card_id"], imp["ts"], imp["ts"], imp["id"], end),
                )
            ]
            try:
                r = _reward(rc, spec, events)
            except Exception:  # one odd event must not stop learning for the rest
                log.exception("could not score impression %s", imp["id"])
                continue
            conn.execute(
                "INSERT INTO rewards(card_id, impression_event_id, reward, computed_at) "
                "VALUES (?, ?, ?, ?)",
                (imp["card_id"], imp["id"], r, _iso(now)),
            )
            stats["impressions"] += 1
            stats["rewards"] += 1
            for feature, value in card_features(conn, cfg, imp["card_id"], now=now):
                _update_weight(conn, cfg, rc, feature, value, r, now)
                touched.add((feature, value))
    stats["weights"] = len(touched)
    return stats


# ---------------------------------------------------------------- features and priors


def _recency(created_at: str, now: datetime) -> str:
    try:
        created = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return "old"
    age = (now - created).days
    return "new" if age < 7 else "recent" if age < 30 else "old"


def card_features(conn, cfg, card_id: str, now: datetime | None = None) -> list[tuple[str, str]]:
    """Stored card_features plus derived `group` (from config) and `recency`."""
    now = _now(now)
    row = conn.execute("SELECT created_at FROM cards WHERE id = ?", (card_id,)).fetchone()
    if row is None:
        return []
    feats = [
        (r["feature"], r["value"])
        for r in conn.execute(
            "SELECT feature, value FROM card_features WHERE card_id = ? ORDER BY feature, value",
            (card_id,),
        )
    ]
    groups = sorted(
        {cfg.repos[v].group for f, v in feats if f == "repo" and v in cfg.repos} - {None}
    )
    feats += [("group", g) for g in groups]
    feats.append(("recency", _recency(row["created_at"], now)))
    return feats


def _prior_strength(cfg) -> float:
    return float(cfg.defaults.get("prior_strength", 10))


def _category_maps() -> tuple[dict, dict]:
    from codescroll import brief

    return brief.CATEGORY_STORIES, brief.CATEGORY_FORMATS


def _mix_share(cfg, feature: str, value: str) -> tuple[float, float] | None:
    """(share, mean_share) of a value within a default mix, or None if it is not in one."""
    if feature == "tone":
        mix = cfg.defaults.get("tones") or {}
        return (mix[value], 1 / len(mix)) if value in mix else None
    if feature in ("story_type", "format"):
        mix = cfg.defaults.get("categories") or {}
        stories, formats = _category_maps()
        table = stories if feature == "story_type" else formats
        shares = [mix[c] for c in mix if value in table.get(c, ())]
        return (sum(shares) / len(shares), 1 / len(mix)) if shares else None
    return None


def _prior(cfg, feature: str, value: str) -> tuple[float, float]:
    strength = _prior_strength(cfg)
    m = 0.5
    found = _mix_share(cfg, feature, value)
    if found:
        m = min(0.85, max(0.15, 0.5 * found[0] / found[1]))
    return strength * m, strength * (1 - m)


def _parse_iso(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def _decayed(rc: RewardConfig, cfg, row, now: datetime) -> tuple[float, float, float, float]:
    """(alpha, beta, alpha0, beta0) with the evidence decayed to `now`."""
    a0, b0 = _prior(cfg, row["feature"], row["value"])
    days = max(0.0, (now - _parse_iso(row["updated_at"])).total_seconds() / 86400)
    k = 0.5 ** (days / rc.half_life_days)
    return a0 + (row["alpha"] - a0) * k, b0 + (row["beta"] - b0) * k, a0, b0


def _update_weight(conn, cfg, rc, feature, value, r, now) -> None:
    row = conn.execute(
        "SELECT * FROM weights WHERE feature = ? AND value = ?", (feature, value)
    ).fetchone()
    if row is None:
        alpha, beta = _prior(cfg, feature, value)
    else:
        alpha, beta, _, _ = _decayed(rc, cfg, row, now)
    conn.execute(
        "INSERT INTO weights(feature, value, alpha, beta, updated_at) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(feature, value) DO UPDATE SET alpha = excluded.alpha, "
        "beta = excluded.beta, updated_at = excluded.updated_at",
        (feature, value, alpha + r, beta + 1 - r, _iso(now)),
    )


def posterior_means(
    conn, cfg, feature: str, now: datetime | None = None
) -> dict[str, tuple[float, float]]:
    """value -> (posterior mean, evidence count), decayed to `now` without writing."""
    now, rc = _now(now), load_reward_config(cfg)
    out = {}
    for row in conn.execute("SELECT * FROM weights WHERE feature = ?", (feature,)):
        alpha, beta, a0, b0 = _decayed(rc, cfg, row, now)
        out[row["value"]] = (alpha / (alpha + beta), (alpha - a0) + (beta - b0))
    return out


def score_cards(
    conn, cfg, card_ids: list[str], rng, now: datetime | None = None
) -> dict[str, float]:
    """Thompson sample per call: one Beta draw per (feature, value), shared by all cards.

    Score = importance-weighted mean of the draws over the card's features. Reads only.
    A card's `dir` prefixes count as one term: their draws are averaged first.
    """
    now, rc = _now(now), load_reward_config(cfg)
    feats = {cid: card_features(conn, cfg, cid, now=now) for cid in card_ids}
    feats = {cid: f for cid, f in feats.items() if f}
    stored = {
        (r["feature"], r["value"]): _decayed(rc, cfg, r, now)[:2]
        for r in conn.execute("SELECT * FROM weights")
    }
    draws: dict[tuple[str, str], float] = {}
    for key in sorted({k for f in feats.values() for k in f}):
        alpha, beta = stored.get(key) or _prior(cfg, *key)
        draws[key] = rng.betavariate(alpha, beta)
    out = {}
    for cid, f in feats.items():
        dirs = [draws[k] for k in f if k[0] == "dir"]
        terms = [(rc.importance.get(k[0], 0.0), draws[k]) for k in f if k[0] != "dir"]
        if dirs:
            terms.append((rc.importance.get("dir", 0.0), sum(dirs) / len(dirs)))
        total = sum(w for w, _ in terms)
        if total > 0:
            out[cid] = sum(w * d for w, d in terms) / total
    return out


# ---------------------------------------------------------------- category shares

SHARE_FLOOR = 0.05


def format_factors(conn, cfg, now: datetime | None = None) -> dict[str, float]:
    """Learned per-format factor for the brief's format pick.

    For a format with evidence (mean m over n decayed observations, priors removed), and ref
    the plain mean of m over formats with evidence (0.5 if none):

        factor = (prior_strength + n * m / ref) / (prior_strength + n)

    Formats without evidence are absent, which counts as factor 1.
    """
    now, rc = _now(now), load_reward_config(cfg)
    stats: dict[str, tuple[float, float]] = {}
    for row in conn.execute("SELECT * FROM weights WHERE feature = 'format'"):
        alpha, beta, a0, b0 = _decayed(rc, cfg, row, now)
        ea, eb = alpha - a0, beta - b0
        if ea + eb > 1e-9:
            stats[row["value"]] = (ea / (ea + eb), ea + eb)
    ref = sum(m for m, _ in stats.values()) / len(stats) if stats else 0.5
    strength = _prior_strength(cfg)
    if ref <= 0:
        return {}
    return {f: (strength + n * m / ref) / (strength + n) for f, (m, n) in stats.items()}


def category_shares(conn, cfg, now: datetime | None = None) -> dict[str, float]:
    """Learned share per default-mix category, blended with the shipped prior.

    For category c: lm_c is the evidence-weighted mean reward of c's story types and formats
    (evidence only, so the weight priors do not count twice), and n_c is the mean of the
    story-type evidence and the format evidence. ref is the plain mean of lm_c over
    categories with evidence (0.5 if none), so extra evidence in one category does not move it. Then

        relative_c = lm_c / ref
        factor_c   = (prior_strength + n_c * relative_c) / (prior_strength + n_c)
        share_c   ~ default_share_c * factor_c      (normalised to sum to 1)

    With no evidence n_c = 0, so factor = 1 and the shares equal the default mix. More
    evidence moves factor toward relative_c, which is above 1 for better-than-average
    categories. After normalising, no category goes below 0.05; clamped categories are fixed
    at 0.05 and the rest are rescaled to fill the remainder.
    """
    mix = {k: float(v) for k, v in (cfg.defaults.get("categories") or {}).items()}
    if not mix:
        return {}
    now, rc = _now(now), load_reward_config(cfg)
    stories, formats = _category_maps()
    evidence: dict[tuple[str, str], tuple[float, float]] = {}
    for row in conn.execute("SELECT * FROM weights WHERE feature IN ('story_type', 'format')"):
        alpha, beta, a0, b0 = _decayed(rc, cfg, row, now)
        ea, eb = alpha - a0, beta - b0
        if ea + eb > 1e-9:
            evidence[(row["feature"], row["value"])] = (ea / (ea + eb), ea + eb)

    stats: dict[str, tuple[float, float]] = {}  # category -> (learned mean, n)
    for c in mix:
        parts = [("story_type", stories.get(c, ())), ("format", formats.get(c, ()))]
        hits = [
            (feature, evidence[(feature, v)])
            for feature, vs in parts
            for v in vs
            if (feature, v) in evidence
        ]
        total = sum(n for _, (_, n) in hits)
        if total > 0:
            lm = sum(m * n for _, (m, n) in hits) / total
            n_c = (
                sum(n for f, (_, n) in hits if f == "story_type") / 2
                + sum(n for f, (_, n) in hits if f == "format") / 2
            )
            stats[c] = (lm, n_c)
    ref = sum(lm for lm, _ in stats.values()) / len(stats) if stats else 0.5
    strength = _prior_strength(cfg)
    raw = {}
    for c, share in mix.items():
        factor = 1.0
        if c in stats and ref > 0:
            lm, n_c = stats[c]
            factor = (strength + n_c * (lm / ref)) / (strength + n_c)
        raw[c] = share * factor
    total = sum(raw.values())
    if total <= 0:
        return {c: 0.0 for c in mix}
    shares = {c: v / total for c, v in raw.items()}
    # Categories with a default share of 0 stay 0; the floor only applies to the others.
    zero = {c for c, v in raw.items() if v <= 0}
    fixed: set[str] = set()
    while True:
        low = {
            c
            for c, v in shares.items()
            if v < SHARE_FLOOR - 1e-12 and c not in fixed and c not in zero
        }
        if not low:
            return shares
        fixed |= low
        room = 1 - SHARE_FLOOR * len(fixed)
        free = {c: raw[c] for c in shares if c not in fixed}
        free_total = sum(free.values())
        shares = {c: SHARE_FLOOR if c in fixed else free[c] / free_total * room for c in shares}


# ---------------------------------------------------------------- reset


def reset_weights(conn, feature: str | None = None) -> int:
    """Delete learned weights (all, or one feature). Returns the number of rows deleted."""
    with conn:
        if feature is None:
            cur = conn.execute("DELETE FROM weights")
        else:
            cur = conn.execute("DELETE FROM weights WHERE feature = ?", (feature,))
    return cur.rowcount


# ---------------------------------------------------------------- worker


class LearningWorker:
    """Background thread that runs `process_events` every `interval_s` (30 s by default)."""

    def __init__(self, get_config: Callable[[], Any], interval_s: float = 30.0):
        self._get_config = get_config
        self._interval = interval_s
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="learning-worker", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout)

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                cfg = self._get_config()
                with closing(db.open_db(cfg.settings.data_dir / "codescroll.db")) as conn:
                    process_events(conn, cfg)
            except Exception:
                log.exception("learning pass failed")
            self._stop.wait(self._interval)

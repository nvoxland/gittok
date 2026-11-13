"""Reward per impression, and the one learner: an additive model with Thompson sampling that
ranks the feed and decides what to make (docs/learning.md sections 3, 4, 7, 9)."""

from __future__ import annotations

import json
import logging
import math
import random
import threading
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from gittok import config, db, knowledge

log = logging.getLogger(__name__)

CAP_MS = 30 * 60 * 1000


@dataclass(frozen=True)
class RewardConfig:
    """Reward and ranking knobs. The values live in config/reward.yaml and nowhere else."""

    skip_ms: int
    weights: dict
    ms_per_word: int
    expected_ms_max: int
    format_base_ms: dict
    like_floor: float
    like_weight: float
    dislike_weight: float
    prior_sd: dict
    crosses: list
    lead_score: dict
    half_life_days: float
    slotting: dict


class RewardConfigError(ValueError):
    pass


_REWARD_FIELDS = tuple(RewardConfig.__dataclass_fields__)


def _reward_files(shared, home) -> tuple[RewardConfig, tuple[str, ...]]:
    """(reward config, warnings) from config/reward.yaml with local/reward.yaml merged over
    it (overlay.py). An unknown key is dropped with a warning, for the reason
    `config._drop_unknown` gives; a known key with a value of the wrong shape is an error."""
    from gittok import overlay

    try:
        ld = overlay.load("reward", shared, home)
    except config.ConfigError as e:
        raise RewardConfigError(str(e)) from None

    def build(data: dict) -> RewardConfig:
        missing = [k for k in _REWARD_FIELDS if k not in data]
        if missing:
            raise RewardConfigError(f"config/reward.yaml is missing: {', '.join(missing)}")
        return RewardConfig(**{k: data[k] for k in _REWARD_FIELDS})

    return ld.memo("reward_config", build), ld.warnings


def default_reward_config() -> RewardConfig:
    """The shipped config/reward.yaml. It must set every field."""
    return _reward_files(None, None)[0]


def load_reward_config(cfg) -> RewardConfig:
    """config/reward.yaml with the user's local/reward.yaml merged over it, key by key.

    A missing local file means the shipped values; an unknown key is dropped
    (`reward_warnings`). The parsed files are cached until one of them changes."""
    return _reward_files(getattr(cfg, "shared", None) or cfg.root, cfg.root)[0]


def reward_warnings(shared, home=None) -> tuple[str, ...]:
    """One warning for each reward key that was ignored."""
    return _reward_files(shared, home)[1]


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


@dataclass(frozen=True)
class Outcome:
    """What one impression teaches the model: a reward in [0, 1], how many times it counts,
    and the explicit signal behind it ('like', 'dislike' or None)."""

    reward: float
    weight: float = 1.0
    signal: str | None = None


# What the reader did with a card beyond looking at it. Any of these means the window is not
# a skip. A scroll back is not one: a quick pass on the way back is still a skip.
ENGAGED = frozenset(
    {"depth_open", "lightbox_open", "explain_more", "source_tap", "beats_done", "replay", "answer"}
)


def _visits_skipped(events: list[tuple[str, dict]]) -> list[bool]:
    """One entry per visit of the window: was it a skip? The client sends a dwell for each
    visit and a skip right after the dwell of a visit it calls a skip. A skip with no dwell
    before it (an old client) is a visit of its own."""
    visits: list[bool] = []
    for t, _ in events:
        if t == "dwell":
            visits.append(False)
        elif t == "skip":
            if visits and not visits[-1]:
                visits[-1] = True
            else:
                visits.append(True)
    return visits


def _reward(rc: RewardConfig, spec: dict, events: list[tuple[str, dict]]) -> float:
    """The implicit reward: watch time and engagement, with a like or save on top.

    The window is a skip when nothing in ENGAGED happened and every visit was a skip, or all
    the visits together were shorter than `skip_ms`. One short look after a long read is
    not a skip."""
    w = rc.weights
    dwell_events = [d for t, d in events if t == "dwell"]
    dwell_ms = sum(_ms(d.get("ms", 0)) for d in dwell_events)
    types = {t for t, _ in events}
    visits = _visits_skipped(events)
    skipped = not types & ENGAGED and (
        (bool(visits) and all(visits)) or (bool(dwell_events) and dwell_ms < rc.skip_ms)
    )
    if skipped and not (_toggled_on(events, "like") or _toggled_on(events, "save")):
        return 0.0
    r = w["dwell"] * _watch_fraction(rc, spec, dwell_events, dwell_ms)
    for name in ("depth_open", "lightbox_open", "explain_more", "source_tap", "scroll_back"):
        if name in types:
            r += w[name]
    if "beats_done" in types:
        r += w["complete"]
    if "replay" in types:
        r += w["replay"]
    if "answer" in types:
        r += w["answer"]
    for name in ("like", "save"):
        if _toggled_on(events, name):
            r += w[name]
    return max(0.0, min(1.0, r))


def outcome(rc: RewardConfig, spec: dict, events: list[tuple[str, dict]]) -> Outcome:
    """A 👎 (last toggle on) wins: reward 0, counted `dislike_weight` times. A like lifts the
    reward to `like_floor` and counts `like_weight` times. Else the implicit reward, once."""
    if _toggled_on(events, "dislike"):
        return Outcome(0.0, float(rc.dislike_weight), "dislike")
    r = _reward(rc, spec, events)
    if _toggled_on(events, "like"):
        return Outcome(max(r, float(rc.like_floor)), float(rc.like_weight), "like")
    return Outcome(r)


def _dislike_state(conn) -> dict[str, tuple[bool, int]]:
    """card id -> (is the last 👎 toggle on, its ts) for every card with a 👎 event."""
    out: dict[str, tuple[bool, int]] = {}
    for r in conn.execute(
        "SELECT card_id, ts, data FROM events WHERE type = 'dislike' AND card_id IS NOT NULL "
        "ORDER BY ts, id"
    ):
        d = db.loads(r["data"])
        out[r["card_id"]] = (bool(d.get("on", True)) if isinstance(d, dict) else True, r["ts"])
    return out


def _closed_impressions(conn, now_ms: int, dislikes: dict | None = None):
    """Unprocessed impressions whose window is closed, oldest first, each as (impression row,
    window end ts, id of the impression that ends it or None).

    A window ends at the next impression of the session, or after CAP_MS. An event at the
    same ms as the next impression belongs to the window with the lower id. A 👎 that is
    still on ends the window at once (at `now_ms`): the reader said what they think, and the
    next cards should know. Only impressions of cards that exist and that have no reward yet
    are read, so a pass costs what is new, not the whole history."""
    pending = conn.execute(
        "SELECT e.id, e.card_id, e.ts, e.data FROM events e WHERE e.type = 'impression' "
        "AND e.card_id IS NOT NULL AND EXISTS (SELECT 1 FROM cards c WHERE c.id = e.card_id) "
        "AND NOT EXISTS (SELECT 1 FROM rewards r WHERE r.impression_event_id = e.id) "
        "ORDER BY e.ts, e.id"
    ).fetchall()
    if not pending:
        return []
    todo = {r["id"] for r in pending}
    rows = conn.execute(  # the pending ones and every later impression that may end a window
        "SELECT e.id, e.card_id, e.ts, e.data FROM events e WHERE e.type = 'impression' "
        "AND e.card_id IS NOT NULL AND e.ts >= ? ORDER BY e.ts, e.id",
        (pending[0]["ts"],),
    ).fetchall()
    if dislikes is None:
        dislikes = _dislike_state(conn)
    groups: dict[tuple, list] = {}
    for r in rows:
        data = db.loads(r["data"])
        session = data.get("session") if isinstance(data, dict) else None
        key = ("s", session) if session else ("c", r["card_id"])
        groups.setdefault(key, []).append(r)
    out = []
    for items in groups.values():
        for i, r in enumerate(items):
            if r["id"] not in todo:
                continue
            nxt = items[i + 1] if i + 1 < len(items) else None
            if nxt is None and now_ms < r["ts"] + CAP_MS:
                on, ts = dislikes.get(r["card_id"], (False, -1))
                if on and ts >= r["ts"]:
                    out.append((r, now_ms, None))
                continue
            if nxt is not None and nxt["ts"] <= r["ts"] + CAP_MS:
                out.append((r, nxt["ts"], nxt["id"]))
            else:
                out.append((r, r["ts"] + CAP_MS, None))
    out.sort(key=lambda x: (x[0]["ts"], x[0]["id"]))
    return out


def _last_toggle(events: list[tuple[str, dict]], name: str) -> int | None:
    """1 or 0 for the last toggle of `name`, None when there is none."""
    if not any(t == name for t, _ in events):
        return None
    return int(_toggled_on(events, name))


def _window_events(conn, imp, end: int, end_id: int | None) -> list[tuple[str, dict]]:
    return [
        (e["type"], d if isinstance(d := db.loads(e["data"]), dict) else {})
        for e in conn.execute(
            "SELECT type, data FROM events WHERE card_id = ? AND type != 'impression' "
            "AND (ts > ? OR (ts = ? AND id > ?)) "
            "AND (ts < ? OR (ts = ? AND (? IS NULL OR id < ?))) ORDER BY ts, id",
            (imp["card_id"], imp["ts"], imp["ts"], imp["id"], end, end, end_id, end_id),
        )
    ]


def _retract_dislikes(conn, dislikes: dict) -> int:
    """Take back the 👎 rewards of cards whose last 👎 toggle is off: delete the reward (the
    impression is scored again, without the 👎) and clear the story's mark. Returns how many."""
    off = [cid for cid, (on, _) in dislikes.items() if not on]
    n = 0
    for i in range(0, len(off), 500):
        chunk = off[i : i + 500]
        marks = ",".join("?" * len(chunk))
        rows = conn.execute(
            f"SELECT id, card_id FROM rewards WHERE signal = 'dislike' AND card_id IN ({marks})",
            chunk,
        ).fetchall()
        for r in rows:
            conn.execute("DELETE FROM rewards WHERE id = ?", (r["id"],))
            conn.execute(
                "UPDATE stories SET disliked = 0 "
                "WHERE story_key = (SELECT story_key FROM cards WHERE id = ?)",
                (r["card_id"],),
            )
        n += len(rows)
    return n


def _stamp_familiarity(conn, cfg, nmaps: dict) -> None:
    """Write the reader's familiarity with its code into each new impression, before the
    knowledge model counts it: the reward must learn what the reader knew when the card was
    ranked, not after this impression was counted."""
    rows = conn.execute(
        "SELECT e.id, e.card_id FROM events e WHERE e.type = 'impression' "
        "AND e.card_id IS NOT NULL AND json_valid(e.data) AND json_type(e.data) = 'object' "
        "AND json_extract(e.data, '$.familiarity') IS NULL "
        "AND EXISTS (SELECT 1 FROM cards c WHERE c.id = e.card_id) "
        "AND NOT EXISTS (SELECT 1 FROM rewards r WHERE r.impression_event_id = e.id)"
    ).fetchall()
    for r in rows:
        feats = set(
            conn.execute(
                "SELECT feature, value FROM card_features WHERE card_id = ? "
                "AND feature IN ('repo', 'dir')",
                (r["card_id"],),
            ).fetchall()
        )
        feats = {(f, v) for f, v in feats}
        repo = next((v for f, v in sorted(feats) if f == "repo"), None)
        dirs = [v for f, v in feats if f == "dir"]
        value = familiarity_of(conn, cfg, repo, dirs, nmaps)
        conn.execute(
            "UPDATE events SET data = json_set(data, '$.familiarity', ?) WHERE id = ?",
            (value, r["id"]),
        )


def process_events(conn, cfg, now: datetime | None = None) -> dict:
    """Turn closed, unprocessed impressions into rewards and update the model. Idempotent.

    A 👎 that the reader took back is unlearned first: its reward goes, the model is rebuilt
    from the other rewards, and the impression is scored again without it."""
    now = _now(now)
    rc = load_reward_config(cfg)
    stats = {"impressions": 0, "rewards": 0, "weights": 0}
    with db.immediate(conn):
        dislikes = _dislike_state(conn)
        if _retract_dislikes(conn, dislikes):
            model = _relearn_in_tx(conn, cfg, rc, now)[0]
        else:
            model = Model.load(conn, cfg, now, rc)
        nmaps: dict[str, dict] = {}
        _stamp_familiarity(conn, cfg, nmaps)
        undone = {cid for cid, (on, _) in dislikes.items() if not on}
        for imp, end, end_id in _closed_impressions(conn, int(now.timestamp() * 1000), dislikes):
            row = conn.execute("SELECT spec FROM cards WHERE id = ?", (imp["card_id"],)).fetchone()
            if row is None:
                continue
            spec = json.loads(row["spec"])
            events = _window_events(conn, imp, end, end_id)
            if imp["card_id"] in undone:  # a 👎 taken back never counts
                events = [e for e in events if e[0] != "dislike"]
            try:
                out = outcome(rc, spec, events)
            except Exception:  # one odd event must not stop learning for the rest
                log.exception("could not score impression %s", imp["id"])
                conn.execute(  # weight 0: teaches nothing, and is not read again
                    "INSERT INTO rewards(card_id, impression_event_id, reward, weight, features, "
                    "computed_at) VALUES (?, ?, 0, 0, '[]', ?)",
                    (imp["card_id"], imp["id"], _iso(now)),
                )
                continue
            data = db.loads(imp["data"])
            stamped = data.get("familiarity") if isinstance(data, dict) else None
            feats = impression_features(conn, cfg, imp["card_id"], now, nmaps, stamped)
            conn.execute(
                "INSERT INTO rewards(card_id, impression_event_id, reward, weight, signal, "
                "features, computed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    imp["card_id"],
                    imp["id"],
                    out.reward,
                    out.weight,
                    out.signal,
                    json.dumps(sorted(feats)),
                    _iso(now),
                ),
            )
            conn.execute(
                "UPDATE stories SET best_reward = MAX(COALESCE(best_reward, 0), ?), "
                "liked = COALESCE(?, liked), disliked = COALESCE(?, disliked) "
                "WHERE story_key = (SELECT story_key FROM cards WHERE id = ?)",
                (
                    out.reward,
                    _last_toggle(events, "like"),
                    _last_toggle(events, "dislike"),
                    imp["card_id"],
                ),
            )
            stats["impressions"] += 1
            stats["rewards"] += 1
            if feats:
                model.update(feats, out.reward, out.weight, now)
        stats["weights"] = model.save(conn)
        knowledge.update_in_tx(conn)
    return stats


# ---------------------------------------------------------------- features


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


FAMILIAR_NEW = 0.7  # novelty at or above this: the reader is new to the code
FAMILIAR_SOME = 0.35  # at or above this: has seen some of it; below: knows it


def familiarity(novelty: float) -> str:
    """The `familiarity` feature value for a novelty in [0, 1] (knowledge model)."""
    return "new" if novelty >= FAMILIAR_NEW else "some" if novelty >= FAMILIAR_SOME else "known"


def familiarity_of(conn, cfg, repo: str | None, dirs, nmaps: dict) -> str:
    """How well the reader knows the deepest of these dirs of the repo, now. `nmaps` caches
    the repo's novelty map (repo -> map) for the caller."""
    if not repo:
        return familiarity(1.0)
    if repo not in nmaps:
        nmaps[repo] = knowledge.novelty_map(conn, repo, cfg.settings.user.git_identities)
    deepest = max(dirs, key=lambda d: (d.count("/"), d), default=None)
    nov = knowledge.lead_dir(f"{deepest}/_", nmaps[repo])[1] if deepest else 1.0
    return familiarity(nov)


def add_familiarity(conn, cfg, feats, nmaps: dict) -> None:
    """Add the impression-time `familiarity` feature to a card's feature set, in place."""
    repo = next((v for f, v in sorted(feats) if f == "repo"), None)
    dirs = [v for f, v in feats if f == "dir"]
    feats.add(("familiarity", familiarity_of(conn, cfg, repo, dirs, nmaps)))


IMPRESSION_FEATURES = ("familiarity",)  # known at the impression only, not from the card


def impression_features(
    conn, cfg, card_id: str, now: datetime, nmaps: dict, familiar: str | None = None
) -> set:
    """What the model learns from for one impression: the card's features, and how well the
    reader knew its code at that time (`familiar`, stamped on the impression; computed now
    when the impression has none)."""
    feats = set(card_features(conn, cfg, card_id, now=now))
    if feats:
        if familiar:
            feats.add(("familiarity", familiar))
        else:
            add_familiarity(conn, cfg, feats, nmaps)
    return feats


# ---------------------------------------------------------------- the model

BIAS = ("bias", "")
DEFAULT_SD = 0.5  # prior sd of a feature that reward.yaml `prior_sd` does not name
MIX_PRIOR_MAX = 0.7  # the default mix moves a prior mean by at most this (log-odds)
CROSS = "cross:"


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1 / (1 + math.exp(-z))
    e = math.exp(z)
    return e / (1 + e)


def _mix_share(cfg, feature: str, value: str) -> tuple[float, float] | None:
    """(share, mean_share) of a value within a default mix, or None if it is not in one."""
    if feature == "tone":
        mix = cfg.defaults.get("tones") or {}
        return (mix[value], sum(mix.values()) / len(mix)) if value in mix else None
    if feature in ("story_type", "format"):
        mix = cfg.defaults.get("categories") or {}
        stories, formats = _category_maps()
        table = stories if feature == "story_type" else formats
        shares = [mix[c] for c in mix if value in table.get(c, ())]
        return (sum(shares) / len(shares), sum(mix.values()) / len(mix)) if shares else None
    return None


def _category_maps() -> tuple[dict, dict]:
    from gittok import brief

    return brief.CATEGORY_STORIES, brief.CATEGORY_FORMATS


def _parse_iso(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def cross_key(a: str, b: str, va: str, vb: str) -> tuple[str, str]:
    return (f"{CROSS}{a}*{b}", f"{va}|{vb}")


class Model:
    """The one learner: Bayesian logistic regression with a diagonal Gaussian per
    (feature, value), updated online (Chapelle and Li 2011, "An Empirical Evaluation of
    Thompson Sampling"). The log-odds of the reward is the sum of the weights of the active
    features; a card's dir prefixes share one unit between them.

    The prior mean comes from the default mix, the prior sd from reward.yaml `prior_sd`.
    Evidence decays toward the prior with `half_life_days`. The stored rows are a cache:
    `relearn` rebuilds them from the rewards.
    """

    def __init__(self, cfg, rc: RewardConfig, rows: dict, now: datetime):
        self.cfg, self.rc, self.now = cfg, rc, now
        self._rows = rows  # key -> (mean, precision, n, updated_at datetime)
        self._dirty: set[tuple[str, str]] = set()

    @classmethod
    def load(cls, conn, cfg, now: datetime | None = None, rc: RewardConfig | None = None):
        rows = {
            (r["feature"], r["value"]): (
                r["mean"],
                r["precision"],
                r["n"],
                _parse_iso(r["updated_at"]),
            )
            for r in conn.execute("SELECT * FROM model_weights")
        }
        return cls(cfg, rc or load_reward_config(cfg), rows, _now(now))

    # ---- priors and state

    def prior(self, key: tuple[str, str]) -> tuple[float, float]:
        """(mean, precision) before evidence."""
        feature, value = key
        family = "cross" if feature.startswith(CROSS) else feature
        sd = float(self.rc.prior_sd.get(family, DEFAULT_SD))
        mean = 0.0
        found = _mix_share(self.cfg, feature, value)
        if found and found[1] > 0:
            ratio = max(found[0] / found[1], 0.25)
            mean = max(-MIX_PRIOR_MAX, min(MIX_PRIOR_MAX, 0.5 * math.log(ratio)))
        return mean, 1 / (sd * sd)

    def state(self, key: tuple[str, str]) -> tuple[float, float, float]:
        """(mean, precision, evidence) decayed to `now`."""
        m0, q0 = self.prior(key)
        row = self._rows.get(key)
        if row is None:
            return m0, q0, 0.0
        mean, prec, n, at = row
        days = max(0.0, (self.now - at).total_seconds() / 86400)
        k = 0.5 ** (days / self.rc.half_life_days)
        return m0 + (mean - m0) * k, q0 + (prec - q0) * k, n * k

    def expand(self, feats) -> dict[tuple[str, str], float]:
        """The active inputs of a feature set: the bias, each feature (dir prefixes share
        one unit), and the crosses of reward.yaml `crosses`."""
        feats = set(feats)
        n_dirs = sum(1 for f, _ in feats if f == "dir")
        x = {BIAS: 1.0}
        for k in feats:
            x[k] = 1 / n_dirs if k[0] == "dir" else 1.0
        values: dict[str, list[str]] = {}
        for f, v in sorted(feats):
            values.setdefault(f, []).append(v)
        for a, b in self.rc.crosses:
            for va in values.get(a, ()):
                for vb in values.get(b, ()):
                    x[cross_key(a, b, va, vb)] = 1.0
        return x

    # ---- reading

    def mean_logit(self, feats) -> float:
        return sum(self.state(k)[0] * xk for k, xk in self.expand(feats).items())

    def predict(self, feats) -> float:
        """The expected reward of a card with these features, by the posterior means."""
        return _sigmoid(self.mean_logit(feats))

    def effect(self, key: tuple[str, str]) -> float:
        """How far the evidence moved this weight from its prior mean (log-odds)."""
        return self.state(key)[0] - self.prior(key)[0]

    def values(self, feature: str) -> dict[str, tuple[float, float]]:
        """value -> (mean weight, evidence) for every stored value of the feature."""
        out = {}
        for key in self._rows:
            if key[0] == feature:
                mean, _, n = self.state(key)
                out[key[1]] = (mean, n)
        return out

    def draw(self, rng) -> Draw:
        """One Thompson sample of every weight, made lazily and the same in any call order."""
        return Draw(self, rng.getrandbits(64))

    # ---- learning

    def update(self, feats, y: float, c: float, now: datetime, drop=frozenset()) -> None:
        """One Laplace step for a soft label y in [0, 1], counted c times.

        With a diagonal prior the new mode has w_k = m_k - c (p - y) x_k / q_k, where p is the
        prediction at the mode, so only z = w . x needs solving: z = z0 - c s (p(z) - y) with
        z0 = m . x and s = sum x_k^2 / q_k. The left side minus the right is increasing in z,
        so Newton converges. Then q_k += c p (1 - p) x_k^2. `drop` names features (or crosses)
        that this update leaves out.
        """
        self.now = now
        x = {k: v for k, v in self.expand(feats).items() if k[0] not in drop}
        st = {k: self.state(k) for k in x}
        z0 = sum(st[k][0] * xk for k, xk in x.items())
        s = sum(xk * xk / st[k][1] for k, xk in x.items())
        z = z0
        for _ in range(50):
            p = _sigmoid(z)
            g = z - z0 + c * s * (p - y)
            if abs(g) < 1e-10:
                break
            z -= g / (1 + c * s * p * (1 - p))
        p = _sigmoid(z)
        r = c * (p - y)
        for k, xk in x.items():
            mean, prec, n = st[k]
            self._rows[k] = (mean - r * xk / prec, prec + c * p * (1 - p) * xk * xk, n + c, now)
            self._dirty.add(k)

    def save(self, conn) -> int:
        """Write the changed weights. Returns how many."""
        conn.executemany(
            "INSERT INTO model_weights(feature, value, mean, precision, n, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(feature, value) DO UPDATE SET "
            "mean = excluded.mean, precision = excluded.precision, n = excluded.n, "
            "updated_at = excluded.updated_at",
            [(*k, *self._rows[k][:3], _iso(self._rows[k][3])) for k in sorted(self._dirty)],
        )
        n = len(self._dirty)
        self._dirty.clear()
        return n


class Draw:
    """One Thompson sample of the model. Each weight is drawn from its posterior with a
    generator seeded by (draw seed, key), so the same draw scores the same in any order."""

    def __init__(self, model: Model, seed: int):
        self.model, self.seed = model, seed
        self._w: dict[tuple[str, str], float] = {}

    def weight(self, key: tuple[str, str]) -> float:
        if key not in self._w:
            mean, prec, _ = self.model.state(key)
            rng = random.Random(f"{self.seed}:{key[0]}:{key[1]}")
            self._w[key] = rng.gauss(mean, 1 / math.sqrt(prec))
        return self._w[key]

    def logit(self, feats) -> float:
        return sum(self.weight(k) * xk for k, xk in self.model.expand(feats).items())

    def score(self, feats) -> float:
        """The sampled expected reward, in (0, 1)."""
        return _sigmoid(self.logit(feats))


def _replay_features(conn, cfg, r, at: datetime) -> set:
    """The features to learn a stored reward from again: the card's current ones (so a change
    to how features are derived applies) with the impression-time ones of the snapshot, or the
    snapshot alone when the card is gone."""
    snap = {tuple(k) for k in json.loads(r["features"] or "[]")}
    feats = set(card_features(conn, cfg, r["card_id"], now=at)) if r["card_id"] else set()
    if not feats:
        return snap
    return feats | {k for k in snap if k[0] in IMPRESSION_FEATURES}


def _relearn_in_tx(conn, cfg, rc: RewardConfig, now: datetime) -> tuple[Model, int]:
    model = Model(cfg, rc, {}, now)
    resets = conn.execute("SELECT feature, at FROM model_resets ORDER BY at").fetchall()
    replayed = 0
    conn.execute("DELETE FROM model_weights")
    for r in conn.execute(
        "SELECT * FROM rewards WHERE weight > 0 ORDER BY computed_at, id"
    ).fetchall():
        later = [x["feature"] for x in resets if x["at"] > r["computed_at"]]
        if None in later:  # every weight was reset after this reward
            continue
        at = _parse_iso(r["computed_at"])
        feats = _replay_features(conn, cfg, r, at)
        if not feats:
            continue
        model.update(feats, r["reward"], r["weight"], at, drop=frozenset(later))
        replayed += 1
    model.now = now
    model.save(conn)
    return model, replayed


def relearn(conn, cfg, now: datetime | None = None) -> int:
    """Rebuild the model from every reward, oldest first, with the cards' current features
    and the familiarity saved at the impression (the saved snapshot alone for a card that is
    gone). A reset (`reset_weights`) stays: what it removed is not learned again from older
    rewards. Returns the number of rewards replayed. Run it after a change to the features
    or the priors."""
    rc = load_reward_config(cfg)
    with db.immediate(conn):
        return _relearn_in_tx(conn, cfg, rc, _now(now))[1]


def score_cards(
    conn, cfg, card_ids: list[str], rng, now: datetime | None = None, feats=None
) -> dict[str, float]:
    """One Thompson draw per call, shared by all cards: id -> sampled expected reward.

    `feats` (card id -> features, as `slotter.features_for` gives them) saves the reads per
    card when the caller already has them. Reads only.
    """
    now = _now(now)
    if feats is None:
        feats = {cid: set(card_features(conn, cfg, cid, now=now)) for cid in card_ids}
    draw = Model.load(conn, cfg, now).draw(rng)
    return {cid: draw.score(f) for cid in card_ids if (f := feats.get(cid))}


def posterior_means(
    conn, cfg, feature: str, now: datetime | None = None
) -> dict[str, tuple[float, float]]:
    """value -> (expected reward of an average card with this value, evidence) for every
    learned value of the feature. Reads only."""
    model = Model.load(conn, cfg, now)
    bias = model.state(BIAS)[0]
    return {v: (_sigmoid(bias + m), n) for v, (m, n) in model.values(feature).items()}


# ---------------------------------------------------------------- category shares

SHARE_FLOOR = 0.05


def _effects(model: Model, feature: str) -> dict[str, tuple[float, float]]:
    """value -> (effect of the evidence in log-odds, evidence) for values with evidence."""
    return {
        v: (model.effect((feature, v)), n)
        for v, (_, n) in model.values(feature).items()
        if n > 1e-9
    }


FACTOR_MAX = 4.0  # a learned factor stays within [1/FACTOR_MAX, FACTOR_MAX]


def value_factors(
    conn, cfg, feature: str, now: datetime | None = None, model: Model | None = None
) -> dict[str, float]:
    """Learned factor per value of a feature, for the brief: exp(effect - mean effect) over
    the values with evidence, clamped to [1/FACTOR_MAX, FACTOR_MAX]. Values without evidence
    are absent, which counts as 1. The brief scales its tone mix, persona share, repo share,
    asked levels and format order with these."""
    stats = _effects(model or Model.load(conn, cfg, now), feature)
    if not stats:
        return {}
    ref = sum(e for e, _ in stats.values()) / len(stats)
    return {
        v: min(FACTOR_MAX, max(1 / FACTOR_MAX, math.exp(e - ref))) for v, (e, _) in stats.items()
    }


def format_factors(conn, cfg, now: datetime | None = None, model=None) -> dict[str, float]:
    """`value_factors` of the formats: the brief's format pick."""
    return value_factors(conn, cfg, "format", now, model)


def category_shares(conn, cfg, now: datetime | None = None, model=None) -> dict[str, float]:
    """Learned share per default-mix category: the default share times exp(effect_c - ref).

    effect_c is the evidence-weighted mean effect of the category's story types and formats
    (the movement of their weights away from the prior, so the mix does not count twice); ref
    is the plain mean over categories with evidence. With no evidence the shares equal the
    default mix. After normalising, no category goes below 0.05; clamped categories are fixed
    at 0.05 and the rest are rescaled to fill the remainder.
    """
    mix = {k: float(v) for k, v in (cfg.defaults.get("categories") or {}).items()}
    if not mix:
        return {}
    model = model or Model.load(conn, cfg, now)
    stories, formats = _category_maps()
    evidence = {("story_type", v): e for v, e in _effects(model, "story_type").items()}
    evidence |= {("format", v): e for v, e in _effects(model, "format").items()}
    stats: dict[str, float] = {}
    for c in mix:
        hits = [
            evidence[(f, v)]
            for f, vs in (("story_type", stories.get(c, ())), ("format", formats.get(c, ())))
            for v in vs
            if (f, v) in evidence
        ]
        total = sum(n for _, n in hits)
        if total > 0:
            stats[c] = sum(e * n for e, n in hits) / total
    ref = sum(stats.values()) / len(stats) if stats else 0.0
    raw = {c: share * math.exp(stats[c] - ref) if c in stats else share for c, share in mix.items()}
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


def reset_weights(conn, feature: str | None = None, now: datetime | None = None) -> int:
    """Delete learned weights (all, or one feature), and note the reset so that `relearn`
    keeps it. Returns the number of rows deleted."""
    with conn:
        if feature is None:
            cur = conn.execute("DELETE FROM model_weights")
        else:
            cur = conn.execute("DELETE FROM model_weights WHERE feature = ?", (feature,))
        conn.execute(
            "INSERT INTO model_resets(feature, at) VALUES (?, ?)", (feature, _iso(_now(now)))
        )
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
                with closing(db.open_db(cfg.settings.data_dir / "gittok.db")) as conn:
                    process_events(conn, cfg)
            except Exception:
                log.exception("learning pass failed")
            self._stop.wait(self._interval)

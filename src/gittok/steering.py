"""Steering: rules, explanations, profile data, and config edits for an agent (SPEC §14, §15).

Every function returns JSON-serializable dicts or lists. Errors are `SteeringError` with a
short message an agent can act on.
"""

from __future__ import annotations

import difflib
import fcntl
import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import zlib
from contextlib import closing
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path

import yaml

from gittok import (
    brief,
    db,
    gc,
    gitq,
    knowledge,
    learning,
    private,
    profiles,
    rule_stats,
    signals,
    social,
)
from gittok import config as config_mod
from gittok.config import load_config, unknown_repo

log = logging.getLogger(__name__)


class SteeringError(Exception):
    """A problem the caller can fix; the message is shown to an agent."""


RULE_TYPES = ("boost", "focus", "limit", "prefer")
FEATURES = (
    "story_type",
    "format",
    "persona",
    "tone",
    "repo",
    "group",
    "dir",
    "visual_kind",
    "template",
    "recency",
    "angle",
    "file",
    "language",
    "kind",
    "tag",
    "familiarity",
    "has_comments",
    "interactive",
    "verdict",
)
FREE_VALUES = ("file", "tag")  # any value: a path, a detector tag


DEFAULT_FACTOR = {"boost": 2.0, "prefer": 1.5}


def _now(now: datetime | None) -> datetime:
    return (now or datetime.now(UTC)).astimezone(UTC)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _rule_dict(row) -> dict:
    return {k: row[k] for k in row.keys()}


def _schema() -> dict:
    return json.loads((files("gittok") / "schema" / "card.schema.json").read_text())


def _schema_values() -> dict[str, list[str]]:
    """Enum-like values taken from the card schema."""
    defs = _schema()["$defs"]
    props = defs["card"]["properties"]
    kinds = [
        defs[ref["$ref"].rsplit("/", 1)[1]]["properties"]["kind"]["const"]
        for ref in props["visual"]["oneOf"]
    ]
    return {
        "story_type": props["story_type"]["enum"],
        "format": props["format"]["enum"],
        "tone": props["tone"]["enum"],
        "verdict": props["verdict"]["enum"],
        "visual_kind": kinds,
        "template": defs["template_visual"]["properties"]["template"]["enum"],
        "angle": props["angle"]["enum"],
    }  # fmt: skip


def _known_dir(cfg, value: str) -> str | None:
    """The dir name if it exists at the ref of a configured repo ('repo/dir' or 'dir')."""
    value = value.strip().strip("/")
    first, _, rest = value.partition("/")
    options = [(cfg.repos[first], rest)] if first in cfg.repos and rest else []
    options += [(r, value) for r in cfg.repos.values()]
    for repo, path in options:
        try:
            if path and gitq.object_type(repo.path, repo.ref, path) == "tree":
                return path
        except gitq.GitError:
            continue
    return None


def _bad_value(feature: str, value: str, known: list[str]) -> SteeringError:
    close = difflib.get_close_matches(value, known, n=1)
    hint = f" Did you mean '{close[0]}'?" if close else ""
    shown = ", ".join(known[:25]) + (", ..." if len(known) > 25 else "")
    return SteeringError(f"Unknown {feature} '{value}'.{hint} Known: {shown or 'none'}.")


def _check_value(cfg, feature: str, value) -> str:
    """Return the value to store, or raise with the known values."""
    value = str(value).strip()
    if feature == "dir":
        found = _known_dir(cfg, value)
        if found is None:
            raise SteeringError(
                f"Unknown dir '{value}'. It must be a directory at the ref of a configured "
                "repo. Use 'dir' or 'repo/dir'. Check `coverage` for real names."
            )
        return found
    if feature == "has_comments":
        yes, no = {"1", "true", "yes"}, {"0", "false", "no"}
        if value.lower() in yes | no:
            return "1" if value.lower() in yes else "0"
        raise _bad_value(feature, value, ["1", "0"])
    if feature in FREE_VALUES:
        if not value:
            raise SteeringError(f"A {feature} rule needs a value.")
        return value.strip("/") if feature == "file" else value
    known = {
        **_schema_values(),
        "persona": list(cfg.personas),
        "repo": list(cfg.repos),
        "group": list(cfg.groups),
        "recency": ["new", "recent", "old"],
        "language": sorted(set(config_mod.language_by_extension().values())),
        "kind": [*profiles.KIND_ORDER, "source"],
        "familiarity": ["new", "some", "known"],
        "interactive": list(brief.CATEGORY_STORIES["interactive"]),
    }[feature]
    if value not in known:
        raise _bad_value(feature, value, list(known))
    return value


_RELATIVE = re.compile(r"(\d+)\s*([hdw])", re.IGNORECASE)
_UNIT = {"h": timedelta(hours=1), "d": timedelta(days=1), "w": timedelta(weeks=1)}


def _expiry(expires, now: datetime) -> str | None:
    """ISO date or datetime, or relative like '7d' / '2w' / '12h', as an ISO UTC string."""
    if expires is None or expires == "":
        return None
    text = str(expires).strip()
    when = None
    if m := _RELATIVE.fullmatch(text):
        if int(m[1]) > 0:
            when = now + int(m[1]) * _UNIT[m[2].lower()]
    else:
        try:
            if len(text) == 10:
                when = datetime.fromisoformat(text).replace(
                    hour=23, minute=59, second=59, tzinfo=UTC
                )
            else:
                when = datetime.fromisoformat(text.replace("Z", "+00:00"))
                when = when.replace(tzinfo=when.tzinfo or UTC)
        except ValueError:
            when = None
    if when is None or when.astimezone(UTC) <= now:
        raise SteeringError(
            f"Bad expires '{text}'. Use a future date (2026-11-06) or a length like 7d, 2w, 12h."
        )
    return _iso(when.astimezone(UTC))


def _params(type, factor, slots, max_share):
    """Keep only the numbers the rule type uses; check them."""
    if type in DEFAULT_FACTOR:
        factor = DEFAULT_FACTOR[type] if factor is None else factor
        if not isinstance(factor, int | float) or factor <= 0:
            raise SteeringError("factor must be a number above 0 (2.0 doubles the score).")
        return float(factor), None, None
    if type == "focus":
        if not isinstance(slots, int) or isinstance(slots, bool) or not 1 <= slots <= 10:
            raise SteeringError("A focus rule needs slots: a whole number from 1 to 10 per batch.")
        return None, slots, None
    if type == "limit":
        if not isinstance(max_share, int | float) or not 0 <= max_share <= 1:
            raise SteeringError("A limit rule needs max_share: a number from 0 to 1.")
        return None, None, max_share
    return None, None, None


def add_rule(
    conn,
    cfg,
    *,
    type,
    feature,
    value,
    factor=None,
    slots=None,
    max_share=None,
    expires=None,
    created_by="agent",
    reason="",
    now=None,
) -> dict:
    """Store a steering rule. The brief reads the `rules` table for each run: rules shape the
    mix of the cards that get made, not the order of the feed."""
    if type == "ban":
        raise SteeringError(
            "There is no ban rule. For 'never make X' use type='limit' with max_share=0 (on "
            "format, story_type, repo or tone). For anything else (a subject, a style, a dir "
            "to leave alone), write it in local/guidance.md: every card writer reads it."
        )
    if type not in RULE_TYPES:
        raise SteeringError(f"Unknown type '{type}'. Use one of: {', '.join(RULE_TYPES)}.")
    if feature not in FEATURES:
        raise SteeringError(f"Unknown feature '{feature}'. Use one of: {', '.join(FEATURES)}.")
    value = _check_value(cfg, feature, value)
    factor, slots, max_share = _params(type, factor, slots, max_share)
    now = _now(now)
    expires_at = _expiry(expires, now)
    with conn:
        cur = conn.execute(
            "INSERT INTO rules(type, feature, value, factor, slots, max_share, expires_at, "
            "created_by, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (type, feature, value, factor, slots, max_share, expires_at, created_by, reason,
             _iso(now)),
        )  # fmt: skip
    return _rule_dict(conn.execute("SELECT * FROM rules WHERE id = ?", (cur.lastrowid,)).fetchone())


def list_rules(conn, include_expired: bool = False, now: datetime | None = None) -> list[dict]:
    """Rules by id. Each has `expired`; expired rules are hidden unless `include_expired`."""
    iso = _iso(_now(now))
    out = []
    for row in conn.execute("SELECT * FROM rules ORDER BY id"):
        rule = _rule_dict(row)
        rule["expired"] = rule["expires_at"] is not None and rule["expires_at"] <= iso
        if include_expired or not rule["expired"]:
            out.append(rule)
    return out


def remove_rule(conn, rule_id) -> dict:
    row = conn.execute("SELECT * FROM rules WHERE id = ?", (rule_id,)).fetchone()
    if row is None:
        raise SteeringError(f"No rule with id {rule_id}. Call list_rules to see current ids.")
    with conn:
        conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
    return {"removed": True, "rule": _rule_dict(row)}


# ---------------------------------------------------------------- weights

HIT_REWARD = 0.5
RECENT_DAYS = 7
BEFORE_DAYS = 21
TREND_MIN = 3  # rewards needed in each window to call a trend
TREND_DELTA = 0.1


def _reward_rows(conn, cfg, now: datetime):
    """(card_id, reward, age_in_days) for each reward, newest data from the impression event."""
    rows = conn.execute(
        "SELECT r.card_id, r.reward, r.computed_at, e.ts FROM rewards r "
        "LEFT JOIN events e ON e.id = r.impression_event_id "
        "JOIN cards c ON c.id = r.card_id"
    ).fetchall()
    for r in rows:
        if r["ts"] is not None:
            when = datetime.fromtimestamp(r["ts"] / 1000, UTC)
        else:
            when = learning._parse_iso(r["computed_at"])
        yield r["card_id"], r["reward"], (now - when).total_seconds() / 86400


def _trend(ages_and_rewards: list[tuple[float, float]]) -> str:
    recent = [r for age, r in ages_and_rewards if 0 <= age < RECENT_DAYS]
    before = [r for age, r in ages_and_rewards if RECENT_DAYS <= age < RECENT_DAYS + BEFORE_DAYS]
    if len(recent) < TREND_MIN or len(before) < TREND_MIN:
        return "unknown"
    delta = sum(recent) / len(recent) - sum(before) / len(before)
    return "up" if delta > TREND_DELTA else "down" if delta < -TREND_DELTA else "flat"


def explain_weights(
    conn, cfg, feature: str | None = None, now: datetime | None = None
) -> list[dict]:
    """Per (feature, value): learned mean, evidence, impressions, hit rate, and 7-day trend.

    `hit_rate` is the share of rewards >= 0.5 (a blend of dwell, likes, and saves).
    `trend` compares the mean reward of the last 7 days with the 21 days before
    (needs 3 rewards in each; else "unknown").
    Sorted by feature, then mean (best first).
    """
    if feature is not None and feature not in FEATURES:
        raise SteeringError(f"Unknown feature '{feature}'. Use one of: {', '.join(FEATURES)}.")
    now = _now(now)
    wanted = [feature] if feature else list(FEATURES)
    seen: dict[tuple[str, str], list[tuple[float, float]]] = {}
    features: dict[str, list[tuple[str, str]]] = {}
    for card_id, value, age in _reward_rows(conn, cfg, now):
        if card_id not in features:
            features[card_id] = learning.card_features(conn, cfg, card_id, now=now)
        for key in features[card_id]:
            if key[0] in wanted:
                seen.setdefault(key, []).append((age, value))
    out = []
    for f in wanted:
        for value, (mean, n) in learning.posterior_means(conn, cfg, f, now=now).items():
            history = seen.get((f, value), [])
            hits = sum(r >= HIT_REWARD for _, r in history)
            out.append(
                {
                    "feature": f,
                    "value": value,
                    "mean": round(mean, 4),
                    "n": round(n, 2),
                    "impressions": len(history),
                    "hit_rate": round(hits / len(history), 4) if history else None,
                    "trend": _trend(history),
                }
            )
    out.sort(key=lambda r: (r["feature"], -r["mean"], r["value"]))
    return out


# ---------------------------------------------------------------- profile

MIN_CLAIM_N = 5
RULE_OUTCOME_ROWS = 5  # rules per repo in get_profile
MAX_SENTENCES = 8
_NOUN = {
    "story_type": "{} cards",
    "format": "{} cards",
    "tone": "{} cards",
    "persona": "cards by {}",
    "repo": "cards about {}",
    "group": "cards about the {} group",
    "dir": "cards about {}/",
    "visual_kind": "{} visuals",
    "template": "{} templates",
    "recency": "{} cards",
    "angle": "'{}' cards",
    "file": "cards about {}",
    "language": "{} cards",
    "kind": "{} code cards",
    "tag": "{} cards",
    "familiarity": "cards about code you {}",
    "has_comments": "cards with comments",
    "interactive": "{} quiz cards",
    "verdict": "{} code cards",
}
_ENDING = {
    "up": ", trending up.",
    "down": ", trending down.",
    "flat": ", holding steady.",
    "unknown": ".",
}


def _sentence(row: dict) -> str:
    noun = _NOUN[row["feature"]].format(row["value"])
    if row["feature"] == "has_comments" and row["value"] == "0":
        noun = "cards without comments"
    pct = round(row["hit_rate"] * 100)
    return (
        f"You engaged with {noun}: average score {row['mean']:.2f}, and {pct}% scored well, "
        f"over {row['impressions']} views{_ENDING[row['trend']]}"
    )


def _claim(row: dict) -> dict:
    keys = ("value", "mean", "n", "impressions", "hit_rate", "trend")
    return {k: row[k] for k in keys}


def get_profile(conn, cfg, now: datetime | None = None) -> dict:
    """Plain-English taste profile. Only values with at least 5 views make claims.

    Top and bottom are ranked by the learned mean, the same number each sentence quotes.
    """
    now = _now(now)
    evidence = conn.execute("SELECT COUNT(*) FROM rewards").fetchone()[0]
    rows = [
        r
        for r in explain_weights(conn, cfg, now=now)
        if r["impressions"] >= MIN_CLAIM_N and r["hit_rate"] is not None
    ]
    by_feature: dict[str, list[dict]] = {}
    for r in rows:
        by_feature.setdefault(r["feature"], []).append(r)
    top, bottom, claims = {}, {}, []
    for feature, group in by_feature.items():
        if len(group) < 2:
            continue
        best, worst = group[0], group[-1]  # explain_weights sorts best first
        top[feature], bottom[feature] = _claim(best), _claim(worst)
        claims += [best, worst]
    claims.sort(key=lambda r: -abs(r["mean"] - 0.5))
    summary = [_sentence(r) for r in claims[:MAX_SENTENCES]]
    if not summary:
        summary = [f"Not enough data yet: {evidence} views so far. Keep scrolling and check back."]
    return {
        "summary": summary,
        "top": top,
        "bottom": bottom,
        "rules": list_rules(conn, now=now),
        "evidence": evidence,
        "knowledge": knowledge.knowledge_rows(conn, cfg),
        "rule_outcomes": {
            repo: rows[:RULE_OUTCOME_ROWS]
            for repo in cfg.repos
            if (rows := rule_stats.rollup(conn, repo))
        },
    }


# ---------------------------------------------------------------- coverage and cards


def _top_level(path: str) -> str | None:
    top = path.strip("/").split("/")[0]
    return None if top in ("", ".") else top


def _repo_top_dirs(conn, repo) -> set[str]:
    """Top-level dirs of a repo: from the latest churn signal and from the tree at its ref."""
    found: set[str] = set()
    churn = (signals.load_signals(conn, repo.name) or {}).get("churn") or {}
    for rows in (churn.get("dirs") or {}).values():
        found |= {t for r in rows if (t := _top_level(r["path"]))}
    try:
        tree = gitq.run(repo.path, "ls-tree", "--name-only", "-d", repo.ref)
    except gitq.GitError:
        tree = ""
    return found | {ln for ln in tree.splitlines() if ln}


def coverage(conn, cfg, repo: str | None = None) -> list[dict]:
    """Per repo and top-level dir: depth, impressions, cards, last_seen, and the ledger leads
    under it (`leads` now at HEAD, `leads_covered` of them with a card). Least covered first.

    A card has a `dir` feature per path prefix; each card counts once per top-level dir.
    """
    if repo is not None and repo not in cfg.repos:
        raise SteeringError(unknown_repo(cfg.repos, repo))
    out = []
    for name in [repo] if repo else list(cfg.repos):
        known = knowledge.novelty_map(conn, name, cfg.settings.user.git_identities)
        stats: dict[str, dict] = {}
        for row in conn.execute(
            "SELECT d.value AS dir, c.id AS card_id, "
            "COUNT(e.id) AS n, MAX(e.ts) AS last FROM cards c "
            "JOIN card_features r ON r.card_id = c.id AND r.feature = 'repo' AND r.value = ? "
            "JOIN card_features d ON d.card_id = c.id AND d.feature = 'dir' "
            "LEFT JOIN events e ON e.card_id = c.id AND e.type = 'impression' "
            "GROUP BY d.value, c.id",
            (name,),
        ):
            top = _top_level(row["dir"])
            if top is None:
                continue
            s = stats.setdefault(top, {"impressions": 0, "cards": set(), "last": None})
            if row["card_id"] in s["cards"]:
                continue  # another prefix of the same card
            s["impressions"] += row["n"]
            s["cards"].add(row["card_id"])
            if row["last"] is not None:
                s["last"] = max(s["last"] or 0, row["last"])
        # Current leads per top dir. A file counts once, however many story types offer it.
        lead_n: dict[str, list[int]] = {}
        for lead in conn.execute(
            "SELECT path, MAX(times_covered) AS covered FROM leads WHERE repo = ? AND path != '' "
            "AND last_seen_at = (SELECT MAX(last_seen_at) FROM leads WHERE repo = ?) "
            "GROUP BY path",
            (name, name),
        ):
            top = _top_level(lead["path"]) if "/" in lead["path"] else None
            if top:
                n = lead_n.setdefault(top, [0, 0])
                n[0] += 1
                n[1] += lead["covered"] > 0
        for top in sorted(_repo_top_dirs(conn, cfg.repos[name]) | set(stats) | set(lead_n)):
            s = stats.get(top) or {"impressions": 0, "cards": set(), "last": None}
            last = (
                None if s["last"] is None else _iso(datetime.fromtimestamp(s["last"] / 1000, UTC))
            )
            out.append(
                {
                    "repo": name,
                    "dir": top,
                    "depth": len(top.split("/")),
                    "impressions": s["impressions"],
                    "cards": len(s["cards"]),
                    "last_seen": last,
                    "leads": lead_n.get(top, [0, 0])[0],
                    "leads_covered": lead_n.get(top, [0, 0])[1],
                    "novelty": known.get(top, 1.0),
                }
            )
    out.sort(key=lambda r: (r["impressions"], r["cards"], r["repo"], r["dir"]))
    return out


def _group_of(cfg, repo: str) -> str | None:
    return cfg.repos[repo].group if cfg is not None and repo in cfg.repos else None


def recent_cards(conn, limit: int = 20, repo: str | None = None, cfg=None) -> list[dict]:
    """Newest cards first, with their repo, how often they were shown and the mean reward.
    `repo` keeps only the cards of that repo. `cfg` gives each row its repo's group."""
    if repo is not None and cfg is not None and repo not in cfg.repos:
        raise SteeringError(unknown_repo(cfg.repos, repo))
    rows = conn.execute(
        "SELECT c.id, c.created_at, c.story_type, c.format, c.status, c.spec, p.name AS repo, "
        "(SELECT COUNT(*) FROM events e WHERE e.card_id = c.id AND e.type = 'impression') AS imps, "
        "(SELECT AVG(r.reward) FROM rewards r WHERE r.card_id = c.id) AS mean_reward "
        "FROM cards c JOIN repos p ON p.id = c.repo_id WHERE (? IS NULL OR p.name = ?) "
        "ORDER BY c.created_at DESC, c.id DESC LIMIT ?",
        (repo, repo, max(0, int(limit))),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "repo": r["repo"],
            "group": _group_of(cfg, r["repo"]),
            "created_at": r["created_at"],
            "story_type": r["story_type"],
            "format": r["format"],
            "hook": json.loads(r["spec"]).get("hook", ""),
            "status": r["status"],
            "impressions": r["imps"],
            "mean_reward": None if r["mean_reward"] is None else round(r["mean_reward"], 4),
        }
        for r in rows
    ]


def card_stats(conn, card_id: str, cfg=None) -> dict:
    """Repo, events by type, dwell time, rewards, and answers for one card."""
    card = conn.execute(
        "SELECT p.name AS repo FROM cards c JOIN repos p ON p.id = c.repo_id WHERE c.id = ?",
        (card_id,),
    ).fetchone()
    if card is None:
        raise SteeringError(f"No card with id '{card_id}'. Call recent_cards for ids.")
    events: dict[str, int] = {}
    dwell: list[int] = []
    answers = []
    for e in conn.execute(
        "SELECT type, ts, data FROM events WHERE card_id = ? ORDER BY ts, id", (card_id,)
    ):
        events[e["type"]] = events.get(e["type"], 0) + 1
        data = json.loads(e["data"] or "{}")
        if e["type"] == "dwell":
            dwell.append(int(data.get("ms", 0)))
        elif e["type"] == "answer":
            answers.append(
                {"choice": data.get("choice"), "correct": data.get("correct"), "ts": e["ts"]}
            )
    rewards = [
        r[0]
        for r in conn.execute(
            "SELECT reward FROM rewards WHERE card_id = ? ORDER BY id", (card_id,)
        )
    ]
    return {
        "card_id": card_id,
        "repo": card["repo"],
        "group": _group_of(cfg, card["repo"]),
        "events": dict(sorted(events.items())),
        "dwell_ms": {
            "total": sum(dwell),
            "mean": round(sum(dwell) / len(dwell), 1) if dwell else 0.0,
        },
        "rewards": rewards,
        "mean_reward": round(sum(rewards) / len(rewards), 4) if rewards else None,
        "answers": answers,
    }


def reset_defaults(conn, feature: str | None = None) -> dict:
    """Forget learned weights (all, or one feature) so the shipped priors apply again."""
    if feature is not None and feature not in FEATURES:
        raise SteeringError(f"Unknown feature '{feature}'. Use one of: {', '.join(FEATURES)}.")
    return {"deleted": learning.reset_weights(conn, feature)}


# ---------------------------------------------------------------- config edits
#
# Config files are edited as text so comments and other entries stay as they are. The helpers
# below know only the shape of config/*.yaml: a top-level section holding named entries, each a
# block of `key: value` lines. Inline forms such as `name: {path: x}` are refused.

_NAME = re.compile(r"[A-Za-z0-9_-]+")
_PLAIN = re.compile(r"[A-Za-z_/][A-Za-z0-9_./-]*")
_RESERVED = {"y", "n", "yes", "no", "true", "false", "on", "off", "null", "~"}


class _Raw(str):
    """Text written to the file as it is (for flow lists)."""


def _scalar(value) -> str:
    if isinstance(value, _Raw):
        return str(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    value = str(value)
    if _PLAIN.fullmatch(value) and value.lower() not in _RESERVED:
        return value
    return json.dumps(value, ensure_ascii=False)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _skippable(line: str) -> bool:
    s = line.strip()
    return not s or s.startswith("#")


def _key_re(key: str) -> re.Pattern:
    return re.compile(rf"^(\s*)(?:{re.escape(key)}|\"{re.escape(key)}\"|'{re.escape(key)}'):(.*)$")


def _block_end(lines: list[str], start: int, end: int) -> int:
    """End (exclusive) of the block whose key line is `start`, trailing comments excluded."""
    indent = _indent(lines[start])
    i = start + 1
    while i < end and (_skippable(lines[i]) or _indent(lines[i]) > indent):
        i += 1
    while i > start + 1 and _skippable(lines[i - 1]):
        i -= 1
    return i


def _find(lines: list[str], key: str, lo: int, hi: int, indent: int | None):
    """(start, end) of child `key` in lines[lo:hi]; children sit at `indent` (first one found)."""
    pattern = _key_re(key)
    for i in range(lo, hi):
        if _skippable(lines[i]):
            continue
        if indent is None:
            indent = _indent(lines[i])
        if _indent(lines[i]) != indent:
            continue
        m = pattern.match(lines[i])
        if m:
            return i, _block_end(lines, i, hi)
    return None


def _child_indent(lines: list[str], lo: int, hi: int, default: int) -> int:
    for i in range(lo, hi):
        if not _skippable(lines[i]):
            return _indent(lines[i])
    return default


def _no_inline(line: str, name: str) -> None:
    value = line.split(":", 1)[1].split(" #")[0].strip()
    if value:
        raise SteeringError(f"'{name}' is written inline in the config. Edit the file by hand.")


def _entry(lines: list[str], section: str, name: str, create: bool):
    """(start, end) of entry `name` under top-level `section`, creating either if asked."""
    sec = _find(lines, section, 0, len(lines), 0)
    if sec is None:
        if not create:
            return None
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"{section}:")
        sec = (len(lines) - 1, len(lines))
    _no_inline(lines[sec[0]], section)
    found = _find(lines, name, sec[0] + 1, sec[1], None)
    if found is None and create:
        ind = _child_indent(lines, sec[0] + 1, sec[1], 2)
        lines.insert(sec[1], f"{' ' * ind}{name}:")
        found = (sec[1], sec[1] + 1)
    if found:
        _no_inline(lines[found[0]], name)
    return found


def _set_fields(lines: list[str], section: str, name: str, fields: dict) -> None:
    """Set (or with None, remove) fields of an entry. Other lines and comments stay."""
    start, end = _entry(lines, section, name, create=True)
    fi = _child_indent(lines, start + 1, end, _indent(lines[start]) + 2)
    for key, value in fields.items():
        found = _find(lines, key, start + 1, end, fi)
        if value is None:
            if found:
                del lines[found[0] : found[1]]
                end -= found[1] - found[0]
            continue
        text = _scalar(value)
        if found:
            i = found[0]
            m = re.match(r"^(\s*[^:]+:\s*)(.*?)(\s+#.*)?$", lines[i])
            lines[i : found[1]] = [f"{m[1].rstrip()} {text}{m[3] or ''}"]
            end -= found[1] - found[0] - 1
        else:
            lines.insert(end, f"{' ' * fi}{key}: {text}")
            end += 1


def _drop_from_groups(lines: list[str], repo: str, keep: str | None) -> None:
    """Remove `repo` from every group's `repos` list, except the group `keep`."""
    sec = _find(lines, "groups", 0, len(lines), 0)
    if sec is None:
        return
    gi = _child_indent(lines, sec[0] + 1, sec[1], 2)
    for gname in [
        m[2]
        for ln in lines[sec[0] + 1 : sec[1]]
        if (m := re.match(rf"^(\s{{{gi}}})([\w-]+):\s*$", ln))
    ]:
        if gname == keep:
            continue
        entry = _entry(lines, "groups", gname, create=False)
        field = _find(lines, "repos", entry[0] + 1, entry[1], None)
        if field is None:
            continue
        i = field[0]
        flow = re.match(r"^(\s*repos:\s*)\[(.*?)\](\s+#.*)?\s*$", lines[i])
        if flow:
            names = [n.strip().strip("'\"") for n in flow[2].split(",") if n.strip()]
            if repo in names:
                names.remove(repo)
                lines[i] = f"{flow[1]}[{', '.join(names)}]{flow[3] or ''}"
        else:  # block list
            j = field[1] - 1
            while j > i:
                if re.fullmatch(rf"\s*-\s*['\"]?{re.escape(repo)}['\"]?\s*(#.*)?", lines[j]):
                    del lines[j]
                j -= 1


def _group_edit(lines: list[str], cfg, repo: str, group: str | None) -> None:
    if (
        group is not None
        and group not in cfg.groups
        and _entry(lines, "groups", group, False) is None
    ):
        _set_fields(lines, "groups", group, {"repos": _Raw("[]")})
    _drop_from_groups(lines, repo, group)
    _set_fields(lines, "repos", repo, {"group": group})


_EDIT_LOCK = threading.Lock()


def _write_atomic(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _edit_files(cfg, edits: dict) -> None:
    """Apply `{file: fn(lines)}`, reload the config to validate, restore all files on failure.

    Edits run one at a time (a thread lock plus a file lock) and every write is a temp file
    followed by `os.replace`.
    """
    root = cfg.root / "local"
    root.mkdir(parents=True, exist_ok=True)
    with _EDIT_LOCK, open(root / ".edit.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            _edit_locked(cfg, root, edits)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _edit_locked(cfg, root: Path, edits: dict) -> None:
    original = {
        f: (root / f).read_text(encoding="utf-8") if (root / f).is_file() else None for f in edits
    }
    try:
        for f, fn in edits.items():
            lines = (original[f] or "").splitlines()
            fn(lines)
            _write_atomic(root / f, "\n".join(lines) + "\n")
        load_config(cfg.root, cfg.shared)
    except BaseException as e:
        for f, old in original.items():
            if old is None:
                (root / f).unlink(missing_ok=True)
            else:
                _write_atomic(root / f, old)
        if isinstance(e, SteeringError) or not isinstance(e, Exception):
            raise
        raise SteeringError(f"Config change rejected and undone: {e}") from e


def _audit(cfg, tool: str, args: dict, created_by: str) -> None:
    """Append one JSON line per config edit to <data_dir>/config_audit.log."""
    entry = {
        "timestamp": _iso(_now(None)),
        "tool": tool,
        "args": args,
        "created_by": created_by,
    }
    try:
        log = cfg.settings.data_dir / "config_audit.log"
        private.make_dir(log.parent)
        with open(log, "a", encoding="utf-8", opener=private.opener) as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass  # the edit is done; a full disk must not undo or hide it


MAX_NAME, MAX_VOICE, MAX_STYLE = 60, 200, 300
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]+")
_INSTRUCTION = re.compile(
    r"\bignor\w*|\binstructions?\b|system\s+prompt|\btools?\b|\bcall\b|\bmcp\b", re.IGNORECASE
)


def _check_text(kind: str, value, limit: int) -> str:
    """Free text that reaches agent prompts: one clean line, short, and without commands."""
    if not isinstance(value, str):
        raise SteeringError(f"{kind} must be text.")
    clean = " ".join(_CONTROL.sub(" ", value).split())
    if len(clean) > limit:
        raise SteeringError(f"{kind} is too long: {len(clean)} characters, the limit is {limit}.")
    if m := _INSTRUCTION.search(clean):
        raise SteeringError(
            f"{kind} contains '{m[0]}'. It must describe a style or voice, not give orders to "
            "an agent. Rewrite it, or edit the config file by hand."
        )
    return clean


def _check_name(kind: str, name: str) -> str:
    if not isinstance(name, str) or not _NAME.fullmatch(name) or not _loads_as_same_text(name):
        raise SteeringError(
            f"Bad {kind} '{name}'. Use letters, digits, '_' and '-', and not a word YAML "
            "reads as a number, yes/no, or null."
        )
    return name


def _loads_as_same_text(name: str) -> bool:
    try:
        loaded = yaml.safe_load(name)
    except yaml.YAMLError:
        return False
    return type(loaded) is str and loaded == name and name.lower() not in _RESERVED


def set_group(cfg, repo: str, group: str | None, created_by: str = "agent") -> dict:
    """Put a repo in a group (created if new), or take it out of all groups with None."""
    if repo not in cfg.repos:
        raise SteeringError(unknown_repo(cfg.repos, repo))
    if group is not None:
        _check_name("group name", group)
    _edit_files(cfg, {"repos.yaml": lambda lines: _group_edit(lines, cfg, repo, group)})
    _audit(cfg, "set_group", {"repo": repo, "group": group}, created_by)
    return {"repo": repo, "group": group}


# For a person at a terminal (CLI output and errors).
NO_REPOS = (
    'No repos yet. Ask your coding agent to add one ("add the repo at ~/src/myapp"), '
    "or run: gittok repos add <name> <path-or-url>"
)
# For the agent (the SessionStart hint and tool results).
NO_REPOS_AGENT = (
    "No repos are configured. Ask the user which repo to add (a local path or a git URL), "
    "then call add_repo."
)


def next_step(name: str) -> str:
    """What the agent does after add_repo."""
    return (
        f"Next: profile the repo now. Do not ask first. Tell the "
        f"user in one line that you profile {name} so that GitTok learns which code is worth "
        "teaching, that it takes a few minutes and some model quota, and that it may ask "
        "permission to run a code analyzer. Then run the gittok-profile-repo skill "
        f"(/gittok-profile-repo {name}). Then call status and read "
        "renderer_setup.illustration. Memes are bundled. When backend is agent, the images "
        "are made after the writers finish (the image step of the generation skill: Codex "
        "uses its native image tool; Claude gives each card to a gittok-illustrator subagent "
        "that draws SVG); never download a model or use a paid API for it. In Claude Code with "
        "installed false, add one line: the images are simple drawings, and the images "
        "extra (mflux, Apple silicon) gives real illustrations. When backend is local, the "
        "feed server downloads its model by itself. Say in one line what it shows and never "
        "wait for it. Missing mflux (the images extra) falls back to the agent. Then give the "
        "repo a mascot. Pick a small character and a drawing style "
        "that fit what you just read in the repo, save it with "
        f'set_mascot(name, style, repo="{name}"), and tell the user in one line what you chose '
        "and that they can change it by asking. Then say in one line that you make the first "
        "cards, and run the gittok-generate skill (/gittok-generate); it stops by itself when "
        "get_brief answers nothing_to_do. If you have no skills, skip the profile (GitTok "
        "then uses its default rules) and make the cards with get_brief."
    )


def _check_allowed_path(cfg, full: Path) -> None:
    """Refuse a path outside `repos.allowed_roots`, when the user set that list. Makes no
    git call. An empty list is no limit."""
    configured = cfg.settings.repos.allowed_roots
    if not configured:
        return
    home = Path.home().resolve()
    roots = [r for r in (p.resolve() for p in configured) if r != Path("/") and r != home]
    if not any(full.is_relative_to(r) for r in roots):
        shown = ", ".join(str(r) for r in roots) or "none that can be used"
        raise SteeringError(
            f"'{full}' is outside `repos.allowed_roots` ({shown}). The user set this limit in "
            "local/settings.yaml: do not work around it. Tell the user. To allow the repo, "
            "the user adds its parent directory to that list."
        )


def _check_repo_root(cfg, full: Path) -> None:
    """Refuse anything that is not the top directory of a git checkout with a commit.

    The path checks come first: git runs only in a directory that has its own `.git`.
    """
    if full == Path("/") or full == Path.home().resolve():
        raise SteeringError(
            f"'{full}' is the root or home directory. Register one repo, not a whole tree."
        )
    if not full.is_dir():
        raise SteeringError(f"'{full}' does not exist or is not a directory.")
    for r in cfg.repos.values():
        inside = r.path.resolve()
        if full != inside and full.is_relative_to(inside):
            raise SteeringError(
                f"'{full}' is inside the repo '{r.name}' ({inside}). GitTok reads it as part "
                "of that repo; it cannot be a repo of its own."
            )
    if not (full / ".git").exists():
        above = next((p for p in full.parents if (p / ".git").exists()), None)
        if above is not None:
            raise SteeringError(
                f"'{full}' is a subdirectory of the repo at '{above}'. Register the repo root "
                "instead."
            )
        raise SteeringError(f"'{full}' is not a git repo. Give the path of a git checkout.")
    try:
        top = Path(gitq.run(full, "rev-parse", "--show-toplevel").strip()).resolve()
    except (gitq.GitError, OSError):
        raise SteeringError(
            f"'{full}' is not a git repo. Give the path of a git checkout."
        ) from None
    if top != full:
        raise SteeringError(
            f"'{full}' is a subdirectory of the repo at '{top}'. Register the repo root instead."
        )
    try:
        gitq.rev_parse(full, "HEAD")
    except gitq.GitError:
        raise SteeringError(
            f"The repo at '{full}' has no commits yet. Make the first commit, then add it."
        ) from None


def add_repo(
    cfg,
    name: str,
    path: str,
    ref: str | None = None,
    group: str | None = None,
    mascot: str | None = None,
    created_by: str = "agent",
    any_root: bool = False,
) -> dict:
    """Add a repo to local/repos.yaml. `path` is a local directory or a remote URL.

    A local path must be the root of a git checkout that has a commit and is not inside a
    configured repo. When the user set `repos.allowed_roots`, it must also sit inside one
    of them, unless `any_root` is true. Only the CLI sets `any_root`: there the user typed
    the path.

    A remote URL (see `parse_remote`) is cloned from the network into <home>/repos/<name>.
    The entry gets `fetch: true`, the remote's default branch as `ref`, and `remote: <url>`.
    The allowed roots do not apply: the clone is in GitTok's own directory."""
    _check_name("repo name", name)
    if name in cfg.repos:
        raise SteeringError(f"Repo '{name}' already exists. Use set_group to change its group.")
    if mascot is not None and mascot not in cfg.mascots:
        raise SteeringError(
            f"Unknown mascot '{mascot}'. Known: {', '.join(cfg.mascots) or 'none'}. "
            "Create it with set_mascot first."
        )
    if group is not None:
        _check_name("group name", group)
    remote = None
    if parse_remote(path) is not None:
        remote = path
        full, ref = _clone_remote(cfg, name, remote, ref)
    else:
        full = Path(path).expanduser().resolve()
        if not any_root:
            _check_allowed_path(cfg, full)
        _check_repo_root(cfg, full)
        if ref is not None:
            try:
                gitq.rev_parse(full, ref)
            except gitq.GitError:
                raise SteeringError(
                    f"Unknown ref '{ref}' in {full}. Use a branch, tag, or HEAD."
                ) from None

    def edit(lines: list[str]) -> None:
        fields = {"path": str(full), "ref": ref, "mascot": mascot}
        if remote is not None:
            fields |= {"fetch": True, "remote": remote}
        _set_fields(lines, "repos", name, fields)
        if group is not None:
            _group_edit(lines, cfg, name, group)

    try:
        _edit_files(cfg, {"repos.yaml": edit})
    except BaseException:
        if remote is not None:
            shutil.rmtree(full, ignore_errors=True)
        raise
    out = {"name": name, "path": str(full), "ref": ref, "group": group, "mascot": mascot}
    if remote is not None:
        out["remote"] = remote
    _audit(cfg, "add_repo", out, created_by)
    return {**out, "next": next_step(name)}


REMOTE_SCHEMES = ("https", "ssh", "git")
_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*)://(.*)$", re.S)
_TRANSPORT = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*)::")
_SCP = re.compile(r"^([^@/:\s]+)@([^/:]*):(.*)$", re.S)  # user@host:path
_HOST = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?")
_USER = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")
_REMOTE_FORMS = "https://host/path, ssh://user@host/path, git://host/path or user@host:path"


def parse_remote(text: str) -> tuple[str, str] | None:
    """(url, default repo name) when `text` is a remote that GitTok may clone; None when it
    reads as a local path. SteeringError for any other remote form.

    Allowed: https://, ssh://, git:// and scp-style user@host:path, with no password or token
    in it. The error text never repeats `text`, because it can hold a secret."""
    if text.startswith("-"):
        raise SteeringError("A repo path or URL must not start with '-'.")
    if m := _TRANSPORT.match(text):
        raise SteeringError(
            f"The '{m[1]}::' transport is not allowed. Use one of: {_REMOTE_FORMS}."
        )
    user = None
    if m := _SCHEME.match(text):
        scheme = m[1].lower()
        if scheme not in REMOTE_SCHEMES:
            raise SteeringError(
                f"'{scheme}://' URLs are not allowed. Use one of: {_REMOTE_FORMS}. "
                "For a repo on this machine, give its directory."
            )
        authority, _, path = m[2].partition("/")
        userinfo, at, hostport = authority.rpartition("@")
        if at and (scheme != "ssh" or ":" in userinfo):
            raise SteeringError(
                "The URL holds a user name, password or token. GitTok does not store "
                "credentials: use a git credential helper, or an ssh URL."
            )
        user = userinfo if at else None
        host, colon, port = hostport.partition(":")
        if colon and not port.isdigit():
            raise SteeringError("The URL has a bad port number after the host.")
    elif m := _SCP.match(text):
        user, host, path = m[1], m[2], m[3]
    else:
        return None
    if _CONTROL.search(text) or any(c.isspace() for c in text):
        raise SteeringError("A repo URL must not contain a space or a control character.")
    if user is not None and not _USER.fullmatch(user):
        raise SteeringError("The URL has a bad user name before the host.")
    if not _HOST.fullmatch(host):
        raise SteeringError("The URL has a bad host name.")
    last = path.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
    if not last:
        raise SteeringError("The URL has no repo path after the host.")
    return text, last


def managed_dir(cfg, name: str) -> Path:
    """Where GitTok keeps its own clone of a repo added by URL: <home>/repos/<name>."""
    return (cfg.root / "repos").resolve() / name


def is_managed(cfg, repo) -> bool:
    """True when GitTok made this repo's clone and may delete it."""
    dest = managed_dir(cfg, repo.name)
    return bool(repo.remote) and repo.path == dest and not dest.is_symlink()


def _clone_remote(cfg, name: str, url: str, ref: str | None) -> tuple[Path, str]:
    """Clone `url` into the managed dir. Returns (path, remote-tracking ref)."""
    dest = managed_dir(cfg, name)
    if dest.exists() or dest.is_symlink():
        raise SteeringError(
            f"'{dest}' already exists. Delete it or use another repo name, then try again."
        )
    try:
        gitq.clone(url, dest)
    except gitq.GitError as e:
        raise SteeringError(f"Could not clone the remote. {e}") from None
    try:
        if ref is None:
            return dest, gitq.default_remote_ref(dest)
        for candidate in (f"origin/{ref}", ref):  # `main` means the remote's main
            try:
                gitq.rev_parse(dest, candidate)
                return dest, candidate
            except gitq.GitError:
                continue
        raise SteeringError(
            f"Unknown ref '{ref}' in the remote. Use a branch name, for example main."
        )
    except BaseException as e:
        shutil.rmtree(dest, ignore_errors=True)
        if isinstance(e, gitq.GitError):
            raise SteeringError(f"Cannot use the remote: {e}.") from None
        raise


def _local_names(cfg, fname: str, top: str) -> set[str]:
    """Entry names under `top` in the user's own local/<fname>."""
    try:
        data = yaml.safe_load((cfg.root / "local" / fname).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return set()
    entries = data.get(top) if isinstance(data, dict) else None
    return {str(k) for k in entries} if isinstance(entries, dict) else set()


def _mascot_plan(cfg, name: str) -> tuple[list[str], list[dict]]:
    """(mascots to delete, mascots to keep with the reason) when the repo `name` goes.

    A mascot belongs to the repo when the repo's entry names it or its own `repo` is `name`.
    It is deleted only when the user's local/mascots.yaml defines it and no other configured
    repo uses it. (No mascot is shipped.)"""
    repo = cfg.repos[name]
    bound = [m.name for m in cfg.mascots.values() if m.repo == name]
    if repo.mascot in cfg.mascots and repo.mascot not in bound:
        bound.append(repo.mascot)
    local = _local_names(cfg, "mascots.yaml", "mascots")
    remove, keep = [], []
    for m in sorted(bound):
        users = sorted(
            {r.name for r in cfg.repos.values() if r.name != name and r.mascot == m}
            | ({cfg.mascots[m].repo} - {None, name}) & set(cfg.repos)
        )
        if users:
            keep.append({"name": m, "why": f"the repo {users[0]} uses it"})
        elif m in local:
            remove.append(m)
    return remove, keep


def _unlink_mascots(lines: list[str], name: str, remove: list[str], keep: list[dict]) -> None:
    """Edit local/mascots.yaml: delete the `remove` entries; a kept entry loses `repo: name`."""
    for m in remove:
        entry = _entry(lines, "mascots", m, create=False)
        if entry:
            del lines[entry[0] : entry[1]]
    for m in (k["name"] for k in keep):
        entry = _entry(lines, "mascots", m, create=False)
        if entry is None:
            continue
        field = _find(lines, "repo", entry[0] + 1, entry[1], None)
        if field and yaml.safe_load(lines[field[0]].split(":", 1)[1].split(" #")[0]) == name:
            del lines[field[0] : field[1]]


def remove_repo(cfg, name: str, created_by: str = "user", keep_data: bool = False) -> dict:
    """Remove a repo and all that GitTok made for it.

    Removed: the entry in local/repos.yaml and in its groups; the repo's cards with all that
    hangs off them (events, rewards, quiz schedule, saved marks, replies, notifications) and
    their image files; the analysis, facts, candidates, leads and knowledge of the repo;
    steering rules on the repo; its profile local/profiles/<name>.yaml; a mascot of the repo
    that the user defined and no other repo uses; and a clone that GitTok made (repo added by
    URL). Kept: the learned weights, a mascot that another repo uses, and a directory the user
    gave, which is never touched. A card of another repo that only cites this repo stays.

    `keep_data` removes only the entry (and a clone that GitTok made): cards, profile and
    mascot stay. The feed does not show them while the repo is not configured, and garbage
    collection leaves them. They are in use again when a repo of the same name is added."""
    repo = cfg.repos.get(name)
    if repo is None:
        raise SteeringError(unknown_repo(cfg.repos, name))
    managed = is_managed(cfg, repo)
    gone, kept = ([], []) if keep_data else _mascot_plan(cfg, name)
    db_file = cfg.settings.data_dir / "gittok.db"
    if not keep_data and db_file.is_file():
        # What the reader did with these cards goes into the weights before the events go.
        try:
            with closing(db.open_db(db_file)) as conn:
                learning.process_events(conn, cfg)
        except Exception:
            log.warning("could not process events before removing %s", name, exc_info=True)

    def edit(lines: list[str]) -> None:
        _drop_from_groups(lines, name, None)
        entry = _entry(lines, "repos", name, create=False)
        if entry is None:
            raise SteeringError(f"Cannot find '{name}' in local/repos.yaml. Edit it by hand.")
        del lines[entry[0] : entry[1]]

    edits = {"repos.yaml": edit}
    if (gone or kept) and (cfg.root / "local" / "mascots.yaml").is_file():
        edits["mascots.yaml"] = lambda lines: _unlink_mascots(lines, name, gone, kept)
    _edit_files(cfg, edits)

    out = {
        "name": name,
        "path": str(repo.path),
        "deleted_clone": managed,
        "kept_data": keep_data,
        "cards_removed": 0,
        "files_removed": 0,
        "rules_removed": 0,
        "profile_removed": False,
        "mascots_removed": gone,
        "mascots_kept": kept,
    }
    try:
        with closing(db.open_db(db_file)) as conn:
            if keep_data:
                with conn:
                    gc.set_kept(conn, name, True)
            else:
                counts = gc.purge_repo(conn, cfg, name)
                out |= {
                    "cards_removed": counts["cards"],
                    "files_removed": counts["files"],
                    "rules_removed": counts["rules"],
                }
    except sqlite3.Error as e:
        # The entry is gone already. The feed hides the cards, and the next garbage
        # collection pass (or `gittok gc`) deletes them.
        out["pending"] = (
            f"The database was busy ({e}), so the repo's cards are not deleted yet. The feed "
            "does not show them, and the next garbage collection pass deletes them."
        )
    if not keep_data:
        profile = cfg.root / "local" / "profiles" / f"{name}.yaml"
        if profile.is_file():
            profile.unlink()
            out["profile_removed"] = True
        for m in gone:
            (cfg.settings.data_dir / "assets" / "mascots" / f"{m}.png").unlink(missing_ok=True)
    if managed:
        shutil.rmtree(repo.path, ignore_errors=True)
    _audit(cfg, "remove_repo", out, created_by)
    return out


def removal_summary(out: dict) -> str:
    """One line for a person: what `remove_repo` removed and what it kept."""
    where = "its clone is deleted" if out["deleted_clone"] else "the directory is not touched"
    head = f"removed repo {out['name']} ({out['path']}): {where}"
    if out["kept_data"]:
        return f"{head}; its cards, profile and mascot are kept (--keep-data)"

    def n(count: int, word: str) -> str:
        return f"{count} {word}" if count == 1 else f"{count} {word}s"

    parts = [f"{n(out['cards_removed'], 'card')} and {n(out['files_removed'], 'file')} removed"]
    if out["rules_removed"]:
        parts.append(f"{n(out['rules_removed'], 'rule')} removed")
    if out["profile_removed"]:
        parts.append("profile removed")
    if out["mascots_removed"]:
        parts.append(f"mascot {', '.join(out['mascots_removed'])} removed")
    for k in out["mascots_kept"]:
        parts.append(f"mascot {k['name']} kept ({k['why']})")
    if out.get("pending"):
        parts = ["cards not deleted yet (the database was busy; `gittok gc` deletes them)"]
    return f"{head}; {'; '.join(parts)}; learned weights kept"


def _set_key(lines: list[str], section: str, key: str, value) -> None:
    """Set `key: value` directly under top-level `section` (the shape of settings.yaml).
    Other lines and comments stay."""
    sec = _find(lines, section, 0, len(lines), 0)
    if sec is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"{section}:")
        sec = (len(lines) - 1, len(lines))
    _no_inline(lines[sec[0]], section)
    found = _find(lines, key, sec[0] + 1, sec[1], None)
    if found is None:
        ind = _child_indent(lines, sec[0] + 1, sec[1], 2)
        lines.insert(sec[1], f"{' ' * ind}{key}: {_scalar(value)}")
        return
    m = re.match(r"^(\s*[^:]+:)\s*(.*?)(\s+#.*)?$", lines[found[0]])
    lines[found[0] : found[1]] = [f"{m[1]} {_scalar(value)}{m[3] or ''}"]


def set_lan(cfg, enabled: bool, created_by: str = "agent") -> dict:
    """Turn phone access (LAN serving) off or on: writes only `server.lan` in
    local/settings.yaml. The running server does not change until it starts again."""
    if not isinstance(enabled, bool):
        raise SteeringError("enabled must be true or false.")
    _edit_files(cfg, {"settings.yaml": lambda lines: _set_key(lines, "server", "lan", enabled)})
    _audit(cfg, "set_lan", {"enabled": enabled}, created_by)
    after = (
        "After the restart, call feed_address to give the user the phone address and the "
        "pairing steps."
        if enabled
        else "After the restart, the feed answers this computer only."
    )
    return {"lan": enabled, "restart": f"{social.LAN_RESTART} {after}"}


def set_mascot(
    cfg,
    name: str,
    repo: str | None = None,
    style: str | None = None,
    seed: int | None = None,
    created_by: str = "agent",
) -> dict:
    """Create or change a mascot in local/mascots.yaml; with `repo`, link it to that repo."""
    _check_name("mascot name", name)
    old = cfg.mascots.get(name)
    if style is not None:
        style = _check_text("style", style, MAX_STYLE)
    if repo is not None and repo not in cfg.repos:
        raise SteeringError(unknown_repo(cfg.repos, repo))
    if old is None and not style:
        raise SteeringError(f"New mascot '{name}' needs a style (the image prompt prefix).")
    if seed is not None and (not isinstance(seed, int) or isinstance(seed, bool)):
        raise SteeringError("seed must be a whole number.")
    final = {
        "repo": repo if repo is not None else (old.repo if old else None),
        "style": style or old.style,
        "seed": seed
        if seed is not None
        else (old.seed if old else zlib.crc32(name.encode()) % 10000 + 1),
    }
    edits = {"mascots.yaml": lambda lines: _set_fields(lines, "mascots", name, final)}
    if repo is not None:
        edits["repos.yaml"] = lambda lines: _set_fields(lines, "repos", repo, {"mascot": name})
    _edit_files(cfg, edits)
    _audit(cfg, "set_mascot", {"name": name, **final}, created_by)
    return {"name": name, **final}


def edit_persona(
    cfg,
    handle: str,
    name: str | None = None,
    voice: str | None = None,
    created_by: str = "agent",
) -> dict:
    """Change a persona's display name or voice, or create one with both."""
    _check_name("persona handle", handle)
    old = cfg.personas.get(handle)
    if name is not None:
        name = _check_text("name", name, MAX_NAME)
    if voice is not None:
        voice = _check_text("voice", voice, MAX_VOICE)
    if name is None and voice is None:
        raise SteeringError("Nothing to change. Give a name, a voice, or both.")
    if old is None and not (name and voice):
        raise SteeringError(f"New persona '{handle}' needs both name and voice.")
    final = {"name": name or old.name, "voice": voice or old.voice}
    _edit_files(cfg, {"personas.yaml": lambda lines: _set_fields(lines, "personas", handle, final)})
    _audit(cfg, "edit_persona", {"handle": handle, **final}, created_by)
    return {"handle": handle, **final}


# Viewer preferences (prefs table): read by the client at GET /api/prefs.
PREF_DEFAULTS: dict[str, float] = {"playback_speed": 1.0}
MIN_SPEED, MAX_SPEED = 0.25, 4.0


def get_prefs(conn) -> dict:
    prefs = dict(PREF_DEFAULTS)
    for row in conn.execute("SELECT key, value FROM prefs"):
        if row["key"] in prefs:
            prefs[row["key"]] = json.loads(row["value"])
    return prefs


def set_playback_speed(conn, cfg, speed, created_by: str = "agent") -> dict:
    """How fast beat cards play: 1.0 normal, 1.5 is 50% faster, 0.75 slower."""
    if isinstance(speed, bool) or not isinstance(speed, int | float):
        raise SteeringError("speed must be a number, for example 1.0 (normal) or 1.5 (faster).")
    if not MIN_SPEED <= speed <= MAX_SPEED:
        raise SteeringError(f"speed must be between {MIN_SPEED} and {MAX_SPEED}; 1.0 is normal.")
    speed = round(float(speed), 2)
    with conn:
        conn.execute(
            "INSERT INTO prefs(key, value, updated_at) VALUES ('playback_speed', ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "updated_at = excluded.updated_at",
            (json.dumps(speed), _iso(_now(None))),
        )
    _audit(cfg, "set_playback_speed", {"speed": speed}, created_by)
    return {"playback_speed": speed}

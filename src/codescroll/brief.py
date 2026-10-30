"""Turns analysis signals and the default mix into a brief for the agent (SPEC §10.3).

The brief is split into work packets so a cheap subagent can write each packet's
cards without any other context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_DRAMA = (
    "commit_drama",
    "hot_spot",
    "archaeology",
    "rip",
    "ancient_todo",
    "secret_couples",
    "whose_code",
)

# Story types that can be rendered, by default-mix category.
CATEGORY_STORIES: dict[str, tuple[str, ...]] = {
    "git_drama": _DRAMA,
    "memes": (*_DRAMA, "what_it_does"),
    "illustrated_explainers": ("what_it_does", "journey", "analogy"),
    "code": ("snippet_callouts", "cursed_clever_line", "before_after"),
    "cross_repo_and_recent": ("before_after", "new_arrival"),
    "interactive": ("spot_the_bug", "guess_who", "guess_when", "quiz", "this_or_that"),
}

# Suggested card formats (docs/formats.md), by default-mix category.
CATEGORY_FORMATS: dict[str, tuple[str, ...]] = {
    "git_drama": (
        "text_post",
        "code_card",
        "breaking_news",
        "iceberg",
        "chart",
        "hot_take",
        "group_chat",
    ),
    "memes": ("meme", "text_meme"),
    "illustrated_explainers": (
        "mascot_scene",
        "comic",
        "eli5",
        "day_in_life",
        "dating_profile",
        "thread",
        "diagram",
    ),
    "code": ("code_card", "glow_up", "flags", "tier_list"),
    "cross_repo_and_recent": ("breaking_news", "horoscope", "text_post"),
    "interactive": ("quiz",),
}

CATEGORY_FORMATS_FLAT = tuple(dict.fromkeys(f for fs in CATEGORY_FORMATS.values() for f in fs))

# Illustrations each format costs against settings.render.max_illustrations_per_run.
# A comic has 2 or 3 panels (one illustration each); the brief reserves the worst case, 3.
ILLUSTRATION_COST = {"mascot_scene": 1, "comic": 3}

# Formats a haiku can write when the story type is concrete. Everything else needs sonnet.
HAIKU_FORMATS = frozenset(
    {"meme", "text_meme", "chart", "breaking_news", "horoscope", "flags", "tier_list"}
)


def largest_remainder(weights: dict[str, float], total: int) -> dict[str, int]:
    """Integer allocation of `total` proportional to `weights` (Hamilton method)."""
    pos = {k: w for k, w in weights.items() if w > 0}
    if total <= 0 or not pos:
        return {k: 0 for k in weights}
    s = sum(pos.values())
    raw = {k: total * w / s for k, w in pos.items()}
    out = {k: int(v) for k, v in raw.items()}
    left = total - sum(out.values())
    order = sorted(pos, key=lambda k: (-(raw[k] - out[k]), -pos[k], k))
    for k in order[:left]:
        out[k] += 1
    return {k: out.get(k, 0) for k in weights}


# Story types whose leads already name the exact commit/path: cheap model is enough.
CONCRETE_TYPES = frozenset({"rip", "ancient_todo", "hot_spot", "new_arrival", "whose_code"})

MAX_LEADS_PER_TYPE = 5


def _date(ts) -> str:
    import datetime as _dt

    return _dt.datetime.fromtimestamp(int(ts), _dt.UTC).strftime("%Y-%m-%d") if ts else "?"


def _sha(s) -> str:
    return (s or "?")[:10]


_NOISE = re.compile(
    r"(^|/)(\.beads|node_modules|dist|build|vendor|\.svelte-kit)/"
    r"|(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|uv\.lock|poetry\.lock|Cargo\.lock"
    r"|Gemfile\.lock|go\.sum|deps\.lock\.json)$"
    r"|\.(min\.js|min\.css|map|lock|jsonl|svg|png|jpg|gif|ico|pdf)$"
)
_TEST = re.compile(
    r"(^|/)(tests?|spec|__tests__)/|(_test|_spec|\.test|\.spec)\.[a-z]+$|(^|/)test_[^/]+$"
)
_DOC = re.compile(r"\.(md|markdown|txt|rst|adoc)$", re.IGNORECASE)
_COMMENT_TODO = re.compile(r"(#|//|;|--|/\*|\*|<!--)\s*(TODO|FIXME|HACK|XXX)\b")
ANCIENT_DAYS = 90


def _useful(path: str) -> bool:
    return not _NOISE.search(path)


def _old(ts, t0) -> bool:
    return t0 is None or (ts or t0) <= t0 - ANCIENT_DAYS * 86400


def leads_for(
    story_type: str, sig: dict, t0: int | None = None, limit: int = MAX_LEADS_PER_TYPE
) -> list[str]:
    """Human-readable leads for one story type, drawn from precomputed signals.

    Generated files and lockfiles are never leads. "Ancient" stories need material
    older than ANCIENT_DAYS before the repo's last commit (t0).
    """
    churn_files = sig.get("churn", {}).get("files", {})
    hot = [f for f in churn_files.get("90") or churn_files.get("365") or [] if _useful(f["path"])]
    wide = [
        f
        for f in churn_files.get("365") or churn_files.get("90") or []
        if _useful(f["path"]) and not _TEST.search(f["path"]) and not _DOC.search(f["path"])
    ]
    out: list[str] = []
    if story_type == "hot_spot":
        out += [
            f"{f['path']}: {f['commits']} commits, {f['lines']} lines changed (90d)" for f in hot
        ]
        dirs = sig.get("churn", {}).get("dirs", {}).get("90", [])
        out += [f"dir {d['path']}/: {d['commits']} commits (90d)" for d in dirs[:2]]
    elif story_type == "commit_drama":
        for r in sig.get("reverts", []):
            out.append(
                f"revert {_sha(r['sha'])} ({_date(r['ts'])}, {r['author']}) undid "
                f'{_sha(r.get("reverted_sha"))} "{r.get("reverted_subject", "?")}"'
            )
        for c in (c for c in sig.get("fix_chains", []) if _useful(c["path"])):
            subj = " -> ".join(f'{_sha(x["sha"])} "{x["subject"]}"' for x in c["commits"])
            out.append(f"fix chain on {c['path']}: {subj}")
        for h in sig.get("huge_diffs", []):
            out.append(
                f'huge diff {_sha(h["sha"])} "{h["subject"]}" ({h["lines"]} lines, '
                f"{h['author']}, {_date(h['ts'])})"
            )
        for n in sig.get("commit_times", {}).get("late_night", []):
            out.append(
                f"late-night commit {_sha(n['sha'])} at {n['local_hour']:02d}:xx by "
                f'{n["author"]}: "{n["subject"]}"'
            )
    elif story_type == "archaeology":
        out += [
            f"{o['path']}:{o['line']} from {_date(o['ts'])} ({o['author']}, {_sha(o['sha'])}): "
            f"{o['text'].strip()[:80]}"
            for o in sig.get("oldest_lines", [])
            if _old(o["ts"], t0) and _useful(o["path"])
        ]
    elif story_type == "rip":
        out += [
            f"{d['path']} born {_date(d.get('born_ts'))} ({_sha(d.get('born_sha'))}), died "
            f"{_date(d['died_ts'])} ({_sha(d['died_sha'])}, {d['died_author']}): "
            f'"{d["cause"]}", lived {d.get("lived_days", "?")} days'
            for d in sig.get("deleted_paths", [])
            if _useful(d["path"])
        ]
    elif story_type == "ancient_todo":
        out += [
            f"{t['path']}:{t['line']} {t['tag']} from {_date(t['ts'])} ({t['author']}, "
            f"{_sha(t['sha'])}): {t['text'].strip()[:80]}"
            for t in sig.get("todo_ages", [])
            if _old(t["ts"], t0) and _COMMENT_TODO.search(t["text"]) and _useful(t["path"])
        ]
    elif story_type == "secret_couples":
        pairs = sorted(
            (c for c in sig.get("co_change", []) if _useful(c["a"]) and _useful(c["b"])),
            key=lambda c: c.get("same_dir", False),
        )
        out += [
            f"{c['a']} + {c['b']}: changed together {c['count']} times (jaccard {c['jaccard']})"
            for c in pairs
        ]
    elif story_type == "whose_code":
        for d, authors in sig.get("author_shares", {}).get("by_dir", {}).items():
            top = ", ".join(f"{a['author']} {round(a['share'] * 100)}%" for a in authors[:3])
            out.append(f"dir {d}/: {top}")
    elif story_type == "new_arrival":
        out += [
            f"{n['path']} added {_date(n['ts'])} in {_sha(n['sha'])} by {n['author']}: "
            f'"{n["subject"]}"'
            for n in sig.get("new_files", [])
            if _useful(n["path"])
        ]
    elif story_type == "spot_the_bug":
        for c in (c for c in sig.get("fix_chains", []) if _useful(c["path"])):
            for x in c["commits"]:
                out.append(
                    f'fix {_sha(x["sha"])} on {c["path"]}: "{x["subject"]}" '
                    "(the visual is the file at that fix's first parent)"
                )
    elif story_type == "before_after":
        recent = sig.get("commits_since", {}).get("commits", [])
        out += [
            f'recent commit {_sha(c["sha"])} ({_date(c["ts"])}, {c["author"]}): "{c["subject"]}"'
            for c in recent
        ]
        for c in (c for c in sig.get("fix_chains", []) if _useful(c["path"])):
            x = c["commits"][-1]
            out.append(f'fix {_sha(x["sha"])} on {c["path"]}: "{x["subject"]}"')
    else:  # explanatory types: point at central, much-edited files
        out += [f"{f['path']} ({f['commits']} commits in the last year)" for f in wide]
    return out[:limit]


# --- Cross-repo leads (SPEC 6.4) -------------------------------------------

CROSS_CATEGORY = "cross_repo_and_recent"
CROSS_STORIES = ("ripple", "drift_alert", "weekly_recap")
CROSS_FORMATS = ("breaking_news", "text_post", "listicle", "thread", "iceberg", "group_chat")
DAY_SECONDS = 86400
RIPPLE_DAYS = 3
RECAP_DAYS = 7

_TICKET = re.compile(r"#\d+|\b[A-Za-z][A-Za-z0-9]+-\d+\b")
_BRANCHISH = re.compile(r"\b[a-z][a-z0-9]+(?:[-_/][a-z0-9]+)+\b")
_WORD = re.compile(r"[a-z][a-z0-9]{2,}")
_STOP = frozenset(
    """the and for with from into onto that this these those not but are was were has have had
    its use uses used using add adds added adding fix fixes fixed fixing update updates updated
    remove removes removed change changes changed make makes made get gets set sets new old
    feat chore refactor test tests docs doc merge revert wip again more some also now when then
    than out off all any can will should per via call calls""".split()
)


def _tokens(subject: str) -> tuple[set[str], set[str]]:
    """(ticket-like tokens, significant words) of a commit subject, lowercased."""
    low = subject.lower()
    ids = {t.lower() for t in _TICKET.findall(subject)} | set(_BRANCHISH.findall(low))
    words = {w for w in _WORD.findall(low) if w not in _STOP}
    return ids, words


def _short_commit(repo: str, c: dict) -> str:
    return f'{repo} {_sha(c["sha"])} ({_date(c["ts"])}) "{c["subject"]}"'


def _ripple_leads(members: dict[str, dict]) -> list[str]:
    toks = {
        r: [(c, *_tokens(c["subject"])) for c in m["signals"].get("recent_commits", [])]
        for r, m in members.items()
    }
    found: list[tuple[tuple, str]] = []
    names = sorted(members)
    for i, ra in enumerate(names):
        for rb in names[i + 1 :]:
            for ca, ia, wa in toks[ra]:
                for cb, ib, wb in toks[rb]:
                    if abs(ca["ts"] - cb["ts"]) > RIPPLE_DAYS * DAY_SECONDS:
                        continue
                    ids, words = ia & ib, wa & wb
                    if not ids and len(words) < 2:
                        continue
                    shared = sorted(ids) + sorted(words - ids)
                    key = (not ids, -len(shared), -max(ca["ts"], cb["ts"]), ca["sha"], cb["sha"])
                    found.append(
                        (
                            key,
                            f"{_short_commit(ra, ca)} <-> {_short_commit(rb, cb)}; "
                            f"shared: {', '.join(shared)}",
                        )
                    )
    found.sort(key=lambda kv: kv[0])
    return [line for _, line in found]


def _recap_leads(members: dict[str, dict]) -> list[str]:
    t0 = max(m.get("t0") or 0 for m in members.values())
    cutoff = t0 - RECAP_DAYS * DAY_SECONDS
    rows = []
    for repo in sorted(members):
        week = [c for c in members[repo]["signals"].get("recent_commits", []) if c["ts"] >= cutoff]
        if week:
            rows.append((repo, week))
    if len(rows) < 2:  # a recap needs commits from at least two repos
        return []
    out = []
    for repo, week in rows:
        top = sorted(week, key=lambda c: (-len(c.get("files", [])), -c["ts"], c["sha"]))[:3]
        shown = "; ".join(f'{_sha(c["sha"])} "{c["subject"]}"' for c in top)
        n = len(week)
        out.append(f"{repo}: {n} commit{'s' * (n != 1)} since {_date(cutoff)}; top: {shown}")
    return out


_ROUTE = re.compile(r"/api/[\w\-]+(?:/[\w\-{}:]+)*")
_ENV_KEY = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")
_GENERIC_BASENAMES = frozenset(
    """readme.md changelog.md license package.json package-lock.json tsconfig.json pyproject.toml
    setup.py setup.cfg __init__.py index.js index.ts index.py main.py main.js main.ts makefile
    dockerfile .gitignore .gitattributes .env.example conftest.py settings.json config.json
    cargo.toml go.mod deps.edn project.clj""".split()
)


def _identifiers(subject: str) -> set[str]:
    return set(_ROUTE.findall(subject)) | {k for k in _ENV_KEY.findall(subject) if len(k) >= 6}


def _contract_file(path: str) -> bool:
    base = path.rsplit("/", 1)[-1]
    return (
        _useful(path)
        and not _TEST.search(path)
        and not _DOC.search(path)
        and base.lower() not in _GENERIC_BASENAMES
    )


def _files_text(c: dict) -> str:
    return ", ".join(c.get("files", [])[:3]) or "no files listed"


MAX_GREP_IDENTIFIERS = 5


def _grep_files(member: dict, ident: str, limit: int = 3) -> list[str]:
    """Files at the repo's analyzed head that mention `ident` (fixed string); [] if unknown."""
    from codescroll import gitq

    path, head = member.get("path"), member.get("head_sha")
    if not path or not head:
        return []
    try:
        raw = gitq.run_bytes(
            path, "grep", "-l", "-F", "-I", "-e", ident, head, "--", ok_codes=(0, 1)
        )[1].decode(errors="replace")
    except gitq.GitError:
        return []
    prefix = f"{head}:"
    files = [ln.removeprefix(prefix) for ln in raw.splitlines() if ln]
    return [f for f in files if _useful(f)][:limit]


def _drift_leads(members: dict[str, dict]) -> list[str]:
    names = sorted(members)
    recent = {r: members[r]["signals"].get("recent_commits", []) for r in names}
    out: list[str] = []
    # 1. The same route or env key shows up in the recent commits of two repos.
    ids: dict[str, dict[str, dict]] = {}
    for r in names:
        for c in recent[r]:  # newest first: keep the newest commit per repo
            for ident in _identifiers(c["subject"]):
                ids.setdefault(ident, {}).setdefault(r, c)
    for ident, per in sorted(ids.items()):
        if len(per) >= 2:
            sides = "; ".join(
                f'{r} {_sha(c["sha"])} ({_date(c["ts"])}) "{c["subject"]}" [{_files_text(c)}]'
                for r, c in sorted(per.items())
            )
            out.append(f"{ident} appears in recent changes of {', '.join(sorted(per))}: {sides}")
    # 2. An identifier changed in one repo is still referenced, untouched, in another.
    shared = {i for i, per in ids.items() if len(per) >= 2}
    for ra in names:
        picked: dict[str, dict] = {}
        for c in recent[ra]:
            for ident in sorted(_identifiers(c["subject"]) - shared):
                if len(picked) < MAX_GREP_IDENTIFIERS:
                    picked.setdefault(ident, c)
        for ident, ca in picked.items():
            for rb in names:
                if rb == ra:
                    continue
                hits = _grep_files(members[rb], ident)
                if not hits:
                    continue
                since = [
                    c for c in recent[rb] if c["ts"] >= ca["ts"] and set(c["files"]) & set(hits)
                ]
                if since:
                    continue
                out.append(
                    f"possible drift: {ident} changed in {ra} {_sha(ca['sha'])} "
                    f'({_date(ca["ts"])}) "{ca["subject"]}" [{_files_text(ca)}], but {rb} '
                    f"still references it in {', '.join(hits)} and has not touched those "
                    "files since"
                )
    # 3. The same file name changed lately in one repo and not since in the other.
    newest: dict[str, dict[str, tuple[dict, str]]] = {}
    for r in names:
        for c in recent[r]:
            for path in c.get("files", []):
                if _contract_file(path):
                    newest.setdefault(path.rsplit("/", 1)[-1], {}).setdefault(r, (c, path))
    for base, per in sorted(newest.items()):
        for i, ra in enumerate(sorted(per)):
            for rb in sorted(per)[i + 1 :]:
                (ca, pa), (cb, pb) = per[ra], per[rb]
                if abs(ca["ts"] - cb["ts"]) <= RIPPLE_DAYS * DAY_SECONDS:
                    continue  # changed together: that is a ripple, not drift
                (rn, cn, pn), (ro, co, po) = (
                    ((ra, ca, pa), (rb, cb, pb))
                    if ca["ts"] > cb["ts"]
                    else ((rb, cb, pb), (ra, ca, pa))
                )
                out.append(
                    f"{base}: changed in {rn} ({pn}, {_sha(cn['sha'])}, {_date(cn['ts'])}) "
                    f"but not changed since in {ro} ({po}, last {_sha(co['sha'])}, "
                    f"{_date(co['ts'])})"
                )
    return out


def cross_leads(members: dict[str, dict]) -> dict[str, list[str]]:
    """Leads for cross-repo story types, from the analyses of repos in one group.

    `members` maps repo name to its analysis dict (`signals.analyze` result). Heuristic
    and cheap: it only reads the `recent_commits` signal (plus a few `git grep` calls).
    """
    if len(members) < 2:
        return {}
    out = {
        "ripple": _ripple_leads(members),
        "drift_alert": _drift_leads(members),
        "weekly_recap": _recap_leads(members),
    }
    return {k: v[:MAX_LEADS_PER_TYPE] for k, v in out.items() if v}


@dataclass
class Packet:
    id: str
    categories: list[str]
    repo: str
    count: int
    story_types: list[str]
    suggested_model: str
    tones: list[str]
    personas: list[str]
    leads: list[str]
    formats: list[str] = field(default_factory=list)
    repos: list[str] = field(default_factory=list)  # all repos the packet covers; [0] is `repo`


@dataclass
class Brief:
    count: int
    quotas: dict[str, int]
    tone_quotas: dict[str, int]
    packets: list = field(default_factory=list)
    recent: list = field(default_factory=list)
    mix_evidence: int | None = None  # rewards behind a learned mix; None means default mix
    rules: list = field(default_factory=list)
    focus: list = field(default_factory=list)  # (repo or None, dir or None, slots)
    unavailable: list = field(default_factory=list)

    def to_dict(self) -> dict:
        from dataclasses import asdict

        return {
            "count": self.count,
            "quotas": self.quotas,
            "tone_quotas": self.tone_quotas,
            "packets": [asdict(p) for p in self.packets],
            "recent": self.recent,
        }

    def to_markdown(self) -> str:
        cats = ", ".join(f"{k} {v}" for k, v in self.quotas.items() if v)
        tones = ", ".join(f"{k} {v}" for k, v in self.tone_quotas.items() if v)
        if self.mix_evidence is None:
            mix = "default"
        else:
            mix = f"learned from {self.mix_evidence} reward{'s' * (self.mix_evidence != 1)}"
        out = [
            f"# Brief: Make {self.count} cards",
            "",
            f"Mix: {mix}",
            f"Categories: {cats}.",
            f"Tones: {tones}.",
            f"{len(self.packets)} work packets. Give each packet to one subagent on its "
            "suggested model.",
        ]
        if self.unavailable:
            out += [
                "",
                f"Skipping {', '.join(self.unavailable)}: renderer not available.",
            ]
        if self.rules:
            out += ["", "Rules:"]
            out += [_rule_line(r) for r in self.rules]
        for repo, d, slots in self.focus:
            where = f"{d}/" if d else f"repo {repo}"
            out += [f"Focus: {where} ({slots} slots): lead with it; its leads come first."]
        if self.recent:
            out += ["", "## Recently posted (do not repeat these stories)", ""]
            out += [f"- [{r['story_type']}] {r['hook']}" for r in self.recent]
        for pk in self.packets:
            names = pk.repos if len(pk.repos) > 1 else [pk.repo]
            where = f"repo{'s' * (len(names) > 1)} " + ", ".join(f"`{r}`" for r in names)
            out += [
                "",
                f"## Packet {pk.id}: {pk.count} card(s) from {where}",
                "",
                f"- suggested model: {pk.suggested_model}",
                f"- categories: {', '.join(pk.categories)}",
                f"- story types: {', '.join(pk.story_types)}",
                f"- formats, one per card: {', '.join(pk.formats)}",
                f"- tones, one per card: {', '.join(pk.tones)}",
                f"- personas, one per card: {', '.join(pk.personas)}",
                "- leads:",
            ]
            out += [f"  - {line}" for line in pk.leads]
        return "\n".join(out) + "\n"


def _rule_line(r: dict) -> str:
    extra = []
    if r.get("factor"):
        extra.append(f"x{r['factor']:g}")
    if r.get("slots"):
        extra.append(f"{r['slots']} slots")
    if r.get("max_share") is not None:
        extra.append(f"max share {r['max_share']:g}")
    if r.get("expires_at"):
        extra.append(f"expires {r['expires_at'][:10]}")
    tail = f" ({', '.join(extra)})" if extra else ""
    why = f': "{r["reason"]}"' if r.get("reason") else ""
    return f"- {r['type']} {r['feature']}={r['value']}{tail}{why}"


def _factors(rules, feature: str) -> dict[str, float]:
    """Combined boost/prefer factor per value of a feature."""
    out: dict[str, float] = {}
    for r in rules:
        if r["type"] in ("boost", "prefer") and r["feature"] == feature:
            out[r["value"]] = out.get(r["value"], 1.0) * (r.get("factor") or 2.0)
    return out


def _banned(rules, feature: str) -> set[str]:
    return {r["value"] for r in rules if r["type"] == "ban" and r["feature"] == feature}


def _interleave(quotas: dict[str, int]) -> list[str]:
    """Spread items so the same value does not cluster: a,b,c,a,b,a ..."""
    left = dict(quotas)
    out: list[str] = []
    while any(left.values()):
        for k in sorted(left, key=lambda k: (-quotas[k], k)):
            if left[k]:
                out.append(k)
                left[k] -= 1
    return out


DEFAULT_PERSONAS = (
    "greybeard",
    "penny_learns",
    "archivist",
    "meme_compiler",
    "paranoid_sec",
    "shipit_sam",
)


def _pick_format(
    options, used: dict[str, int], spent: int, budget: int, boost: dict[str, float] | None = None
) -> str:
    """Least-used format of the category that still fits the illustration budget.

    A boost factor divides a format's use count, so boosted formats come up more often.
    """
    boost = boost or {}
    fits = (
        [f for f in options if spent + ILLUSTRATION_COST.get(f, 0) <= budget]
        or [f for f in options if f not in ILLUSTRATION_COST]
        or list(options)
    )
    return min(fits, key=lambda f: ((used.get(f, 0) + 1) / boost.get(f, 1.0), options.index(f)))


def build_brief(
    *,
    repo_signals,
    defaults,
    personas,
    count,
    packet_size,
    recent,
    max_illustrations=4,
    category_shares: dict[str, float] | None = None,
    evidence: int | None = None,
    rules=None,
    unavailable_formats=frozenset(),
    groups: dict[str, list[str]] | None = None,
) -> Brief:
    if not repo_signals:
        raise ValueError("no repos to build a brief from")
    rules = list(rules or [])
    gone_formats = set(unavailable_formats) | _banned(rules, "format")
    gone_stories = _banned(rules, "story_type")
    stories_in = {
        c: tuple(t for t in ts if t not in gone_stories) for c, ts in CATEGORY_STORIES.items()
    }
    formats_in = {
        c: tuple(f for f in fs if f not in gone_formats) for c, fs in CATEGORY_FORMATS.items()
    }
    live = {c for c in CATEGORY_STORIES if stories_in[c] and formats_in[c]}
    fmt_boost = _factors(rules, "format")
    story_boost = _factors(rules, "story_type")
    repo_boost = _factors(rules, "repo")
    focus = []
    for r in rules:
        if r["type"] == "focus" and r["feature"] in ("repo", "dir"):
            n = r.get("slots") or 3
            focus.append((r["value"], None, n) if r["feature"] == "repo" else (None, r["value"], n))
    focus_dirs = [d.strip("/") + "/" for _, d, _ in focus if d]
    focus_repos = {rp: n for rp, _, n in focus if rp}

    def focused_first(lines: list[str]) -> list[str]:
        return sorted(lines, key=lambda x: not any(d in x for d in focus_dirs))

    learned = bool(category_shares) and evidence != 0  # no rewards: keep the default mix
    source = category_shares if learned else defaults.get("categories", {})
    cats = {k: w for k, w in source.items() if k in live}
    if not cats:
        raise ValueError("active rules leave no category with a story type and format")
    quotas = largest_remainder(cats, count)
    if learned and count >= len(cats):
        for k in [k for k, v in quotas.items() if v < 1]:
            donor = max(quotas, key=lambda c: (quotas[c], c))
            quotas[donor] -= 1
            quotas[k] = 1
    banned_tones = _banned(rules, "tone")
    tones_in = {k: w for k, w in defaults.get("tones", {}).items() if k not in banned_tones}
    tone_quotas = largest_remainder(tones_in or defaults.get("tones", {}), count)
    tone_pool = _interleave(tone_quotas)
    repo_names = sorted(repo_signals)
    persona_cycle = list(personas) or list(DEFAULT_PERSONAS)
    persona_cycle = [
        p for p in persona_cycle if p not in _banned(rules, "persona")
    ] or persona_cycle
    story_used: dict[str, int] = {}

    # Cross-repo groups: >= 2 repos of one group in this brief. `groups` (name -> repos)
    # overrides the group each analysis carries.
    if groups is None:
        groups = {}
        for r in repo_names:
            g = repo_signals[r].get("group")
            if g:
                groups.setdefault(g, []).append(r)
    cross_groups = {
        g: [r for r in rs if r in repo_signals]
        for g, rs in sorted(groups.items())
        if len([r for r in rs if r in repo_signals]) >= 2
    }
    cross_by_group: dict[str, dict[str, list[str]]] = {}

    # 1. Allocate every card slot to (repo, category, story_type, format, group).
    # `group` is None except for cross-repo slots, whose repo is the group's first repo.
    slots: list[tuple[str, str, str, str, str | None]] = []
    used: dict[str, int] = {}
    spent = 0
    leads_by: dict[tuple[str, str], list[str]] = {}
    for ci, (category, n) in enumerate(sorted(quotas.items(), key=lambda kv: (-kv[1], kv[0]))):
        if not n:
            continue
        cross_n = 0
        if category == CROSS_CATEGORY:
            cross_fmts = [f for f in CROSS_FORMATS if f not in gone_formats]
            combos = []
            for g, rs in cross_groups.items():
                if g not in cross_by_group:
                    cross_by_group[g] = cross_leads({r: repo_signals[r] for r in rs})
                combos += [
                    (g, t)
                    for t in CROSS_STORIES
                    if t not in gone_stories and cross_by_group[g].get(t)
                ]
            if combos and cross_fmts:
                cross_n = min(-(-n // 2), len(combos))
                for _ in range(cross_n):
                    g, t = min(
                        combos,
                        key=lambda gt: (
                            (story_used.get(gt[1], 0) + 1) / story_boost.get(gt[1], 1.0),
                            CROSS_STORIES.index(gt[1]),
                            gt[0],
                        ),
                    )
                    combos.remove((g, t))
                    fmt = _pick_format(cross_fmts, used, spent, max_illustrations, fmt_boost)
                    used[fmt] = used.get(fmt, 0) + 1
                    spent += ILLUSTRATION_COST.get(fmt, 0)
                    story_used[t] = story_used.get(t, 0) + 1
                    slots.append((cross_groups[g][0], category, t, fmt, g))
        n -= cross_n
        # Split the category across repos; rotate the start so small quotas spread out.
        order = repo_names[ci % len(repo_names) :] + repo_names[: ci % len(repo_names)]
        per_repo = largest_remainder(
            {r: repo_boost.get(r, 1.0) * (1 + focus_repos.get(r, 0)) for r in order}, n
        )
        for repo in order:
            sig = repo_signals[repo]["signals"]
            t0 = repo_signals[repo].get("t0")
            for t in stories_in[category]:
                if (repo, t) not in leads_by:
                    wide = leads_for(t, sig, t0, limit=1000 if focus_dirs else MAX_LEADS_PER_TYPE)
                    leads_by[(repo, t)] = focused_first(wide)[:MAX_LEADS_PER_TYPE]
            usable = [t for t in stories_in[category] if leads_by[(repo, t)]] or list(
                stories_in[category]
            )
            for _ in range(per_repo[repo]):
                fmt = _pick_format(formats_in[category], used, spent, max_illustrations, fmt_boost)
                used[fmt] = used.get(fmt, 0) + 1
                spent += ILLUSTRATION_COST.get(fmt, 0)
                story = min(
                    usable,
                    key=lambda t: (
                        (story_used.get(t, 0) + 1) / story_boost.get(t, 1.0),
                        usable.index(t),
                    ),
                )
                story_used[story] = story_used.get(story, 0) + 1
                slots.append((repo, category, story, fmt, None))

    # 2. Pack slots into as few packets as possible per (repo or group, model tier).
    packets: list[Packet] = []
    slot_no = 0
    units = [(r, None, [r]) for r in repo_names] + [
        (rs[0], g, rs) for g, rs in cross_groups.items()
    ]
    for repo, grp, unit_repos in units:
        for cheap in (True, False):
            group = [
                s
                for s in slots
                if s[0] == repo
                and s[4] == grp
                and (s[2] in CONCRETE_TYPES and s[3] in HAIKU_FORMATS) == cheap
            ]
            for start in range(0, len(group), packet_size):
                chunk = group[start : start + packet_size]
                types = list(dict.fromkeys(t for _, _, t, _, _ in chunk))
                if grp:
                    plead = [f"[{t}] {line}" for t in types for line in cross_by_group[grp][t]]
                else:
                    plead = [f"[{t}] {line}" for t in types for line in leads_by[(repo, t)]]
                packets.append(
                    Packet(
                        id=f"p{len(packets) + 1}",
                        categories=list(dict.fromkeys(c for _, c, _, _, _ in chunk)),
                        repo=repo,
                        count=len(chunk),
                        story_types=types,
                        suggested_model="haiku" if cheap else "sonnet",
                        tones=tone_pool[slot_no : slot_no + len(chunk)],
                        personas=[
                            persona_cycle[(slot_no + i) % len(persona_cycle)]
                            for i in range(len(chunk))
                        ],
                        leads=plead or ["No precomputed leads: explore with list_dir and git_log."],
                        formats=[f for _, _, _, f, _ in chunk],
                        repos=list(unit_repos),
                    )
                )
                slot_no += len(chunk)
    return Brief(
        count=count,
        quotas=quotas,
        tone_quotas=tone_quotas,
        packets=packets,
        recent=list(recent),
        mix_evidence=(evidence or 0) if learned else None,
        rules=rules,
        focus=focus,
        unavailable=[f for f in CATEGORY_FORMATS_FLAT if f in set(unavailable_formats)],
    )


_FORMAT_SECTION = re.compile(r"^### Format: `(\w+)`", re.MULTILINE)


def _format_sections() -> dict[str, str]:
    from importlib.resources import files

    text = (files("codescroll") / "prompts" / "formats.md").read_text()
    marks = list(_FORMAT_SECTION.finditer(text))
    return {
        m.group(1): text[m.start() : marks[i + 1].start() if i + 1 < len(marks) else len(text)]
        for i, m in enumerate(marks)
    }


def guidance_markdown(
    personas: dict, formats=None, meme_templates: dict | None = None, mascots: dict | None = None
) -> str:
    """Card-writing rules for a packet subagent: base guidance plus the format sections.

    `formats=None` includes every format section; a list includes only those (`[]` is base only).
    """
    from importlib.resources import files

    text = (files("codescroll") / "prompts" / "generate.md").read_text()
    roster = "\n".join(f"- `@{p.handle}` ({p.name}): {p.voice}" for p in personas.values())
    out = text.replace("{personas}", roster)
    sections = _format_sections()
    wanted = list(sections) if formats is None else list(dict.fromkeys(formats))
    chosen = [sections[f].strip() for f in wanted if f in sections]
    if not chosen:
        return out
    tpl = "\n".join(
        f"- `{t.id}` ({t.lines} lines): {t.hint}" for t in (meme_templates or {}).values()
    )
    masc = "\n".join(f"- `{m.name}` (repo {m.repo or 'none'})" for m in (mascots or {}).values())
    body = "\n\n".join(chosen).replace("{meme_templates}", tpl or "(none configured)")
    body = body.replace("{mascots}", masc or "(none configured)")
    return out.rstrip() + "\n\n## Format sections\n\n" + body + "\n"

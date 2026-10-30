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


def leads_for(story_type: str, sig: dict, t0: int | None = None) -> list[str]:
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
    return out[:MAX_LEADS_PER_TYPE]


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


@dataclass
class Brief:
    count: int
    quotas: dict[str, int]
    tone_quotas: dict[str, int]
    packets: list = field(default_factory=list)
    recent: list = field(default_factory=list)
    mix_evidence: int | None = None  # rewards behind a learned mix; None means default mix

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
        if self.recent:
            out += ["", "## Recently posted (do not repeat these stories)", ""]
            out += [f"- [{r['story_type']}] {r['hook']}" for r in self.recent]
        for pk in self.packets:
            out += [
                "",
                f"## Packet {pk.id}: {pk.count} card(s) from repo `{pk.repo}`",
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


def _pick_format(category: str, used: dict[str, int], spent: int, budget: int) -> str:
    """Least-used format of the category that still fits the illustration budget."""
    options = CATEGORY_FORMATS[category]
    fits = [f for f in options if spent + ILLUSTRATION_COST.get(f, 0) <= budget] or [
        f for f in options if f not in ILLUSTRATION_COST
    ]
    return min(fits, key=lambda f: (used.get(f, 0), options.index(f)))


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
) -> Brief:
    if not repo_signals:
        raise ValueError("no repos to build a brief from")
    learned = bool(category_shares) and evidence != 0  # no rewards: keep the default mix
    source = category_shares if learned else defaults.get("categories", {})
    cats = {k: w for k, w in source.items() if k in CATEGORY_STORIES}
    quotas = largest_remainder(cats, count)
    if learned and count >= len(cats):
        for k in [k for k, v in quotas.items() if v < 1]:
            donor = max(quotas, key=lambda c: (quotas[c], c))
            quotas[donor] -= 1
            quotas[k] = 1
    tone_quotas = largest_remainder(defaults.get("tones", {}), count)
    tone_pool = _interleave(tone_quotas)
    repo_names = sorted(repo_signals)
    persona_cycle = list(personas) or list(DEFAULT_PERSONAS)

    # 1. Allocate every card slot to (repo, category, story_type, format).
    slots: list[tuple[str, str, str, str]] = []
    used: dict[str, int] = {}
    spent = 0
    leads_by: dict[tuple[str, str], list[str]] = {}
    for ci, (category, n) in enumerate(sorted(quotas.items(), key=lambda kv: (-kv[1], kv[0]))):
        if not n:
            continue
        # Split the category across repos; rotate the start so small quotas spread out.
        order = repo_names[ci % len(repo_names) :] + repo_names[: ci % len(repo_names)]
        per_repo = largest_remainder({r: 1.0 for r in order}, n)
        for repo in order:
            sig = repo_signals[repo]["signals"]
            t0 = repo_signals[repo].get("t0")
            for t in CATEGORY_STORIES[category]:
                leads_by.setdefault((repo, t), leads_for(t, sig, t0))
            usable = [t for t in CATEGORY_STORIES[category] if leads_by[(repo, t)]] or list(
                CATEGORY_STORIES[category]
            )
            for i in range(per_repo[repo]):
                fmt = _pick_format(category, used, spent, max_illustrations)
                used[fmt] = used.get(fmt, 0) + 1
                spent += ILLUSTRATION_COST.get(fmt, 0)
                slots.append((repo, category, usable[i % len(usable)], fmt))

    # 2. Pack slots into as few packets as possible per (repo, model tier).
    packets: list[Packet] = []
    slot_no = 0
    for repo in repo_names:
        for cheap in (True, False):
            group = [
                s
                for s in slots
                if s[0] == repo and (s[2] in CONCRETE_TYPES and s[3] in HAIKU_FORMATS) == cheap
            ]
            for start in range(0, len(group), packet_size):
                chunk = group[start : start + packet_size]
                types = list(dict.fromkeys(t for _, _, t, _ in chunk))
                plead = [f"[{t}] {line}" for t in types for line in leads_by[(repo, t)]] or [
                    "No precomputed leads: explore with list_dir and git_log."
                ]
                packets.append(
                    Packet(
                        id=f"p{len(packets) + 1}",
                        categories=list(dict.fromkeys(c for _, c, _, _ in chunk)),
                        repo=repo,
                        count=len(chunk),
                        story_types=types,
                        suggested_model="haiku" if cheap else "sonnet",
                        tones=tone_pool[slot_no : slot_no + len(chunk)],
                        personas=[
                            persona_cycle[(slot_no + i) % len(persona_cycle)]
                            for i in range(len(chunk))
                        ],
                        leads=plead,
                        formats=[f for _, _, _, f in chunk],
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

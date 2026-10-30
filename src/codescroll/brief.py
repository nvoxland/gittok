"""Turns analysis signals and the default mix into a brief for the agent (SPEC §10.3).

The brief is split into work packets so a cheap subagent can write each packet's
cards without any other context.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Story types that can be rendered in M1, by default-mix category.
CATEGORY_STORIES: dict[str, tuple[str, ...]] = {
    "git_drama": (
        "commit_drama",
        "hot_spot",
        "archaeology",
        "rip",
        "ancient_todo",
        "secret_couples",
        "whose_code",
    ),
    "illustrated_explainers": ("what_it_does", "journey", "analogy"),
    "code": ("snippet_callouts", "cursed_clever_line"),
    "cross_repo_and_recent": ("before_after", "new_arrival"),
}


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


def leads_for(story_type: str, sig: dict) -> list[str]:
    """Human-readable leads for one story type, drawn from precomputed signals."""
    churn_files = sig.get("churn", {}).get("files", {})
    hot = churn_files.get("90") or churn_files.get("365") or []
    wide = churn_files.get("365") or hot
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
        for c in sig.get("fix_chains", []):
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
        ]
    elif story_type == "rip":
        out += [
            f"{d['path']} born {_date(d.get('born_ts'))} ({_sha(d.get('born_sha'))}), died "
            f"{_date(d['died_ts'])} ({_sha(d['died_sha'])}, {d['died_author']}): "
            f'"{d["cause"]}", lived {d.get("lived_days", "?")} days'
            for d in sig.get("deleted_paths", [])
        ]
    elif story_type == "ancient_todo":
        out += [
            f"{t['path']}:{t['line']} {t['tag']} from {_date(t['ts'])} ({t['author']}, "
            f"{_sha(t['sha'])}): {t['text'].strip()[:80]}"
            for t in sig.get("todo_ages", [])
        ]
    elif story_type == "secret_couples":
        pairs = sorted(sig.get("co_change", []), key=lambda c: c.get("same_dir", False))
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
        ]
    elif story_type == "before_after":
        recent = sig.get("commits_since", {}).get("commits", [])
        out += [
            f'recent commit {_sha(c["sha"])} ({_date(c["ts"])}, {c["author"]}): "{c["subject"]}"'
            for c in recent
        ]
        for c in sig.get("fix_chains", []):
            x = c["commits"][-1]
            out.append(f'fix {_sha(x["sha"])} on {c["path"]}: "{x["subject"]}"')
    else:  # explanatory types: point at central, much-edited files
        out += [f"{f['path']} ({f['commits']} commits in the last year)" for f in wide]
    return out[:MAX_LEADS_PER_TYPE]


@dataclass
class Packet:
    id: str
    category: str
    repo: str
    count: int
    story_types: list[str]
    suggested_model: str
    tones: list[str]
    personas: list[str]
    leads: list[str]


@dataclass
class Brief:
    count: int
    quotas: dict[str, int]
    tone_quotas: dict[str, int]
    packets: list = field(default_factory=list)
    recent: list = field(default_factory=list)

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
        out = [
            f"# Brief: Make {self.count} cards",
            "",
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
                f"## Packet {pk.id}: {pk.count} {pk.category} card(s) from repo `{pk.repo}`",
                "",
                f"- suggested model: {pk.suggested_model}",
                f"- story types: {', '.join(pk.story_types)}",
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


def build_brief(*, repo_signals, defaults, personas, count, packet_size, recent) -> Brief:
    cats = {k: w for k, w in defaults.get("categories", {}).items() if k in CATEGORY_STORIES}
    quotas = largest_remainder(cats, count)
    tone_quotas = largest_remainder(defaults.get("tones", {}), count)
    tone_pool = _interleave(tone_quotas)
    repo_names = sorted(repo_signals)
    persona_cycle = list(personas)

    packets: list[Packet] = []
    slot_no = 0
    for ci, (category, n) in enumerate(sorted(quotas.items(), key=lambda kv: (-kv[1], kv[0]))):
        if not n:
            continue
        repo = repo_names[ci % len(repo_names)]
        sig = repo_signals[repo]["signals"]
        leads = {t: leads_for(t, sig) for t in CATEGORY_STORIES[category]}
        usable = [t for t in CATEGORY_STORIES[category] if leads[t]] or list(
            CATEGORY_STORIES[category]
        )
        slots = [usable[i % len(usable)] for i in range(n)]
        # Group cheap and expensive story types into separate packets.
        for concrete in (True, False):
            group = [t for t in slots if (t in CONCRETE_TYPES) == concrete]
            for start in range(0, len(group), packet_size):
                chunk = group[start : start + packet_size]
                types = list(dict.fromkeys(chunk))
                plead = [f"[{t}] {line}" for t in types for line in leads[t]] or [
                    "No precomputed leads: explore with list_dir and git_log."
                ]
                packets.append(
                    Packet(
                        id=f"p{len(packets) + 1}",
                        category=category,
                        repo=repo,
                        count=len(chunk),
                        story_types=types,
                        suggested_model="haiku" if concrete else "sonnet",
                        tones=tone_pool[slot_no : slot_no + len(chunk)],
                        personas=[
                            persona_cycle[(slot_no + i) % len(persona_cycle)]
                            for i in range(len(chunk))
                        ],
                        leads=plead,
                    )
                )
                slot_no += len(chunk)
    return Brief(
        count=count,
        quotas=quotas,
        tone_quotas=tone_quotas,
        packets=packets,
        recent=list(recent),
    )


def guidance_markdown(personas: dict) -> str:
    """Card-writing rules handed to each packet subagent (from prompts/generate.md)."""
    from importlib.resources import files

    text = (files("codescroll") / "prompts" / "generate.md").read_text()
    roster = "\n".join(f"- `@{p.handle}` ({p.name}): {p.voice}" for p in personas.values())
    return text.replace("{personas}", roster)

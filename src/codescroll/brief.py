"""Turns analysis signals and the default mix into a brief for the agent (SPEC §10.3).

The brief is split into work packets so a cheap subagent can write each packet's
cards without any other context.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace

from codescroll import candidates, knowledge, validator

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

# Formats that suit each story type (docs/formats.md), 2 to 4 each. The writer picks one; the
# packet lists them best first. A card whose format is not in its story type's list is
# rejected (`format_not_allowed`), unless the packet named it for a variant. `chart` appears
# only where a server chart kind shows the story's data: hot_spot (top_churn_files),
# secret_couples (co_change), whose_code (author_shares).
STORY_FORMATS: dict[str, tuple[str, ...]] = {
    "rip": ("text_post", "breaking_news", "comic", "meme"),
    "hot_spot": ("chart", "hot_take", "text_meme"),
    "commit_drama": ("breaking_news", "group_chat", "text_meme", "meme"),
    "archaeology": ("code_card", "iceberg", "thread"),
    "ancient_todo": ("code_card", "horoscope", "meme"),
    "secret_couples": ("group_chat", "chart", "text_meme"),
    "whose_code": ("chart", "tier_list", "text_post"),
    "what_it_does": ("code_card", "dating_profile", "eli5", "thread"),
    "journey": ("day_in_life", "thread", "comic", "diagram"),
    "analogy": ("mascot_scene", "comic", "eli5"),
    "snippet_callouts": ("code_card", "flags", "eli5"),
    "cursed_clever_line": ("code_card", "hot_take", "meme"),
    "before_after": ("glow_up", "code_card", "breaking_news"),
    "new_arrival": ("breaking_news", "dating_profile", "code_card"),
    "spot_the_bug": ("quiz",),
    "guess_who": ("quiz",),
    "guess_when": ("quiz",),
    "quiz": ("quiz",),
    "this_or_that": ("quiz",),
    "ripple": ("breaking_news", "text_post", "thread", "group_chat"),
    "drift_alert": ("breaking_news", "text_post", "listicle"),
    "weekly_recap": ("listicle", "thread", "text_post", "iceberg"),
}

SPOT = "spot_the_bug"

# A slot's category still leans its format list: its own formats count as this much less used.
HOME_FACTOR = 2.0

CATEGORY_FORMATS_FLAT = tuple(dict.fromkeys(f for fs in CATEGORY_FORMATS.values() for f in fs))

# Illustrations each format costs against settings.render.max_illustrations_per_run.
# A comic has 2 or 3 panels (one illustration each); the brief reserves the worst case, 3.
ILLUSTRATION_COST = {"mascot_scene": 1, "comic": 3}

# Formats that draw an image (meme, illustration, comic, chart, diagram); the image share
# target (defaults visual_mix.image_min_share) counts these.
IMAGE_KINDS = frozenset({"meme", "illustration", "comic", "chart", "diagram"})
IMAGE_FORMATS = frozenset(
    f
    for f, k in validator.FORMAT_KIND.items()
    if IMAGE_KINDS & set((k,) if isinstance(k, str) else k)
)

# Formats a haiku can write when the story type is concrete. Everything else needs sonnet.
HAIKU_FORMATS = frozenset(
    {
        "meme",
        "text_meme",
        "chart",
        "breaking_news",
        "horoscope",
        "flags",
        "tier_list",
        "code_card",
        "text_post",
    }
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

# Story types whose leads are rated candidates (candidate_leads.py), never signals. With no
# candidate for a type, the brief skips the type.
CANDIDATE_STORIES = (
    "what_it_does",
    "journey",
    "analogy",
    "snippet_callouts",
    "cursed_clever_line",
    "quiz",
    "this_or_that",
    "guess_who",
    "guess_when",
)


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


# Dirs that hold no code worth an intro: hidden dirs, tests, fixtures, recorded HTTP, snapshots,
# vendored or generated code, docs. One list, used for intro slots (candidates.SKIP_PATH covers
# hidden and vendored dirs for the miners).
_NON_CODE_DIR = re.compile(
    r"^(\.[^/]*|tests?|specs?|__tests__|fixtures?|cassettes?|snapshots?|__snapshots__|mocks?"
    r"|__mocks__|testdata|vendor|vendored|third_party|generated|gen|dist|build|target"
    r"|docs?|documentation|node_modules)$",
    re.IGNORECASE,
)


def code_path(path: str) -> bool:
    """True when no parent dir of `path` is hidden, test, fixture, vendored, generated or docs."""
    dirs = path.split("/")[:-1]
    return not any(_NON_CODE_DIR.match(d) for d in dirs) and not candidates.SKIP_PATH.search(path)


_DOC_SUFFIX = re.compile(r"\.(md|markdown|rst|txt|adoc|log|csv)$", re.IGNORECASE)


def code_file(path: str) -> bool:
    """True for a source file in a code dir: `code_path`, and not a doc or text file."""
    return code_path(path) and not _DOC_SUFFIX.search(path)


def _real_dir(d: str) -> bool:
    """A dir `whose_code` may name: not the root, and a code dir (`code_path`)."""
    return d not in ("", ".") and code_path(f"{d}/x")


def _old(ts, t0) -> bool:
    return t0 is None or (ts or t0) <= t0 - ANCIENT_DAYS * 86400


def _fix_hunks(sig: dict) -> dict[tuple[str, str], dict]:
    return {(h["sha"], h["path"]): h for h in sig.get("fix_hunks") or []}


def _ranges(ranges: list) -> str:
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in ranges[:4])


@dataclass(frozen=True)
class Lead:
    """One lead: its text plus the coordinates `materials` uses to attach evidence.

    `kind` is "commit" (a sha, maybe with a path), "path" (a file, maybe with a line span),
    or "none" (a directory, pair, or cross-repo lead: no single place to look).
    """

    story_type: str
    repo: str
    kind: str
    commit: str | None = None
    path: str | None = None
    lines: tuple[int, int] | None = None
    text: str = ""
    id: int | None = None  # ledger row id, when the lead came from the ledger
    key: str | None = None  # synthetic ledger key for leads with no single identity in history
    intro: str | None = None  # set to the dir when this lead is an intro slot's (reader new to it)


def leads_for(
    story_type: str, sig: dict, t0: int | None = None, limit: int = MAX_LEADS_PER_TYPE
) -> list[str]:
    """Human-readable leads for one story type, drawn from precomputed signals."""
    return [x.text for x in lead_refs_for(story_type, sig, t0, limit)]


def lead_refs_for(
    story_type: str,
    sig: dict,
    t0: int | None = None,
    limit: int = MAX_LEADS_PER_TYPE,
    repo: str = "",
) -> list[Lead]:
    """Leads for one story type with coordinates, drawn from precomputed signals.

    Generated files and lockfiles are never leads. "Ancient" stories need material
    older than ANCIENT_DAYS before the repo's last commit (t0).
    """

    def lead(text, kind="none", **coords) -> Lead:
        return Lead(story_type, repo, kind, text=text, **coords)

    def at_commit(text, sha, path=None) -> Lead:
        return lead(text, "commit", commit=sha, path=path)

    def at_path(text, path, line=None, key=None) -> Lead:
        return lead(text, "path", path=path, lines=(line, line) if line else None, key=key)

    churn_files = sig.get("churn", {}).get("files", {})
    hot = [f for f in churn_files.get("90") or churn_files.get("365") or [] if _useful(f["path"])]
    out: list[Lead] = []
    if story_type == "hot_spot":
        out += [
            at_path(
                f"{f['path']}: {f['commits']} commits, {f['lines']} lines changed (90d)", f["path"]
            )
            for f in hot
        ]
        dirs = sig.get("churn", {}).get("dirs", {}).get("90", [])
        out += [
            lead(f"dir {d['path']}/: {d['commits']} commits (90d)", key=f"dir:{d['path']}")
            for d in dirs[:2]
        ]
    elif story_type == "commit_drama":
        for r in sig.get("reverts", []):
            out.append(
                at_commit(
                    f"revert {_sha(r['sha'])} ({_date(r['ts'])}, {r['author']}) undid "
                    f'{_sha(r.get("reverted_sha"))} "{r.get("reverted_subject", "?")}"',
                    r["sha"],
                )
            )
        for c in (c for c in sig.get("fix_chains", []) if _useful(c["path"])):
            subj = " -> ".join(f'{_sha(x["sha"])} "{x["subject"]}"' for x in c["commits"])
            out.append(
                at_commit(f"fix chain on {c['path']}: {subj}", c["commits"][-1]["sha"], c["path"])
            )
        for h in sig.get("huge_diffs", []):
            out.append(
                at_commit(
                    f'huge diff {_sha(h["sha"])} "{h["subject"]}" ({h["lines"]} lines, '
                    f"{h['author']}, {_date(h['ts'])})",
                    h["sha"],
                )
            )
        for n in sig.get("commit_times", {}).get("late_night", []):
            out.append(
                at_commit(
                    f"late-night commit {_sha(n['sha'])} at {n['local_hour']:02d}:xx by "
                    f'{n["author"]}: "{n["subject"]}"',
                    n["sha"],
                )
            )
    elif story_type == "archaeology":
        out += [
            at_path(
                f"{o['path']}:{o['line']} from {_date(o['ts'])} ({o['author']}, {_sha(o['sha'])}): "
                f"{o['text'].strip()[:80]}",
                o["path"],
                o["line"],
            )
            for o in sig.get("oldest_lines", [])
            if _old(o["ts"], t0) and _useful(o["path"])
        ]
    elif story_type == "rip":
        out += [
            at_commit(
                f"{d['path']} born {_date(d.get('born_ts'))} ({_sha(d.get('born_sha'))}), died "
                f"{_date(d['died_ts'])} ({_sha(d['died_sha'])}, {d['died_author']}): "
                f'"{d["cause"]}", lived {d.get("lived_days", "?")} days',
                d["died_sha"],
                d["path"],
            )
            for d in sig.get("deleted_paths", [])
            if _useful(d["path"])
        ]
    elif story_type == "ancient_todo":
        out += [
            at_path(
                f"{t['path']}:{t['line']} {t['tag']} from {_date(t['ts'])} ({t['author']}, "
                f"{_sha(t['sha'])}): {t['text'].strip()[:80]}",
                t["path"],
                t["line"],
            )
            for t in sig.get("todo_ages", [])
            if _old(t["ts"], t0) and _COMMENT_TODO.search(t["text"]) and _useful(t["path"])
        ]
    elif story_type == "secret_couples":
        pairs = sorted(
            (c for c in sig.get("co_change", []) if _useful(c["a"]) and _useful(c["b"])),
            key=lambda c: c.get("same_dir", False),
        )
        out += [
            at_path(
                f"{c['a']} + {c['b']}: changed together {c['count']} times "
                f"(jaccard {c['jaccard']})",
                c["a"],
                key=f"pair:{c['a']}|{c['b']}",
            )
            for c in pairs
        ]
    elif story_type == "whose_code":
        for d, authors in sig.get("author_shares", {}).get("by_dir", {}).items():
            if not _real_dir(d):
                continue
            top = ", ".join(f"{a['author']} {round(a['share'] * 100)}%" for a in authors[:3])
            out.append(lead(f"dir {d}/: {top}", key=f"dir:{d}"))
    elif story_type == "new_arrival":
        out += [
            at_commit(
                f"{n['path']} added {_date(n['ts'])} in {_sha(n['sha'])} by {n['author']}: "
                f'"{n["subject"]}"',
                n["sha"],
                n["path"],
            )
            for n in sig.get("new_files", [])
            if _useful(n["path"])
        ]
    elif story_type == "spot_the_bug":
        hunks = _fix_hunks(sig)
        for c in (c for c in sig.get("fix_chains", []) if _useful(c["path"])):
            for x in c["commits"]:
                h = hunks.get((x["sha"], c["path"]))
                where = (
                    f"visual commit (first parent) {_sha(h['parent'])}, "
                    f"changed lines {_ranges(h['ranges'])}"
                    if h
                    else "the visual is the file at that fix's first parent"
                )
                out.append(
                    at_commit(
                        f'fix {_sha(x["sha"])} on {c["path"]}: "{x["subject"]}" ({where})',
                        x["sha"],
                        c["path"],
                    )
                )
    elif story_type == "before_after":
        recent = sig.get("commits_since", {}).get("commits", [])
        out += [
            at_commit(
                f"recent commit {_sha(c['sha'])} ({_date(c['ts'])}, {c['author']}): "
                f'"{c["subject"]}"',
                c["sha"],
            )
            for c in recent
        ]
        hunks = _fix_hunks(sig)
        for c in (c for c in sig.get("fix_chains", []) if _useful(c["path"])):
            x = c["commits"][-1]
            h = hunks.get((x["sha"], c["path"]))
            before = (
                f" (before: {_sha(h['parent'])}, changed lines {_ranges(h['ranges'])})" if h else ""
            )
            out.append(
                at_commit(
                    f'fix {_sha(x["sha"])} on {c["path"]}: "{x["subject"]}"{before}',
                    x["sha"],
                    c["path"],
                )
            )
    # CANDIDATE_STORIES come from rated candidates (candidate_leads), not from churn.
    return out[:limit]


# --- Cross-repo leads (SPEC 6.4) -------------------------------------------

CROSS_CATEGORY = "cross_repo_and_recent"
CROSS_STORIES = ("ripple", "drift_alert", "weekly_recap")
CROSS_FORMATS = ("breaking_news", "text_post", "listicle", "thread", "iceberg", "group_chat")
DAY_SECONDS = 86400
RIPPLE_DAYS = 3
RECAP_DAYS = 7

_TICKET = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")  # JIRA style only; bare #123 is per repo
_WORD = re.compile(r"[a-z][a-z0-9]{2,}")
_STOP = frozenset(
    """the and for with from into onto that this these those not but are was were has have had
    its use uses used using add adds added adding fix fixes fixed fixing update updates updated
    remove removes removed change changes changed make makes made get gets set sets new old
    feat chore refactor test tests docs doc merge revert wip again more some also now when then
    than out off all any can will should per via call calls
    pre commit follow read only opt built e2e non self multi auto end back front check run
    ready work code file files page fixes bump wire tweak minor small""".split()
)


def _tokens(subject: str) -> tuple[set[str], set[str]]:
    """(ticket-like tokens, significant words) of a commit subject, lowercased."""
    low = subject.lower()
    ids = {t.lower() for t in _TICKET.findall(subject)}
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
GREP_MAX_BYTES = 100_000
DIFF_MAX_BYTES = 1_000_000


def _grep_files(member: dict, ident: str, limit: int = 3) -> list[str]:
    """Files at the repo's analyzed head that mention `ident` (fixed string); [] if unknown."""
    from codescroll import gitq

    path, head = member.get("path"), member.get("head_sha")
    if not path or not head:
        return []
    try:
        raw = gitq.run_bytes(
            path,
            "grep",
            "-l",
            "-F",
            "-w",
            "-I",
            "-e",
            ident,
            head,
            "--",
            ok_codes=(0, 1),
            max_bytes=GREP_MAX_BYTES,
        )[1].decode(errors="replace")
    except gitq.GitError:
        return []
    prefix = f"{head}:"
    files = [ln.removeprefix(prefix) for ln in raw.splitlines() if ln]
    return [f for f in files if _useful(f)][:limit]


def _changed_since(member: dict, ts: int) -> set[str] | None:
    """Files changed at the analyzed head since the last commit at or before `ts`.

    None means unknown or everything (no older commit); callers treat that as "touched".
    """
    from codescroll import gitq

    path, head = member.get("path"), member.get("head_sha")
    if not path or not head:
        return None
    try:
        old = gitq.run(path, "rev-list", "-1", f"--before={ts}", head).strip()
        if not old:
            return None
        raw = gitq.run(path, "diff", "--name-only", f"{old}..{head}", max_bytes=DIFF_MAX_BYTES)
    except gitq.GitError:
        return None
    return {ln for ln in raw.splitlines() if ln}


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
                changed = _changed_since(members[rb], ca["ts"])
                if changed is None:  # no full list: fall back to the (truncated) recent list
                    changed = {
                        f for c in recent[rb] if c["ts"] >= ca["ts"] for f in c.get("files", [])
                    }
                if set(hits) & changed:
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


MENU_SIZE = 3  # meme templates offered per meme card


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
    lead_refs: list[dict] = field(default_factory=list)  # Lead coordinates, same order as leads
    formats: list[str] = field(default_factory=list)  # per card: the preferred format
    card_stories: list[str] = field(default_factory=list)  # per card: its story type
    allowed: list[list[str]] = field(default_factory=list)  # per card: formats to pick from
    images: int = 0  # cards that should use an image format, where their lists have one
    # Per card: a menu of candidate meme templates (best first), or None for other formats.
    templates: list[list[str] | None] = field(default_factory=list)
    repos: list[str] = field(default_factory=list)  # all repos the packet covers; [0] is `repo`
    intro: int = 0  # cards of this packet that must use an intro-flagged lead


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
    intro: list = field(default_factory=list)  # (repo, dir, cards) reserved for unseen dirs

    def to_dict(self) -> dict:
        return {
            "count": self.count,
            "quotas": self.quotas,
            "tone_quotas": self.tone_quotas,
            "packets": [asdict(p) for p in self.packets],
            "recent": self.recent,
        }

    def summary_markdown(self) -> str:
        """Mix, rules, and skipped formats: what the driver needs, without packets."""
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
        out += self._focus_lines()
        if self.intro:
            dirs = ", ".join(f"{d}/ ({n})" for _, d, n in self.intro)
            out += [f"Intro: the reader has not seen these dirs yet: {dirs}. Explain from zero."]
        return "\n".join(out) + "\n"

    def _focus_lines(self) -> list[str]:
        out = []
        for repo, d, slots in self.focus:
            where = f"{d}/" if d else f"repo {repo}"
            out.append(f"Focus: {where} ({slots} slots): lead with it; its leads come first.")
        return out

    def _recent_lines(self) -> list[str]:
        if not self.recent:
            return []
        out = ["", "## Recently posted (do not repeat these stories)", ""]
        return out + [f"- [{r['story_type']}] {r['hook']}" for r in self.recent]

    def _packet_section(self, pk) -> list[str]:
        names = pk.repos if len(pk.repos) > 1 else [pk.repo]
        where = f"repo{'s' * (len(names) > 1)} " + ", ".join(f"`{r}`" for r in names)
        out = [
            f"## Packet {pk.id}: {pk.count} card(s) from {where}",
            "",
            f"- suggested model: {pk.suggested_model}",
            f"- categories: {', '.join(pk.categories)}",
            f"- story types: {', '.join(pk.story_types)}",
            f"- tones, one per card: {', '.join(pk.tones)}",
            f"- personas, one per card: {', '.join(pk.personas)}",
            "- leads:",
        ]
        if pk.allowed:
            out.insert(-1, "- cards (story type, then the formats to pick from):")
            for n, (story, fs) in enumerate(zip(pk.card_stories, pk.allowed, strict=True), 1):
                if len(fs) == 1:
                    out.insert(-1, f"  {n}. {story}: use `{fs[0]}`")
                else:
                    shown = ", ".join(f"{f} (preferred)" if i == 0 else f for i, f in enumerate(fs))
                    out.insert(-1, f"  {n}. {story}: pick one: {shown}")
        if pk.images:
            out.insert(
                -1,
                f"- images: at least {pk.images} of the cards should use an image format "
                f"({', '.join(sorted(IMAGE_FORMATS))}) where their list has one",
            )
        if pk.intro:
            out.insert(
                -1,
                f"- intro cards: {pk.intro} of the cards must use the leads marked `intro` "
                "(one card each)",
            )
        if any(pk.templates):
            menus = "; ".join("|".join(m) for m in pk.templates if m)
            out.insert(-1, f"- meme templates to choose from (one menu per meme card): {menus}")
        return out + [f"  - {line}" for line in pk.leads]

    def packet_markdown(self, packet_id: str) -> str:
        """One packet for its writer: the packet, focus lines, and stories not to repeat."""
        pk = next((p for p in self.packets if p.id == packet_id), None)
        if pk is None:
            raise KeyError(packet_id)
        focus = self._focus_lines()
        out = self._packet_section(pk) + ([""] + focus if focus else []) + self._recent_lines()
        return "\n".join(out) + "\n"

    def to_markdown(self) -> str:
        out = [self.summary_markdown().rstrip("\n")] + self._recent_lines()
        for pk in self.packets:
            out += [""] + self._packet_section(pk)
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
    """Combined bias per value of a feature, as the slotter multiplies scores.

    boost/prefer use the stored factor (None counts as 1.0: the steering layer stores the
    defaults). focus on a feature without a slot meaning here biases like a boost of 1 + slots.
    """
    out: dict[str, float] = {}
    for r in rules:
        if r["feature"] != feature:
            continue
        if r["type"] in ("boost", "prefer"):
            f = r["factor"] if r.get("factor") is not None else 1.0
        elif r["type"] == "focus":
            f = 1 + (r.get("slots") or 3)
        else:
            continue
        out[r["value"]] = out.get(r["value"], 1.0) * f
    return out


def _banned(rules, feature: str) -> set[str]:
    return {r["value"] for r in rules if r["type"] == "ban" and r["feature"] == feature}


def _caps(rules, feature: str, count: int) -> dict[str, int]:
    """Slot ceilings from `limit` rules, computed like the slotter (share 0 means none)."""
    out: dict[str, int] = {}
    for r in rules:
        if r["type"] == "limit" and r["feature"] == feature and r.get("max_share") is not None:
            cap = 0 if r["max_share"] == 0 else max(1, round(r["max_share"] * count))
            out[r["value"]] = min(cap, out.get(r["value"], cap))
    return out


def _clip(alloc: dict[str, int], room: dict[str, int]) -> dict[str, int]:
    """Cut each key to its room and hand the excess to keys that still have room.

    With no room anywhere the excess stays (a ceiling is best effort, never a short brief).
    """
    out = dict(alloc)
    extra = 0
    for k, r in room.items():
        if k in out and out[k] > r:
            extra += out[k] - r
            out[k] = r
    for _ in range(extra):
        open_ = [k for k in out if k not in room or out[k] < room[k]] or list(out)
        k = min(open_, key=lambda k: (out[k], k))
        out[k] += 1
    return out


def _dir_candidates(value: str, repos) -> list[str]:
    v = value.strip("/")
    return [v] + [v[len(r) + 1 :] for r in repos if v.startswith(r + "/")]


def _line_in_dirs(line: str, dirs: list[str]) -> bool:
    """Does a lead mention a path equal to or under one of `dirs` (path-prefix match)?"""
    for tok in re.findall(r"[\w@.+-]+(?:/[\w@.+-]+)*", line):
        for d in dirs:
            if tok == d or tok.startswith(d + "/"):
                return True
    return False


def _banned_formats(rules) -> set[str]:
    """Formats that can only produce a banned visual kind or template."""
    from codescroll.validator import FORMAT_KIND, TEMPLATE_FORMATS

    kinds, templates = _banned(rules, "visual_kind"), _banned(rules, "template")
    gone = {f for f, k in FORMAT_KIND.items() if set((k,) if isinstance(k, str) else k) <= kinds}
    return gone | (templates & TEMPLATE_FORMATS)


def _banned_stories(rules) -> set[str]:
    gone = set(_banned(rules, "story_type")) | set(_banned(rules, "interactive"))
    if _banned(rules, "difficulty"):
        gone |= set(CATEGORY_STORIES["interactive"])
    return gone


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
    options,
    used: dict[str, int],
    spent: int,
    budget: int,
    boost: dict[str, float] | None = None,
    caps: dict[str, int] | None = None,
    recent: dict[str, int] | None = None,
    weights: dict[str, float] | None = None,
) -> str:
    """Least-used format of the category that still fits the illustration budget.

    A boost factor divides a format's use count, so boosted formats come up more often.
    `weights` are learned per-format factors; they multiply into the boost.
    Ties go to the format used least in recent cards, so runs rotate through the list.
    """
    recent = recent or {}
    boost = boost or {}
    weights = weights or {}
    caps = caps or {}
    options = [f for f in options if used.get(f, 0) < caps.get(f, 1 << 30)] or list(options)
    fits = (
        [f for f in options if spent + ILLUSTRATION_COST.get(f, 0) <= budget]
        or [f for f in options if f not in ILLUSTRATION_COST]
        or list(options)
    )
    return min(
        fits,
        key=lambda f: (
            (used.get(f, 0) + 1) / (boost.get(f, 1.0) * weights.get(f, 1.0)),
            recent.get(f, 0),
            options.index(f),
        ),
    )


def _source_ref(src: dict) -> str:
    """One card source as a short citation: `repo@sha7` or `repo:path:lines`."""
    repo = src.get("repo", "?")
    if src.get("commit"):
        return f"{repo}@{src['commit'][:7]}"
    lines = src.get("lines")
    return f"{repo}:{src.get('path', '?')}" + (f":{lines[0]}-{lines[1]}" if lines else "")


def _variant_pair(v: dict, fmt: str) -> tuple[str, dict]:
    """The packet lead (text, lead_ref) that asks a writer to retell story `v` as `fmt`."""
    told = f'"{v["hook"]}" ' if v.get("hook") else ""
    line = (
        f"[variant] retell {told}({v['story_type']}, first told as "
        f"{', '.join(v['formats_used'])}) in format `{fmt}`; cite the same sources: "
        f"{', '.join(_source_ref(x) for x in v['sources'])}"
    )
    return line, {
        "kind": "variant",
        "story_key": v["story_key"],
        "sources": v["sources"],
        "story_type": v["story_type"],
        "format": fmt,
    }


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
    format_weights: dict[str, float] | None = None,
    ledger: dict[tuple[str, str], list[Lead]] | None = None,
    lead_ok: Callable[[Lead], bool] | None = None,
    variants: list[dict] | None = None,
    variant_max_share: float = 0.2,
    meme_templates: dict | None = None,
    template_weights: dict[str, float] | None = None,
    novelty: dict[str, dict[str, float]] | None = None,
    intro_share: float = 0.0,
    intro_prefer: dict[str, set[str]] | None = None,
    min_spot_the_bug: float = 0.0,
) -> Brief:
    """Build the brief.

    `variants` lists stories that may be retold in a new format (story_key, story_type, repo,
    sources, hook, formats_used), best first. They fill slots that have no fresh lead, at most
    `variant_max_share` x `count` of them. `meme_templates` (id -> MemeTemplate) gives each
    meme slot a menu of 3 candidates: templates that fit its story type, least used first
    (recent cards, plus the first pick of earlier menus in this brief), then higher
    `template_weights`, then list order.

    `novelty` (repo -> dir -> novelty, see knowledge.novelty_map) and `intro_share` reserve
    ceil(count x intro_share) cards for leads from the dirs the reader knows least (novelty at
    least INTRO_MIN_NOVELTY). Those leads are flagged `intro` and go first in their packet.

    `min_spot_the_bug` (a share of `count`) reserves that many spot_the_bug slots before the
    category quotas are used, when some repo has a lead for it. The quota of the interactive
    category grows to hold them.
    """
    if not repo_signals:
        raise ValueError("no repos to build a brief from")
    rules = list(rules or [])
    # Recent cards break ties, so successive runs rotate through formats and story types.
    recent_fmt = Counter(r.get("format") for r in recent if r.get("format"))
    recent_story = Counter(r.get("story_type") for r in recent if r.get("story_type"))
    template_use = Counter(r.get("template") for r in recent if r.get("template"))
    template_ids = list(meme_templates or {})
    t_weight = template_weights or {}

    def template_menu(fmt, story_type):
        if fmt != "meme" or not template_ids:
            return None
        fit = [
            t
            for t in template_ids
            if not meme_templates[t].fits or story_type in meme_templates[t].fits
        ]
        rest = [t for t in template_ids if t not in fit]
        menu: list[str] = []
        for pool in (fit, rest):
            ranked = sorted(
                pool, key=lambda t: (template_use[t], -t_weight.get(t, 0.0), template_ids.index(t))
            )
            menu += ranked[: MENU_SIZE - len(menu)]
        template_use[menu[0]] += 1
        return menu

    # Cross-repo groups: >= 2 repos of one group in this brief. `groups` (name -> repos)
    # overrides the group each analysis carries.
    if groups is None:
        groups = {}
        for r in sorted(repo_signals):
            g = repo_signals[r].get("group")
            if g:
                groups.setdefault(g, []).append(r)
    group_of = {r: g for g, rs in groups.items() for r in rs}
    zero = {
        f: {v for v, c in _caps(rules, f, count).items() if c == 0}
        for f in ("repo", "format", "story_type", "tone")
    }
    gone_repos = _banned(rules, "repo") | zero["repo"]
    gone_groups = _banned(rules, "group")
    repo_signals = {
        r: v
        for r, v in repo_signals.items()
        if r not in gone_repos and group_of.get(r) not in gone_groups
    }
    if not repo_signals:
        raise ValueError("active rules ban every repo")
    groups = {g: [r for r in rs if r in repo_signals] for g, rs in groups.items()}
    gone_formats = (
        set(unavailable_formats)
        | _banned(rules, "format")
        | _banned_formats(rules)
        | zero["format"]
    )
    gone_stories = _banned_stories(rules) | zero["story_type"]
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
    group_boost = _factors(rules, "group")
    fmt_caps = _caps(rules, "format", count)
    story_caps = _caps(rules, "story_type", count)
    repo_caps = _caps(rules, "repo", count)
    weights = format_weights or {}

    def allowed_for(story, category, used, spent, fallback=()):
        """Formats a card of this story type may use, best first; never empty.

        Banned and unavailable formats are dropped; formats at their cap or past the
        illustration budget drop too while others remain. Order: formats of the slot's
        category first, then least used (divided by rule boost x learned weight), then least
        used in recent cards, then list order. With nothing left, the best format of
        `fallback` (the category's) stands in.
        """
        pool = [f for f in STORY_FORMATS.get(story, ()) if f not in gone_formats]
        if not pool:
            return [_pick_format(fallback, used, spent, max_illustrations, fmt_boost, fmt_caps,
                                 recent_fmt, weights)]  # fmt: skip
        pool = [f for f in pool if used.get(f, 0) < fmt_caps.get(f, 1 << 30)] or pool
        pool = (
            [f for f in pool if spent + ILLUSTRATION_COST.get(f, 0) <= max_illustrations]
            or [f for f in pool if f not in ILLUSTRATION_COST]
            or pool
        )
        home = set(CATEGORY_FORMATS.get(category, ()))
        return sorted(
            pool,
            key=lambda f: (
                (used.get(f, 0) + 1)
                / (fmt_boost.get(f, 1.0) * weights.get(f, 1.0) * (HOME_FACTOR if f in home else 1)),
                recent_fmt.get(f, 0),
                STORY_FORMATS[story].index(f),
            ),
        )

    focus = []
    for r in rules:
        if r["type"] == "focus" and r["feature"] in ("repo", "dir"):
            n = r.get("slots") or 3
            focus.append((r["value"], None, n) if r["feature"] == "repo" else (None, r["value"], n))
    prefer_dirs = [
        r["value"]
        for r in rules
        if r["feature"] == "dir" and (r["type"] in ("focus", "boost", "prefer"))
    ]
    ban_dirs = [r["value"] for r in rules if r["type"] == "ban" and r["feature"] == "dir"]
    all_repos = list(repo_signals)

    def focused_first(lines: list[str]) -> list[str]:
        if ban_dirs:
            bad = [d for v in ban_dirs for d in _dir_candidates(v, all_repos)]
            lines = [x for x in lines if not _line_in_dirs(x, bad)]
        want = [d for v in prefer_dirs for d in _dir_candidates(v, all_repos)]
        return sorted(lines, key=lambda x: not _line_in_dirs(x, want))

    def fill_leads(repo, t):
        if (repo, t) in leads_by:
            return
        sig = repo_signals[repo]["signals"]
        # A ledger entry (even an empty one) replaces computing leads.
        wide = (ledger or {}).get((repo, t))
        if wide is None:
            wide = lead_refs_for(
                t,
                sig,
                repo_signals[repo].get("t0"),
                limit=1000 if prefer_dirs or ban_dirs else MAX_LEADS_PER_TYPE,
                repo=repo,
            )
            if lead_ok:  # no ledger rows: still honor cooldown and story blocks
                wide = [x for x in wide if lead_ok(x)]
        ref_by[(repo, t)] = {x.text: x for x in wide}
        leads_by[(repo, t)] = focused_first([x.text for x in wide])[:MAX_LEADS_PER_TYPE]

    learned = bool(category_shares) and evidence != 0  # no rewards: keep the default mix
    source = category_shares if learned else defaults.get("categories", {})
    cats = {k: w for k, w in source.items() if k in live}
    # A category whose story types all need rated candidates is skipped when no repo has one:
    # its cards go to the other categories.
    leads_by: dict[tuple[str, str], list[str]] = {}
    ref_by: dict[tuple[str, str], dict[str, Lead]] = {}  # lead text -> its coordinates

    def starved(category) -> bool:
        stories = stories_in[category]
        if not all(t in CANDIDATE_STORIES for t in stories):
            return False
        for r in repo_signals:
            for t in stories:
                fill_leads(r, t)
        return not any(leads_by[(r, t)] for r in repo_signals for t in stories)

    cats = {k: w for k, w in cats.items() if not starved(k)} or cats
    if not cats:
        raise ValueError("active rules leave no category with a story type and format")
    quotas = largest_remainder(cats, count)
    if learned and count >= len(cats):
        for k in [k for k, v in quotas.items() if v < 1]:
            donor = max(quotas, key=lambda c: (quotas[c], c))
            quotas[donor] -= 1
            quotas[k] = 1
    spot_min = 0
    if min_spot_the_bug > 0 and SPOT in stories_in.get("interactive", ()) and "interactive" in cats:
        for r in repo_signals:
            fill_leads(r, SPOT)
        if any(leads_by[(r, SPOT)] for r in repo_signals):
            spot_min = min(math.ceil(count * min_spot_the_bug - 1e-9), story_caps.get(SPOT, count))
            for _ in range(max(0, spot_min - quotas["interactive"])):
                donors = [c for c in quotas if c != "interactive" and quotas[c] > 0]
                if not donors:
                    break
                quotas[max(donors, key=lambda c: (quotas[c], c))] -= 1
                quotas["interactive"] += 1
    banned_tones = _banned(rules, "tone") | zero["tone"]
    tone_boost = _factors(rules, "tone")
    tones_in = {
        k: w * tone_boost.get(k, 1.0)
        for k, w in defaults.get("tones", {}).items()
        if k not in banned_tones
    }
    tone_quotas = largest_remainder(tones_in or defaults.get("tones", {}), count)
    tone_quotas = _clip(tone_quotas, _caps(rules, "tone", count)) if tones_in else tone_quotas
    tone_pool = _interleave(tone_quotas)
    repo_names = sorted(repo_signals)
    persona_cycle = list(personas) or list(DEFAULT_PERSONAS)
    persona_cycle = [
        p for p in persona_cycle if p not in _banned(rules, "persona")
    ] or persona_cycle
    story_used: dict[str, int] = {}

    cross_groups = {
        g: [r for r in rs if r in repo_signals]
        for g, rs in sorted(groups.items())
        if len([r for r in rs if r in repo_signals]) >= 2
    }
    cross_by_group: dict[str, dict[str, list[str]]] = {}

    # 1. Allocate every card slot to (repo, category, story_type, format, group).
    # `group` is None except for cross-repo slots, whose repo is the group's first repo.
    slots: list[tuple[str, str, str, str, str | None]] = []
    slot_allowed: list[list[str]] = []  # per slot: the formats its writer may pick from
    used: dict[str, int] = {}
    spent = 0
    repo_total: dict[str, int] = {}
    for ci, (category, n) in enumerate(sorted(quotas.items(), key=lambda kv: (-kv[1], kv[0]))):
        if not n:
            continue
        cross_n = 0
        if category == CROSS_CATEGORY:
            cross_fmts = [f for f in CROSS_FORMATS if f not in gone_formats]
            combos = []
            for g, rs in cross_groups.items():
                if g not in cross_by_group:
                    cross_by_group[g] = {
                        t: [x for x in focused_first(ls)]
                        for t, ls in cross_leads({r: repo_signals[r] for r in rs}).items()
                    }
                    cross_by_group[g] = {t: ls for t, ls in cross_by_group[g].items() if ls}
                combos += [
                    (g, t)
                    for t in CROSS_STORIES
                    if t not in gone_stories and cross_by_group[g].get(t)
                ]
            if combos and cross_fmts:
                cross_n = min(-(-n // 2), len(combos))
                for _ in range(cross_n):
                    open_gt = [
                        gt
                        for gt in combos
                        if story_used.get(gt[1], 0) < story_caps.get(gt[1], 1 << 30)
                    ] or combos
                    g, t = min(
                        open_gt,
                        key=lambda gt: (
                            (story_used.get(gt[1], 0) + 1) / story_boost.get(gt[1], 1.0),
                            CROSS_STORIES.index(gt[1]),
                            gt[0],
                        ),
                    )
                    combos.remove((g, t))
                    allowed = allowed_for(t, category, used, spent, cross_fmts)
                    fmt = allowed[0]
                    slot_allowed.append(allowed)
                    used[fmt] = used.get(fmt, 0) + 1
                    spent += ILLUSTRATION_COST.get(fmt, 0)
                    story_used[t] = story_used.get(t, 0) + 1
                    lead_repo = cross_groups[g][0]
                    repo_total[lead_repo] = repo_total.get(lead_repo, 0) + 1
                    slots.append((lead_repo, category, t, fmt, g))
        n -= cross_n
        # Split the category across repos; rotate the start so small quotas spread out.
        order = repo_names[ci % len(repo_names) :] + repo_names[: ci % len(repo_names)]
        only_candidates = all(t in CANDIDATE_STORIES for t in stories_in[category])
        for r in order:
            for t in stories_in[category]:
                fill_leads(r, t)
        per_repo = largest_remainder(
            {
                r: 0.0  # no rated candidate in this repo: its share goes to the other repos
                if only_candidates and not any(leads_by[(r, t)] for t in stories_in[category])
                else repo_boost.get(r, 1.0) * group_boost.get(group_of.get(r), 1.0)
                for r in order
            },
            n,
        )
        per_repo = _clip(
            per_repo, {r: max(0, c - repo_total.get(r, 0)) for r, c in repo_caps.items()}
        )
        for r, k in per_repo.items():
            repo_total[r] = repo_total.get(r, 0) + k
        for repo in order:
            for t in stories_in[category]:
                fill_leads(repo, t)
            has_leads = [t for t in stories_in[category] if leads_by[(repo, t)]]
            # With no lead for any type, prefer types that do not need a candidate.
            usable = (
                has_leads
                or [t for t in stories_in[category] if t not in CANDIDATE_STORIES]
                or list(stories_in[category])
            )
            for _ in range(per_repo[repo]):
                open_t = [
                    t for t in usable if story_used.get(t, 0) < story_caps.get(t, 1 << 30)
                ] or usable
                story = min(
                    open_t,
                    key=lambda t: (
                        not (t == SPOT and story_used.get(t, 0) < spot_min),
                        (story_used.get(t, 0) + 1) / story_boost.get(t, 1.0),
                        recent_story.get(t, 0),
                        usable.index(t),
                    ),
                )
                story_used[story] = story_used.get(story, 0) + 1
                allowed = allowed_for(story, category, used, spent, formats_in[category])
                fmt = allowed[0]
                used[fmt] = used.get(fmt, 0) + 1
                spent += ILLUSTRATION_COST.get(fmt, 0)
                slot_allowed.append(allowed)
                slots.append((repo, category, story, fmt, None))

    # 1a. Variants: a slot with no fresh lead may retell a good old story in a new format.
    variant_at: dict[int, dict] = {}  # slot index -> variant
    cap = int(variant_max_share * count)
    seen_n: Counter = Counter()
    needy = []  # slots past the fresh leads of their (repo, story type)
    for i, (repo, _, story, _, grp) in enumerate(slots):
        if grp is None:
            seen_n[(repo, story)] += 1
            if seen_n[(repo, story)] > len(leads_by[(repo, story)]):
                needy.append(i)
    for v in variants or []:
        if len(variant_at) >= cap:
            break
        for i in needy:
            repo, category, story, fmt, _ = slots[i]
            if repo != v["repo"] or v["story_type"] not in stories_in[category]:
                continue
            room = spent - ILLUSTRATION_COST.get(fmt, 0)
            # Formats that suit the variant's story first, then any of the category's.
            options = [
                f
                for f in allowed_for(v["story_type"], category, used, room, formats_in[category])
                if f not in v["formats_used"]
            ] or [f for f in formats_in[category] if f not in v["formats_used"]]
            if not options:
                continue
            new = _pick_format(
                options,
                used,
                room,
                max_illustrations,
                fmt_boost,
                fmt_caps,
                recent_fmt,
                format_weights,
            )
            used[fmt] -= 1
            used[new] = used.get(new, 0) + 1
            spent = room + ILLUSTRATION_COST.get(new, 0)
            story_used[story] -= 1
            story_used[v["story_type"]] = story_used.get(v["story_type"], 0) + 1
            slots[i] = (repo, category, v["story_type"], new, None)
            slot_allowed[i] = [new]
            variant_at[i] = v
            needy.remove(i)
            break

    # 1c. Intro slots: reserve a share of the cards for leads from the least-known dirs.
    intro_at = _assign_intro(
        slots, variant_at, ref_by, novelty, intro_share, count, intro_prefer or {}
    )

    # The image share is a soft target the packet states; no format is forced.
    image_share = float((defaults.get("visual_mix") or {}).get("image_min_share") or 0)

    # 2. Pack slots into as few packets as possible per (repo or group, model tier).
    packets: list[Packet] = []
    slot_no = 0
    units = [(r, None, [r]) for r in repo_names] + [
        (rs[0], g, rs) for g, rs in cross_groups.items()
    ]
    plan = []  # (repo, group, cheap, slot indexes) per packet, in packet order
    for repo, grp, unit_repos in units:
        for cheap in (True, False):
            group = [
                i
                for i, s in enumerate(slots)
                if s[0] == repo
                and s[4] == grp
                # The writer may pick any allowed format, so a haiku needs all of them to be easy.
                and (s[2] in CONCRETE_TYPES and all(f in HAIKU_FORMATS for f in slot_allowed[i]))
                == cheap
            ]
            for start in range(0, len(group), packet_size):
                plan.append((repo, grp, unit_repos, cheap, group[start : start + packet_size]))
    # Packets of one repo get disjoint leads: the leads of a (repo, story type) are dealt out
    # round robin over the packets that hold the type, intro leads belong to their own packet
    # only, and a commit or path is offered to one packet of the repo.
    holders: dict[tuple[str, str], list[int]] = {}
    for pi, (repo, grp, _, _, chunk_ix) in enumerate(plan):
        if not grp:
            for t in dict.fromkeys(slots[i][2] for i in chunk_ix):
                holders.setdefault((repo, t), []).append(pi)
    intro_texts = {(slots[i][0], slots[i][2], ld.text) for i, (_, ld) in intro_at.items()}
    claimed: dict[tuple[str, str], int] = {}
    for pi, (repo, _grp, _, _, chunk_ix) in enumerate(plan):
        for i in chunk_ix:
            if i in intro_at and (subject := _subject(intro_at[i][1])):
                claimed.setdefault((repo, subject), pi)
    for pi, (repo, grp, unit_repos, cheap, chunk_ix) in enumerate(plan):
        chunk = [slots[i] for i in chunk_ix]
        types = list(dict.fromkeys(t for _, _, t, _, _ in chunk))
        if grp:
            pairs = [
                (f"[{t}] {line}", Lead(t, repo, "none", text=line))
                for t in types
                for line in cross_by_group[grp][t]
            ]
        else:
            pairs = []
            for t in types:
                mine = leads_by[(repo, t)][holders[(repo, t)].index(pi) :: len(holders[(repo, t)])]
                for line in mine:
                    ld = ref_by[(repo, t)][line]
                    if (repo, t, line) in intro_texts:
                        continue  # an intro slot holds it
                    if (subject := _subject(ld)) and claimed.setdefault((repo, subject), pi) != pi:
                        continue
                    pairs.append((f"[{t}] {line}", ld))
        intro_pairs = []
        for i in chunk_ix:
            if i in intro_at:
                d, ld = intro_at[i]
                t = slots[i][2]
                line = (
                    f"[{t}] intro: the reader has not seen {d}/ yet; explain what it "
                    f"is for before the detail. {ld.text}"
                )
                intro_pairs.append((line, replace(ld, intro=d)))
        if intro_pairs:
            taken = {r.text for _, r in intro_pairs}
            pairs = intro_pairs + [
                (ln, r) for ln, r in pairs if getattr(r, "text", None) not in taken
            ]
        if not pairs and len(chunk_ix) > sum(i in variant_at for i in chunk_ix):
            none = "No precomputed leads: explore with list_dir and git_log."
            pairs = [(none, Lead(types[0], repo, "none", text=none))]
        for i in chunk_ix:
            if i in variant_at:
                pairs.append(_variant_pair(variant_at[i], slots[i][3]))
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
                    persona_cycle[(slot_no + i) % len(persona_cycle)] for i in range(len(chunk))
                ],
                leads=[line for line, _ in pairs],
                lead_refs=[r if isinstance(r, dict) else asdict(r) for _, r in pairs],
                formats=[f for _, _, _, f, _ in chunk],
                card_stories=[t for _, _, t, _, _ in chunk],
                allowed=[slot_allowed[i] for i in chunk_ix],
                images=min(
                    math.ceil(image_share * len(chunk) - 1e-9),
                    sum(bool(IMAGE_FORMATS & set(slot_allowed[i])) for i in chunk_ix),
                ),
                templates=[template_menu(f, t) for _, _, t, f, _ in chunk],
                repos=list(unit_repos),
                intro=sum(i in intro_at for i in chunk_ix),
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
        intro=_intro_summary(intro_at, slots),
    )


def _subject(ld: Lead) -> str | None:
    """What a lead points at: its commit, else its path (None for a dir or a pair)."""
    return ld.commit or (ld.path if ld.kind == "path" else None)


INTRO_MIN_NOVELTY = 0.5  # a dir this known or better is not "unseen": no intro slot for it


def _assign_intro(slots, variant_at, ref_by, novelty, intro_share, count, prefer=None) -> dict:
    """slot index -> (dir, Lead) for the intro slots.

    Dirs with leads are ranked by novelty (highest first, then by their best lead's rank) and
    dealt out one slot at a time, so a few dirs share the slots instead of one dir taking all.
    A slot takes the best unused lead of its own repo and story type in the dir. Only code dirs
    count (`code_path`: no hidden, test, fixture, cassette, vendored, generated or docs dirs).
    Dirs in `prefer[repo]` (they hold core or entry_point candidates) come first.
    """
    prefer = prefer or {}
    if not novelty or intro_share <= 0 or not slots:
        return {}
    want = min(math.ceil(count * intro_share - 1e-9), len(slots))
    cands: dict[tuple[str, str], list] = {}  # (repo, dir) -> [(rank, story, Lead)]
    nov_of: dict[tuple[str, str], float] = {}
    for (repo, story), by_text in ref_by.items():
        nmap = novelty.get(repo)
        if nmap is None:
            continue
        for rank, ld in enumerate(by_text.values()):
            d, n = knowledge.lead_dir(ld.path, nmap)
            code = code_file(ld.path) if ld.path else code_path(f"{d}/x")
            if d and n >= INTRO_MIN_NOVELTY and code and code_path(f"{d}/x"):
                cands.setdefault((repo, d), []).append((rank, story, ld))
                nov_of[(repo, d)] = n
    order = sorted(
        cands,
        key=lambda k: (
            k[1] not in prefer.get(k[0], ()),
            -nov_of[k],
            min(c[0] for c in cands[k]),
            k,
        ),
    )
    out: dict = {}
    used: set = set()
    free = [i for i, s in enumerate(slots) if s[4] is None and i not in variant_at]
    while len(out) < want and order:
        progress = False
        for key in order:
            if len(out) >= want:
                break
            repo, d = key
            for i in free:
                if i in out or slots[i][0] != repo:
                    continue
                pick = next(
                    (
                        ld
                        for _, story, ld in cands[key]
                        if story == slots[i][2] and id(ld) not in used
                    ),
                    None,
                )
                if pick is not None:
                    used.add(id(pick))
                    out[i] = (d, pick)
                    progress = True
                    break
        if not progress:
            break
    return out


def _intro_summary(intro_at, slots) -> list:
    n: Counter = Counter((slots[i][0], d) for i, (d, _) in intro_at.items())
    return [(repo, d, c) for (repo, d), c in n.items()]


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
    personas: dict,
    formats=None,
    meme_templates: dict | None = None,
    mascots: dict | None = None,
    menus: list | None = None,
) -> str:
    """Card-writing rules for a packet subagent: base guidance plus the format sections.

    `formats=None` includes every format section; a list includes only those (`[]` is base only).
    `menus` (a packet's meme menus) limits the meme template list to the templates in them.
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
    shown = dict(meme_templates or {})
    menu_ids = [t for m in menus or [] for t in m or []]
    if menu_ids:
        shown = {t: shown[t] for t in dict.fromkeys(menu_ids) if t in shown}
    tpl = "\n".join(f"- `{t.id}` ({t.lines} lines): {t.hint}" for t in shown.values())
    masc = "\n".join(f"- `{m.name}` (repo {m.repo or 'none'})" for m in (mascots or {}).values())
    body = "\n\n".join(chosen).replace("{meme_templates}", tpl or "(none configured)")
    body = body.replace("{mascots}", masc or "(none configured)")
    return out.rstrip() + "\n\n## Format sections\n\n" + body + "\n"

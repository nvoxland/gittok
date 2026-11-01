"""Strict, LLM-free validation of agent-written card specs (SPEC §10.6)."""

from __future__ import annotations

import copy
import json
import re
from functools import cache
from importlib.resources import files

from jsonschema import Draft202012Validator


@cache
def _base_schema() -> dict:
    return json.loads((files("codescroll") / "schema" / "card.schema.json").read_text())


def card_schema(personas: list[str] | tuple[str, ...]) -> dict:
    """The submission schema with the persona enum set to the configured handles."""
    doc = copy.deepcopy(_base_schema())
    doc["$defs"]["persona"]["enum"] = sorted(personas)
    return doc


@cache
def _card_validator(personas: tuple[str, ...]) -> Draft202012Validator:
    doc = card_schema(personas)
    card_doc = {"$schema": doc["$schema"], "$defs": doc["$defs"], **doc["$defs"]["card"]}
    return Draft202012Validator(card_doc)


def schema_errors(card: object, personas) -> list[str]:
    """Human-readable schema errors for one card; empty when valid."""
    v = _card_validator(tuple(sorted(personas)))
    out = []
    for err in sorted(v.iter_errors(card), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in err.absolute_path) or "(card)"
        out.append(f"{where}: {_short(err)}")
    return out


def _short(err) -> str:
    if err.validator == "oneOf" and err.context:
        best = min(err.context, key=lambda e: len(list(e.absolute_path)) * -1)
        return best.message[:300]
    return err.message[:300]


# ---------------------------------------------------------------------------
# Git-backed checks
# ---------------------------------------------------------------------------

import hashlib  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from datetime import UTC, datetime, timedelta, timezone  # noqa: E402
from pathlib import PurePosixPath  # noqa: E402

from codescroll import gitq  # noqa: E402

MAX_SPAN = 40
# The card front must fit one phone screen without scrolling: on iOS a scrolling front takes
# the vertical swipe and the feed never flips. Text is counted in characters, plus a fixed
# cost per list item for its padding. Images and charts have a fixed size and are not counted.
MAX_HOOK = 140
FRONT_BUDGET = 360
ITEM_COST = 25
MAX_FRONT_CODE_LINES = 12
_NOT_SHOWN = {"kind", "template", "repo", "path", "commit", "from", "tier", "prompt", "excerpt"}

LANGUAGES = {
    ".py": "python",
    ".clj": "clojure",
    ".cljs": "clojure",
    ".cljc": "clojure",
    ".edn": "clojure",
    ".js": "javascript",
    ".jsx": "jsx",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".svelte": "svelte",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".sh": "bash",
    ".sql": "sql",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".md": "markdown",
    ".html": "html",
    ".css": "css",
    ".toml": "toml",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
}


def language_for(path: str) -> str | None:
    return LANGUAGES.get(PurePosixPath(path).suffix.lower())


@dataclass(frozen=True)
class Rejection:
    index: int
    reason: str
    detail: str

    def as_dict(self) -> dict:
        return {"index": self.index, "reason": self.reason, "detail": self.detail}


@dataclass
class Accepted:
    index: int
    card: dict
    resolved: dict
    story_key: str


class _Reject(Exception):
    def __init__(self, reason: str, detail: str):
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


@dataclass
class _GitCache:
    repos: dict
    shas: dict = field(default_factory=dict)
    times: dict = field(default_factory=dict)
    files: dict = field(default_factory=dict)
    diffs: dict = field(default_factory=dict)
    patches: dict = field(default_factory=dict)

    def repo(self, name: str):
        if name not in self.repos:
            raise _Reject(
                "unknown_repo", f"{name!r} is not configured; known: {sorted(self.repos)}"
            )
        return self.repos[name]

    def commit(self, repo_name: str, sha: str) -> str:
        key = (repo_name, sha)
        if key not in self.shas:
            repo = self.repo(repo_name)
            try:
                if re.fullmatch(gitq.HEX_ID_PATTERN, sha):
                    full = gitq.resolve_commit_id(repo.path, sha)
                else:
                    full = gitq.rev_parse(repo.path, sha)
            except gitq.GitError as e:
                what = "is ambiguous" if "ambiguous" in str(e) else "not found"
                raise _Reject("unknown_commit", f"{sha} {what} in {repo_name}") from e
            if not gitq.is_ancestor(repo.path, full, repo.ref):
                raise _Reject("commit_not_in_ref", f"{sha} is not on {repo.ref} in {repo_name}")
            self.shas[key] = full
        return self.shas[key]

    def commit_ts(self, repo_name: str, full: str) -> int:
        key = (repo_name, full)
        if key not in self.times:
            self.times[key] = gitq.commit_time(self.repo(repo_name).path, full)
        return self.times[key]

    def file_lines(self, repo_name: str, rev: str, path: str) -> list[str]:
        key = (repo_name, rev, path)
        if key not in self.files:
            repo = self.repo(repo_name)
            try:
                data = gitq.show_file(repo.path, rev, path)
            except gitq.GitError as e:
                if gitq.object_type(repo.path, rev, path) == "tree":
                    raise _Reject(
                        "path_not_at_commit", f"{path} is a directory at {rev[:10]}, not a file"
                    ) from e
                raise _Reject("path_not_at_commit", f"{path} does not exist at {rev[:10]}") from e
            if b"\0" in data[:8192]:
                raise _Reject("binary_path", f"{path} is binary")
            self.files[key] = gitq.split_lines(data.decode(errors="replace"))
        return self.files[key]

    def diff(self, repo_name: str, full: str, path: str) -> str:
        key = (repo_name, full, path)
        if key not in self.diffs:
            repo = self.repo(repo_name)
            kinds = [gitq.object_type(repo.path, full, path)]
            if "blob" not in kinds:
                kinds.append(gitq.object_type(repo.path, f"{full}^1", path))
            if "blob" not in kinds:
                raise _Reject(
                    "path_not_at_commit", f"{path} is not a file at or before {full[:10]}"
                )
            parents = gitq.run(repo.path, "rev-list", "--parents", "-n", "1", full).split()[1:]
            if len(parents) > 1:  # merge: `git show` would print an empty combined diff
                head = ["diff", f"{full}^1", full]
            else:
                head = ["show", "--format=", full]
            self.diffs[key] = gitq.run(
                repo.path,
                head[0],
                "--no-color",
                "--no-ext-diff",
                *head[1:],
                "--",
                path,
                max_bytes=200_000,
            )
        return self.diffs[key]

    def patch(self, repo_name: str, full: str) -> str:
        """The whole patch of one commit (all files), for finding identifiers in a cited commit."""
        key = (repo_name, full)
        if key not in self.patches:
            self.patches[key] = gitq.run(
                self.repo(repo_name).path,
                "show", "--format=", "--no-color", "--no-ext-diff", full,
                max_bytes=200_000,
            )  # fmt: skip
        return self.patches[key]


CROSS_STORIES = frozenset({"weekly_recap", "drift_alert", "ripple"})
CROSS_WINDOW_DAYS = 7


def _check_cross_repo(card: dict, gc: _GitCache) -> None:
    """Rules for cross-repo stories (SPEC 6.4); `sources` commits are already full shas."""
    if card["story_type"] not in CROSS_STORIES:
        return
    repos = list(dict.fromkeys(card["repos"]))
    groups = {getattr(gc.repo(r), "group", None) for r in repos}
    if len(repos) < 2 or len(groups) != 1 or None in groups:
        raise _Reject(
            "cross_repo_group",
            f"{card['story_type']} needs 2+ repos of one configured group; "
            f"got {repos} in groups {sorted(map(str, groups))}",
        )
    cited = {s["repo"] for s in card["sources"]}
    if len(cited & set(repos)) < 2:
        raise _Reject(
            "cross_repo_sources",
            f"sources must cite commits or paths in 2+ of {repos}; got {sorted(cited)}",
        )
    commits = [(s["repo"], s["commit"]) for s in card["sources"] if "commit" in s]
    when = {(r, c): gc.commit_ts(r, c) for r, c in commits}
    window = CROSS_WINDOW_DAYS * 86400
    if card["story_type"] == "ripple":
        if len({r for r, _ in commits}) < 2:
            raise _Reject("ripple_window", "ripple needs cited commits from 2+ repos within 7 days")
        far = [
            (ra, rb)
            for i, (ra, ca) in enumerate(commits)
            for rb, cb in commits[i + 1 :]
            if ra != rb and abs(when[(ra, ca)] - when[(rb, cb)]) > window
        ]
        if far:
            raise _Reject(
                "ripple_window",
                f"cited commits of {far[0][0]} and {far[0][1]} are more than "
                f"{CROSS_WINDOW_DAYS} days apart",
            )
    elif card["story_type"] == "weekly_recap":
        for r in dict.fromkeys(s["repo"] for s in card["sources"]):
            times = [when[rc] for rc in when if rc[0] == r]
            if not times:
                raise _Reject(
                    "recap_window", f"weekly_recap must cite at least one commit in {r}, not paths"
                )
            repo = gc.repo(r)
            head = gitq.commit_time(repo.path, repo.ref)
            if head - max(times) > window or max(times) - min(times) > window:
                raise _Reject(
                    "recap_window",
                    f"weekly_recap commits in {r} must be within {CROSS_WINDOW_DAYS} days of "
                    f"each other and of the last commit of {r}",
                )


def _norm_lines(text: str) -> list[str]:
    lines = [ln.expandtabs(4).rstrip() for ln in gitq.split_lines(text)]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return lines


def _check_range(lines: list[int], nlines: int, path: str) -> tuple[int, int]:
    a, b = lines
    if not (1 <= a <= b <= nlines):
        raise _Reject("lines_out_of_range", f"{path} has {nlines} lines; got [{a}, {b}]")
    if b - a + 1 > MAX_SPAN:
        raise _Reject("excerpt_too_long", f"[{a}, {b}] spans {b - a + 1} lines; max {MAX_SPAN}")
    return a, b


def _resolve_code(gc: _GitCache, ref: dict, *, excerpt: str | None = None) -> dict:
    full = gc.commit(ref["repo"], ref["commit"])
    ref["commit"] = full
    content = gc.file_lines(ref["repo"], full, ref["path"])
    a, b = _check_range(ref["lines"], len(content), ref["path"])
    code = content[a - 1 : b]
    if excerpt is not None and _norm_lines(excerpt) != _norm_lines("\n".join(code)):
        raise _Reject(
            "excerpt_mismatch",
            f"excerpt does not match {ref['path']} lines {a}-{b} at {full[:10]}; "
            "omit excerpt or copy the lines exactly",
        )
    return {"code": "\n".join(code), "language": language_for(ref["path"]), "start_line": a}


def _strip_dot(path: str) -> str:
    while path.startswith("./"):
        path = path[2:]
    return path


def _repo_refs(card: dict) -> list[dict]:
    refs = [card["visual"]] if card["visual"]["kind"] == "code" else []
    refs += [p for p in card["depth"] if p["kind"] in ("code", "code_diff")]
    return refs + list(card["sources"])


def _normalize_paths(card: dict) -> None:
    for ref in _repo_refs(card):
        if "path" in ref:
            ref["path"] = _strip_dot(ref["path"])


TEXT_FORMATS = {"text_post", "fun_fact", "listicle", "eli5"}
TEMPLATE_FORMATS = {
    "iceberg", "tier_list", "group_chat", "flags", "dating_profile", "glow_up",
    "breaking_news", "horoscope", "thread", "day_in_life", "hot_take",
}  # fmt: skip
FORMAT_KIND = {
    "code_card": "code",
    **dict.fromkeys(TEXT_FORMATS, "text"),
    "meme": "meme",
    "text_meme": "text_meme",
    "mascot_scene": "illustration",
    "comic": "comic",
    "chart": "chart",
    "diagram": "diagram",
    "quiz": ("code", "text"),
    **dict.fromkeys(TEMPLATE_FORMATS, "template"),
}
INTERACTIVE_STORIES = frozenset({"spot_the_bug", "guess_who", "guess_when", "quiz", "this_or_that"})
BUG_MARGIN = 10  # a fix counts when it touches the cited lines +/- this many


def _check_format(card: dict) -> None:
    fmt, visual = card["format"], card["visual"]
    want = FORMAT_KIND[fmt]
    if isinstance(want, tuple):
        if visual["kind"] not in want:
            raise _Reject(
                "format_kind_mismatch",
                f"format {fmt!r} needs visual kind {' or '.join(map(repr, want))}; "
                f"got {visual['kind']!r}",
            )
        return
    if visual["kind"] != want or (want == "template" and visual["template"] != fmt):
        got = visual["kind"] + (f"/{visual['template']}" if visual["kind"] == "template" else "")
        raise _Reject(
            "format_kind_mismatch",
            f"format {fmt!r} needs visual kind {want!r}"
            + (f" with template {fmt!r}" if want == "template" else "")
            + f"; got {got!r}",
        )


def _check_interaction_shape(card: dict) -> None:
    """Presence and answer_index rules that need no git."""
    has = "interaction" in card
    if has and card["format"] != "quiz":
        raise _Reject(
            "interaction_not_allowed",
            f"interaction is only allowed on quiz cards, not {card['format']!r}",
        )
    if not has:
        if card["format"] == "quiz" or card["story_type"] in INTERACTIVE_STORIES:
            raise _Reject(
                "interaction_required",
                f"{card['story_type']!r} cards need format 'quiz' and an interaction",
            )
        return
    inter, story = card["interaction"], card["story_type"]
    norm = [_norm_choice(c) for c in inter["choices"]]
    if len(set(norm)) != len(norm):
        raise _Reject("duplicate_choices", "two choices say the same thing")
    idx = inter.get("answer_index")
    if story == "this_or_that":
        if idx is not None:
            raise _Reject("invalid_answer_index", "this_or_that must not have answer_index")
        if len({c["persona"] for c in card.get("comments", [])}) < 2:
            raise _Reject(
                "needs_debate", "this_or_that needs comments from at least 2 different personas"
            )
    elif idx is None:
        raise _Reject("invalid_answer_index", "answer_index is required")
    elif idx >= len(inter["choices"]):
        raise _Reject(
            "invalid_answer_index", f"answer_index {idx} but only {len(inter['choices'])} choices"
        )


def _ranges_touch(ranges: list[tuple[int, int]], lines) -> bool:
    lo, hi = lines[0] - BUG_MARGIN, lines[1] + BUG_MARGIN
    return any(a <= hi and b >= lo for a, b in ranges)


def _norm_choice(text: str) -> str:
    return " ".join(text.split()).casefold()


def _tz(offset: str) -> timezone:
    """A git `author-tz` value like "+1030" or "-0500"."""
    try:
        sign = -1 if offset.startswith("-") else 1
        digits = offset.lstrip("+-")
        return timezone(sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:4])))
    except ValueError:
        return UTC


def _check_interactive_truth(card: dict, gc: _GitCache) -> None:
    """Checks that need git. Runs after sources and depth are resolved to full SHAs."""
    story = card["story_type"]
    if story not in ("spot_the_bug", "guess_who", "guess_when"):
        return
    v = card["visual"]
    if v["kind"] != "code":
        reason = "not_a_bug_fix" if story == "spot_the_bug" else "wrong_answer"
        raise _Reject(reason, f"{story} needs a code visual; got {v['kind']!r}")
    repo = gc.repo(v["repo"]).path
    if story == "spot_the_bug":
        fixes = []
        for src in card["sources"]:
            if src.get("repo") != v["repo"] or "commit" not in src:
                continue
            if gitq.first_parent(repo, src["commit"]) != v["commit"]:
                continue
            if gitq.path_removed_by(repo, src["commit"], v["path"]):
                continue  # the "fix" deletes or renames the file; there is no bug to spot
            if _ranges_touch(gitq.changed_old_ranges(repo, src["commit"], v["path"]), v["lines"]):
                fixes.append(src["commit"])
        if not fixes:
            raise _Reject(
                "not_a_bug_fix",
                f"no source commit has {v['commit'][:10]} as first parent and changes "
                f"{v['path']} within lines {v['lines']} +/- {BUG_MARGIN}",
            )
        if not any(
            p["kind"] == "code_diff" and p["repo"] == v["repo"] and p["commit"] in fixes
            for p in card["depth"]
        ):
            raise _Reject(
                "missing_fix_diff",
                f"add a code_diff depth panel for the fix commit {fixes[0][:10]}",
            )
        return
    rows = gitq.blame_range(repo, v["commit"], v["path"], *v["lines"])
    inter = card["interaction"]
    choice = inter["choices"][inter["answer_index"]]
    if story == "guess_who":
        counts: dict[str, int] = {}
        for r in rows:
            counts[r["author"]] = counts.get(r["author"], 0) + 1
        top = max(counts.values())
        winners = [a for a, n in counts.items() if n == top]
        names = {_norm_choice(a) for a in winners}
        if _norm_choice(choice) not in names:
            raise _Reject(
                "wrong_answer", f"git blame says {' or '.join(winners)} wrote those lines"
            )
        for n, other in enumerate(inter["choices"]):
            if n != inter["answer_index"] and any(a in _norm_choice(other) for a in names):
                raise _Reject("ambiguous_answer", f"choice {other!r} also names the author")
    else:
        mid = sorted(rows, key=lambda r: r["author_time"])[(len(rows) - 1) // 2]
        year = datetime.fromtimestamp(mid["author_time"], _tz(mid["author_tz"])).year
        if str(year) not in choice:
            raise _Reject("wrong_answer", f"the median blame year of those lines is {year}")
        for n, other in enumerate(inter["choices"]):
            if n != inter["answer_index"] and str(year) in other:
                raise _Reject("ambiguous_answer", f"choice {other!r} also contains {year}")


@dataclass
class _Ctx:
    personas: list
    meme_templates: dict = field(default_factory=dict)
    mascots: dict = field(default_factory=dict)
    signals_for: object = None
    budget: int | None = None  # remaining illustrations; None = unlimited
    card_repos: tuple = ()


def _check_meme(card: dict, ctx: _Ctx) -> None:
    v = card["visual"]
    tpl = ctx.meme_templates.get(v["template"])
    if tpl is None:
        raise _Reject(
            "unknown_meme_template",
            f"{v['template']!r} is not a meme template; known: {sorted(ctx.meme_templates)}",
        )
    if len(v["lines"]) > tpl.lines:
        raise _Reject(
            "meme_lines", f"template {tpl.id!r} takes {tpl.lines} line(s); got {len(v['lines'])}"
        )
    if any(line and set(line) == {"."} for line in v["lines"]):
        raise _Reject("meme_lines", "a line cannot be only dots")


def _code_account(acct: str, card: dict, gc: _GitCache) -> tuple[str, str, str]:
    """Check a `repo:path` account. Returns (repo, normalized path, "file" | "dir")."""
    repo_name, _, path = acct.partition(":")
    path = _strip_dot(path).strip("/")
    if repo_name not in card["repos"]:
        raise _Reject(
            "unknown_account", f"{acct!r}: repo {repo_name!r} is not in card repos {card['repos']}"
        )
    repo = gc.repo(repo_name)
    kind = (
        gitq.object_type(repo.path, repo.ref, path)
        if path and ".." not in path.split("/")
        else None
    )
    if kind not in ("blob", "tree"):
        raise _Reject(
            "unknown_account", f"{acct!r}: {path!r} does not exist at {repo_name} {repo.ref}"
        )
    return repo_name, path, "file" if kind == "blob" else "dir"


def _resolve_account(acct: str, card: dict, gc: _GitCache, ctx: _Ctx) -> str:
    """Normalize a persona handle or code account; reject anything else."""
    if ":" not in acct:
        if acct not in ctx.personas:
            raise _Reject("unknown_account", f"{acct!r} is not a persona handle or repo:path")
        return acct
    repo_name, path, _ = _code_account(acct, card, gc)
    return f"{repo_name}:{path}"


def _check_accounts(card: dict, gc: _GitCache, ctx: _Ctx) -> dict | None:
    v = card["visual"]
    if v["kind"] == "template":
        d, t = v["data"], v["template"]
        if t == "group_chat":
            for m in d["messages"]:
                m["from"] = _resolve_account(m["from"], card, gc, ctx)
        elif t == "dating_profile":
            d["name"] = _resolve_account(d["name"], card, gc, ctx)
        elif t in ("horoscope", "day_in_life"):
            d["subject"] = _resolve_account(d["subject"], card, gc, ctx)
    if "account" not in card:
        return None
    repo_name, path, kind = _code_account(card["account"], card, gc)
    card["account"] = f"{repo_name}:{path}"
    return {
        "handle": "@" + path.rsplit("/", 1)[-1],
        "repo": repo_name,
        "path": path,
        "kind": kind,
    }


def _top(rows: list[dict], key: str, label, n: int = 10) -> list[dict]:
    ranked = sorted(rows, key=lambda r: (-r[key], label(r)))[:n]
    return [{"label": label(r), "value": r[key]} for r in ranked]


def _build_chart(v: dict, ctx: _Ctx) -> dict:
    name, kind = v["repo"], v["chart"]
    if name not in ctx.card_repos:
        raise _Reject("repo_not_in_card", f"chart repo {name!r} is not listed in repos")
    sig = ctx.signals_for(name) if ctx.signals_for else None
    if not sig:
        raise _Reject("chart_no_data", f"no cached signals for {name!r}; run analysis first")
    window = v.get("window", "90")
    x_label, y_label = "file", "commits"
    if kind in ("top_churn_files", "top_churn_dirs"):
        group = "files" if kind == "top_churn_files" else "dirs"
        x_label = "file" if group == "files" else "dir"
        rows = (sig.get("churn") or {}).get(group, {}).get(window) or []
        bars = _top(rows, "commits", lambda r: r["path"])
        default = f"Most-edited {group} (last {window} days)"
    elif kind == "commit_hours":
        hist = (sig.get("commit_times") or {}).get("hour_histogram") or []
        bars = [{"label": f"{h:02d}", "value": n} for h, n in enumerate(hist)] if hist else []
        x_label, default = "hour", "When commits happen"
    elif kind == "author_shares":
        rows = ((sig.get("author_shares") or {}).get("by_dir") or {}).get(v["dir"]) or []
        bars = [{"label": r["author"], "value": round(r["share"] * 100)} for r in rows]
        x_label, y_label, default = "author", "share of changes (%)", f"Who owns {v['dir']}"
    else:  # co_change
        rows = sig.get("co_change") or []
        bars = _top(rows, "count", lambda r: f"{r['a']} + {r['b']}")
        x_label, y_label, default = "file pair", "co-changes", "Files that change together"
    if not bars:
        raise _Reject("chart_no_data", f"{kind} has no data for {name!r} ({window}d)")
    return {
        "type": "bar",
        "title": v.get("title") or default,
        "x_label": x_label,
        "y_label": y_label,
        "bars": bars,
    }


def illustration_cost(card: dict) -> int:
    v = card["visual"]
    if v["kind"] == "illustration":
        return 1
    return len(v["panels"]) if v["kind"] == "comic" else 0


def _check_mascots(card: dict, ctx: _Ctx, gc: _GitCache) -> None:
    v = card["visual"]
    names = v.get("mascots")
    if not names:
        first = card["repos"][0]
        names = [m.name for m in ctx.mascots.values() if m.repo == first][:1]
        if not names:
            fallback = gc.repo(first).mascot
            names = [fallback] if fallback else []
        if not names:
            raise _Reject("unknown_mascot", f"no default mascot for repo {first!r}; set mascots")
    for n in names:
        if n not in ctx.mascots:
            raise _Reject("unknown_mascot", f"{n!r} is not a mascot; known: {sorted(ctx.mascots)}")
    v["mascots"] = names
    cost = illustration_cost(card)
    if ctx.budget is not None and cost > ctx.budget:
        raise _Reject(
            "illustration_budget", f"card needs {cost} image(s); {ctx.budget} left in the budget"
        )


def _front_cost(value, key: str | None = None) -> int:
    if key in _NOT_SHOWN:
        return 0
    if isinstance(value, str):
        return len(value)
    if isinstance(value, dict):
        return sum(_front_cost(v, k) for k, v in value.items())
    if isinstance(value, list):
        return sum(_front_cost(v) + ITEM_COST for v in value)
    return 0


def _check_fit(card: dict) -> None:
    hook = card["hook"]
    if len(hook) > MAX_HOOK:
        raise _Reject("too_long", f"hook is {len(hook)} chars; max {MAX_HOOK}")
    v = card["visual"]
    if v["kind"] in ("meme", "illustration", "comic", "chart", "code"):
        cost = _front_cost(v.get("callouts", [])) + _front_cost(v.get("caption", ""))
    else:
        cost = _front_cost(v)
    if cost > FRONT_BUDGET:
        raise _Reject(
            "too_long",
            f"front text costs {cost}; budget {FRONT_BUDGET} (characters, plus {ITEM_COST} "
            "per list item). Cut items or shorten them; detail belongs in depth panels",
        )


MIN_EXPLAIN_CHARS = 200
MIN_EXPLAIN_PARAGRAPHS = 2
# Phrases that admit the writer did not find the reason. Matched on lowercased text.
UNTRACED_PHRASES = (
    "did not trace",
    "didn't trace",
    "did not read why",
    "didn't read why",
    "did not check why",
    "didn't check why",
    "not sure why",
    "unsure why",
    "unclear why",
    "don't know why",
    "do not know why",
    "could not tell why",
    "couldn't tell why",
)
_BACKTICKED = re.compile(r"`([^`\n]+)`")


def _check_untraced(card: dict) -> None:
    for panel in card["depth"]:
        if panel["kind"] != "explain":
            continue
        low = panel["text"].lower().replace("\u2019", "'")
        hit = next((p for p in UNTRACED_PHRASES if p in low), None)
        if hit:
            raise _Reject(
                "untraced",
                f"the explain text says {hit!r}. Read the commit message (git_show) or the "
                "callers (git_grep) and say why. If you cannot find out, drop the card",
            )


def _explain_haystack(card: dict, gc: _GitCache, cited_paths: set[str]) -> str:
    """Text of everything the card cites: code at commits, diffs, sources, and commit patches."""
    parts: list[str] = []
    refs = [card["visual"]] if card["visual"]["kind"] == "code" else []
    for panel in card["depth"]:
        if panel["kind"] == "code":
            refs.append(panel)
        elif panel["kind"] == "code_diff":
            full = gc.commit(panel["repo"], panel["commit"])
            parts.append(gc.diff(panel["repo"], full, panel["path"]))
            cited_paths.add(panel["path"])
    for ref in refs:
        cited_paths.add(ref["path"])
        parts.extend(gc.file_lines(ref["repo"], ref["commit"], ref["path"]))
    for src in card["sources"]:
        if "commit" in src:
            parts.append(gc.patch(src["repo"], gc.commit(src["repo"], src["commit"])))
        else:
            cited_paths.add(src["path"])
            parts.extend(gc.file_lines(src["repo"], gc.repo(src["repo"]).ref, src["path"]))
    return "\n".join(parts)


def _check_explain_floor(card: dict, gc: _GitCache) -> None:
    """The first explain panel is the card's main explanation; it must teach something real."""
    _check_untraced(card)
    text = next(p["text"] for p in card["depth"] if p["kind"] == "explain")
    paragraphs = [b for b in re.split(r"\n\s*\n", text.strip()) if b.strip()]
    if len(text.strip()) < MIN_EXPLAIN_CHARS or len(paragraphs) < MIN_EXPLAIN_PARAGRAPHS:
        raise _Reject(
            "explain_too_thin",
            f"the first explain panel has {len(text.strip())} characters in {len(paragraphs)} "
            f"paragraph(s); it needs at least {MIN_EXPLAIN_CHARS} characters in "
            f"{MIN_EXPLAIN_PARAGRAPHS} paragraphs (blank line between). Explain what the code "
            "does, what calls it, or why it exists",
        )
    cited_paths: set[str] = set()
    haystack = _explain_haystack(card, gc, cited_paths)
    spans = [m.strip() for m in _BACKTICKED.findall(text)]
    for span in spans:
        bare = span[:-2] if span.endswith("()") else span
        if len(bare) >= 3 and bare in haystack:
            return
        if any(path == span or path.endswith("/" + span) for path in cited_paths):
            return
    raise _Reject(
        "identifier_not_found",
        "the first explain panel needs at least one `backticked` function, variable, or path "
        "that occurs in the cited code, diff, or commit"
        + (f" (none of {spans[:4]} do)" if spans else " (it has none)")
        + ". Name real identifiers from the code you cite",
    )


def _validate_one(card: dict, gc: _GitCache, ctx: _Ctx) -> tuple[dict, dict, str]:
    personas = ctx.personas
    ctx.card_repos = tuple(card.get("repos", ())) if isinstance(card, dict) else ()
    errs = schema_errors(card, personas)
    if errs:
        raise _Reject("schema", "; ".join(errs[:3]))
    card = copy.deepcopy(card)
    _check_format(card)
    _check_fit(card)
    _check_interaction_shape(card)
    visual = card["visual"]
    if visual["kind"] == "template" and visual["template"] == "breaking_news":
        visual["data"].setdefault("ticker", [])  # optional in the schema; clients expect a list
    if card["visual"]["kind"] == "meme":
        _check_meme(card, ctx)
    if card["visual"]["kind"] in ("illustration", "comic"):
        _check_mascots(card, ctx, gc)
    for name in card["repos"]:
        gc.repo(name)
    _normalize_paths(card)
    for ref in _repo_refs(card):
        if ref["repo"] not in card["repos"]:
            raise _Reject(
                "repo_not_in_card",
                f"{ref['repo']!r} is cited but not listed in repos {card['repos']}",
            )

    resolved: dict = {"visual": None, "depth": []}
    account = _check_accounts(card, gc, ctx)
    if account:
        resolved["account"] = account
    visual = card["visual"]
    if visual["kind"] == "chart":
        resolved["visual"] = _build_chart(visual, ctx)
    if visual["kind"] == "code":
        resolved["visual"] = _resolve_code(gc, visual, excerpt=visual.get("excerpt"))
        a, b = visual["lines"]  # checked after git, so range errors keep their own reasons
        if b - a + 1 > MAX_FRONT_CODE_LINES:
            raise _Reject(
                "too_long",
                f"front code spans {b - a + 1} lines; max {MAX_FRONT_CODE_LINES}. "
                "Show the key lines; put the rest in a code depth panel",
            )
        a, b = visual["lines"]
        for c in visual.get("callouts", []):
            if not a <= c["line"] <= b:
                raise _Reject("callout_out_of_range", f"callout line {c['line']} not in [{a}, {b}]")

    for panel in card["depth"]:
        if panel["kind"] == "explain":
            resolved["depth"].append(None)
        elif panel["kind"] == "code":
            resolved["depth"].append(_resolve_code(gc, panel))
        else:  # code_diff
            full = gc.commit(panel["repo"], panel["commit"])
            panel["commit"] = full
            diff = gc.diff(panel["repo"], full, panel["path"])
            if not diff.strip():
                raise _Reject("empty_diff", f"{panel['path']} did not change in {full[:10]}")
            resolved["depth"].append({"diff": diff})
    if not any(p["kind"] == "explain" for p in card["depth"]):
        raise _Reject("missing_explain_panel", "every card needs a plain-language explain panel")

    keys = []
    for src in card["sources"]:
        repo = gc.repo(src["repo"])
        if "commit" in src:
            src["commit"] = gc.commit(src["repo"], src["commit"])
            keys.append(f"{src['repo']}:{src['commit']}")
        else:
            content = gc.file_lines(src["repo"], repo.ref, src["path"])
            if "lines" in src:
                _check_range(src["lines"], len(content), src["path"])
            span = "-".join(map(str, src.get("lines", [])))
            keys.append(f"{src['repo']}:{src['path']}:{span}")

    _check_cross_repo(card, gc)
    _check_interactive_truth(card, gc)
    if "interaction" in card:
        resolved["interaction"] = {"answer_index": card["interaction"].get("answer_index")}

    dirs: list[str] = []
    for d in card["dirs"]:
        rel = next((r for name in card["repos"] if (r := _dir_rel(gc, name, d)) is not None), None)
        if rel is None:
            raise _Reject("unknown_dir", f"{d} is not a directory at the repo ref")
        if rel and rel not in dirs:
            dirs.append(rel)
    card["dirs"] = dirs
    _check_explain_floor(card, gc)  # last: other checks keep their own reasons

    story_key = hashlib.sha1(
        (card["story_type"] + "|" + "|".join(sorted(keys))).encode()
    ).hexdigest()[:16]
    return card, resolved, story_key


def _dir_rel(gc: _GitCache, repo_name: str, d: str) -> str | None:
    """Repo-relative form of `d` if it is a directory in the repo, else None.

    `d` may carry a repo-name prefix (SPEC §10.5 example). A bare repo name means the
    repo root and normalizes to "" (the caller drops it).
    """
    repo = gc.repo(repo_name)
    rel = _strip_dot(d).strip("/")
    if rel and gitq.object_type(repo.path, repo.ref, rel) == "tree":
        return rel
    if rel == repo_name:
        return ""
    if rel.startswith(repo_name + "/"):
        rel = rel[len(repo_name) + 1 :]
        if rel and gitq.object_type(repo.path, repo.ref, rel) == "tree":
            return rel
    return None


def validate_cards(
    cards: list,
    repos: dict,
    personas,
    *,
    meme_templates: dict | None = None,
    mascots: dict | None = None,
    signals_for=None,
    illustration_budget: int | None = None,
) -> tuple[list[Accepted], list[Rejection]]:
    """Validate agent cards against the schema and git. Never raises for bad cards."""
    gc = _GitCache(repos=repos)
    ctx = _Ctx(
        personas=personas,
        meme_templates=meme_templates or {},
        mascots=mascots or {},
        signals_for=signals_for,
        budget=illustration_budget,
    )
    accepted: list[Accepted] = []
    rejected: list[Rejection] = []
    seen: set[str] = set()
    for i, card in enumerate(cards):
        try:
            normalized, resolved, key = _validate_one(card, gc, ctx)
            if key in seen:
                raise _Reject("duplicate_story", "same story_type and sources as an earlier card")
            seen.add(key)
            if ctx.budget is not None:
                ctx.budget -= illustration_cost(normalized)
            accepted.append(Accepted(i, normalized, resolved, key))
        except _Reject as r:
            rejected.append(Rejection(i, r.reason, r.detail))
        except gitq.GitError as e:
            rejected.append(Rejection(i, "git_error", str(e)[:300]))
    return accepted, rejected

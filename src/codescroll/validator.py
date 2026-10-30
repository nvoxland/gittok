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
from pathlib import PurePosixPath  # noqa: E402

from codescroll import gitq  # noqa: E402

MAX_SPAN = 40

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
    files: dict = field(default_factory=dict)
    diffs: dict = field(default_factory=dict)

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
    **dict.fromkeys(TEMPLATE_FORMATS, "template"),
}


def _check_format(card: dict) -> None:
    fmt, visual = card["format"], card["visual"]
    want = FORMAT_KIND[fmt]
    if visual["kind"] != want or (want == "template" and visual["template"] != fmt):
        got = visual["kind"] + (f"/{visual['template']}" if visual["kind"] == "template" else "")
        raise _Reject(
            "format_kind_mismatch",
            f"format {fmt!r} needs visual kind {want!r}"
            + (f" with template {fmt!r}" if want == "template" else "")
            + f"; got {got!r}",
        )


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


def _validate_one(card: dict, gc: _GitCache, ctx: _Ctx) -> tuple[dict, dict, str]:
    personas = ctx.personas
    ctx.card_repos = tuple(card.get("repos", ())) if isinstance(card, dict) else ()
    errs = schema_errors(card, personas)
    if errs:
        raise _Reject("schema", "; ".join(errs[:3]))
    card = copy.deepcopy(card)
    _check_format(card)
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

    dirs: list[str] = []
    for d in card["dirs"]:
        rel = next((r for name in card["repos"] if (r := _dir_rel(gc, name, d)) is not None), None)
        if rel is None:
            raise _Reject("unknown_dir", f"{d} is not a directory at the repo ref")
        if rel and rel not in dirs:
            dirs.append(rel)
    card["dirs"] = dirs

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

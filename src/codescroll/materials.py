"""Evidence attached to a packet's leads, so a writer can write without tool calls.

Everything here is read-only and goes through `gitq`. A lead is the `asdict` of a
`brief.Lead`. Bad coordinates give "" (the writer can still research), never an error.
"""

from __future__ import annotations

import re
from collections import Counter

from codescroll import candidates, gitq, links, research, secrets, structure
from codescroll.brief import _useful
from codescroll.profiles import fileset_for

LEAD_CAP = 4 * 1024  # bytes of materials per lead
# Story types whose writers must explain behaviour get callers, definitions and imports too.
EXPLAIN_TYPES = frozenset(
    {
        "what_it_does",
        "journey",
        "analogy",
        "snippet_callouts",
        "cursed_clever_line",
        "quiz",
        "this_or_that",
        "spot_the_bug",
    }
)
EXPLAIN_LEAD_CAP = 6 * 1024
MAX_SYMBOLS = 4
MAX_CALLERS = 10
MAX_IMPORTS = 15
MIN_SYMBOL_LEN = 3
LINE_CLIP = 120
# bytes of materials per packet: get_packet must stay small enough for the harness to show it
# inline (a ~50 KB reply was saved to a file the writer could not read).
PACKET_CAP = 12 * 1024
LEADS_PER_TYPE = 2  # materials for the top leads of each story type; a writer uses 1 or 2
STAT_FILES = 15
DIFF_LINES = 80
WINDOW_LINES = 60
WHY_LIMIT = 3
WHY_BODY_CHARS = 600
_ISSUE_REF = re.compile(r"#\d+|/(?:issues|pull)/\d+")
_PR_REF = re.compile(r"\(#(\d+)\)")
MARKER = "[truncated]"
NOTE = "Materials attached for the leads below. Research only what is missing."


def _cap(text: str, limit: int) -> str:
    raw = text.encode()
    if len(raw) <= limit:
        return text
    return raw[:limit].decode(errors="ignore").rstrip() + f"\n{MARKER}"


def _trim_body(body: str) -> str:
    body = body.strip()
    if len(body) <= WHY_BODY_CHARS:
        return body
    return body[:WHY_BODY_CHARS].rstrip() + " …"


def _pr_url(cfg, repo: str, subject: str) -> str | None:
    m = _PR_REF.search(subject)
    base = m and links.repo_url(cfg, repo)
    return f"{base}/pull/{m.group(1)}" if base else None


def why_commits(cfg, repo: str, path: str, limit: int = WHY_LIMIT) -> list[dict]:
    """The commits touching `path` that most likely explain why it changed.

    A commit counts when its body has at least `analysis.why_min_words` words or its subject
    or body refers to an issue or PR (`#123`). Longest body first, then newest, inside the
    analysis window counted back from the ref's last commit. Each item is
    `{sha, date, subject, body, pr_url}` with `body` trimmed to WHY_BODY_CHARS and `pr_url`
    set only when the subject has `(#N)` and the repo has a GitHub URL. [] on bad input.
    """
    if limit <= 0:
        return []
    try:
        root, ref = research._resolve(cfg, repo, None)
        an = cfg.settings.analysis
        since = gitq.commit_time(root, ref) - an.history_window_days * 86400
        rows = gitq.path_messages(root, ref, path, since)
    except (research.ResearchError, gitq.GitError, ValueError):
        return []
    picked = [
        r
        for r in rows
        if len(r["body"].split()) >= an.why_min_words
        or _ISSUE_REF.search(r["subject"])
        or _ISSUE_REF.search(r["body"])
    ]
    picked.sort(key=lambda r: len(r["body"]), reverse=True)  # stable: newest first among ties
    return [
        {
            "sha": r["sha"],
            "date": r["date"],
            "subject": r["subject"],
            "body": _trim_body(r["body"]),
            "pr_url": _pr_url(cfg, repo, r["subject"]),
        }
        for r in picked[:limit]
    ]


def _why_entry(c: dict) -> str:
    head = f"- {c['sha'][:7]} {c['date']}: {c['subject']}"
    if c["pr_url"]:
        head += f" ({c['pr_url']})"
    body = "\n".join("  " + ln for ln in c["body"].splitlines())
    return head + ("\n" + body if body else "")


def _why_section(cfg, lead: dict, room: int) -> str:
    """The "Why it changed" block, whole commits only, at most `room` bytes; "" if none fit."""
    entries: list[str] = []
    used = len("Why it changed:\n")
    for c in why_commits(cfg, lead["repo"], lead["path"]):
        e = _why_entry(c)
        if used + len(e.encode()) + 1 > room:
            break
        entries.append(e)
        used += len(e.encode()) + 1
    return "Why it changed:\n" + "\n".join(entries) if entries else ""


def _lang_for(path: str):
    name = path.rsplit("/", 1)[-1]
    ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
    for lang in candidates.compiled_languages().values():
        if ext in lang.raw["extensions"]:
            return lang
    return None


def _def_patterns(lang) -> list[re.Pattern]:
    pats = [re.compile(p) for p in lang.raw.get("def_patterns") or ()]
    return ([lang.func_start] if lang.func_start else []) + pats


def _defined_names(lang, lines: list[str]) -> list[str]:
    """Symbols defined on `lines`, in order, without duplicates."""
    names: list[str] = []
    for ln in lines:
        for pat in _def_patterns(lang):
            m = pat.match(ln)
            name = m and candidates._first_group(m)
            if name and name not in names:
                names.append(name)
                break
    return names


def _clip_line(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= LINE_CLIP else text[: LINE_CLIP - 1] + "…"


MAX_PARSED = 40  # files read through the structure layer to check call sites


class _RefIndex:
    """Which names are real references (not comments or strings) on which lines of a file,
    from the structure layer. A file it cannot read has no entry: every hit in it stays."""

    def __init__(self, root, ref: str, queries: dict | None):
        self.root, self.ref, self.queries = root, ref, queries
        self.by_file: dict[str, dict[int, set[str]] | None] = {}

    def is_ref(self, path: str, line: int, name: str) -> bool:
        if path not in self.by_file:
            self.by_file[path] = self._load(path) if len(self.by_file) < MAX_PARSED else None
        index = self.by_file[path]
        return True if index is None else name in index.get(line, ())

    def _load(self, path: str):
        if not structure.available() or structure.grammar_for(path, self.queries) is None:
            return None
        try:
            data = gitq.show_file(self.root, self.ref, path)
        except gitq.GitError:
            return None
        if b"\0" in data[:8192]:
            return None
        text = "\n".join(gitq.split_lines(data.decode(errors="replace")))
        facts = structure.parse(path, text, self.queries)
        if facts is None:
            return None
        index: dict[int, set[str]] = {}
        for nm, line in facts.refs:
            index.setdefault(line, set()).add(nm.rsplit("/", 1)[-1])
        return index


def _called_from(
    root,
    ref: str,
    lang,
    path: str,
    names: list[str],
    files=None,
    facts=None,
    queries: dict | None = None,
) -> list[str]:
    """Up to MAX_CALLERS "path:line: text" call sites, non-test files first. With the structure
    layer a `git grep -w` hit counts only when the name is a reference on that line (not text
    in a comment or a string); without it every hit counts."""
    pats = _def_patterns(lang) if lang else []
    own = {(d.name, d.start) for d in facts.defs} if facts else set()
    refs = _RefIndex(root, ref, queries) if structure.available() else None
    fs = files or fileset_for(None)
    per_symbol: list[list[tuple[bool, str, int, str]]] = []
    seen: set[tuple[str, int]] = set()
    for name in [n for n in names if len(n) >= MIN_SYMBOL_LEN][:MAX_SYMBOLS]:
        hits = []
        rows = [
            (p, num, text)
            for p, num, text in gitq.grep_word(root, ref, name)
            if (p, num) not in seen and not fs.ignored(p)
        ]
        rows.sort(key=lambda r: (fs.is_test(r[0]), r[0], r[1]))
        for p, num, text in rows:
            if p == path and (
                (name, num) in own
                or any(
                    (m := pat.match(text)) and candidates._first_group(m) == name for pat in pats
                )
            ):
                continue
            if refs is not None and not refs.is_ref(p, num, name):
                continue
            seen.add((p, num))
            hits.append((fs.is_test(p), p, num, text))
        hits.sort(key=lambda h: (h[0], h[1], h[2]))
        per_symbol.append(hits)
    picked: list[tuple[bool, str, int, str]] = []
    # round robin over symbols so one popular name does not use every slot
    while len(picked) < MAX_CALLERS and any(per_symbol):
        for hits in per_symbol:
            if hits and len(picked) < MAX_CALLERS:
                picked.append(hits.pop(0))
    picked.sort(key=lambda h: (h[0], h[1], h[2]))
    return [f"{p}:{num}: {_clip_line(text)}" for _, p, num, text in picked]


def _import_lines(lang, lines: list[str], facts=None) -> list[str]:
    out = []
    if lang is None or (facts is not None and not lang.imports):
        for imp in facts.imports if facts else ():
            out.append(_clip_line(imp.text.splitlines()[0]))
            if len(out) >= MAX_IMPORTS:
                break
        return out
    for ln in lines:
        if any(p.search(ln) for p in lang.imports):
            out.append(_clip_line(ln))
            if len(out) >= MAX_IMPORTS:
                break
    return out


def _defined_in(facts, start: int, end: int) -> list[str]:
    """Names of the definitions that start in lines start..end, from the structure layer."""
    names: list[str] = []
    for d in facts.defs:
        if start <= d.start <= end and (d.kind != "var" or d.top) and d.name not in names:
            names.append(d.name)
    return names


def _fit_lines(title: str, rows: list[str], room: int) -> str:
    """`title` plus as many whole `rows` as fit in `room` bytes; "" when none fit."""
    used = len(title.encode()) + 2
    kept = []
    for r in rows:
        used += len(r.encode()) + 1
        if used > room:
            break
        kept.append(r)
    return title + "\n" + "\n".join(kept) if kept else ""


def _commit_materials(cfg, root, lead: dict) -> str:
    sha = gitq.rev_parse(root, lead["commit"])
    cap = cfg.settings.research.max_output_bytes
    head = gitq.run(root, "show", "-s", "--date=short", "--format=%an%x1f%ad%x1f%s%x1f%b", sha)
    author, date, subject, body = head.rstrip("\n").split("\x1f", 3)
    pr = _pr_url(cfg, lead["repo"], subject)
    stat = gitq.split_lines(
        gitq.run(root, "show", "--format=", "--stat", "--stat-width=100", sha, max_bytes=cap)
    )
    files, summary = stat[:-1], stat[-1:]
    shown = files[:STAT_FILES] + (
        [f" … {len(files) - STAT_FILES} more files"] if len(files) > STAT_FILES else []
    )
    out = [
        f"commit {sha[:10]} by {author} on {date}: {subject}",
        *([f"pull request: {pr}"] if pr else []),
        *(["", _trim_body(body)] if body.strip() else []),
        "",
        "```",
        *shown,
        *summary,
        "```",
    ]
    numstat = gitq.run(root, "show", "--format=", "--numstat", sha, max_bytes=cap)
    changed: dict[str, int] = {}
    for row in gitq.split_lines(numstat):
        add, _, rest = row.partition("\t")
        dele, _, path = rest.partition("\t")
        if add.isdigit() and dele.isdigit() and "=>" not in path and _useful(path):
            changed[path] = int(add) + int(dele)
    if changed:
        want = lead.get("path")
        top = want if want in changed else max(changed, key=lambda p: (changed[p], p))
        diff = gitq.split_lines(
            gitq.run(
                root,
                "show",
                "--format=",
                "--no-color",
                "--no-ext-diff",
                sha,
                "--",
                top,
                max_bytes=cap,
            )
        )
        more = len(diff) - DIFF_LINES
        out += ["", f"diff of {top}:", "```diff", *diff[:DIFF_LINES], "```"]
        if more > 0:
            out.append(f"{MARKER} diff: {more} more lines")
    return "\n".join(out)


FACTS_IN_WINDOW = 12  # fact rows listed per cited window


def _fact_line(r: dict) -> str:
    fid, src = r.get("fact_id", "?"), r.get("source", "")
    if "callee_name" in r:
        what = f"`{r.get('caller_symbol')}` calls `{r['callee_name']}` at L{r.get('line')}"
    elif "start" in r and "symbol" in r:
        what = f"defines `{r['symbol']}` L{r['start']}-{r.get('end')}"
    elif "module_text" in r:
        what = f"imports `{r['module_text']}` at L{r.get('line')}"
    else:
        what = f"{r.get('kind', 'fact')} `{r.get('symbol', '')}` at L{r.get('line')}"
    return f"- {fid} {what} ({src})"


def _facts_section(cfg, repo: str | None, path: str, start: int, end: int) -> str:
    """Stored facts inside the cited window, with their ids, so the writer can list them in
    `facts` without a tool call. "" when the store has none."""
    from codescroll import fact_tools  # local: fact_tools imports research too

    if not repo or end < start:
        return ""
    try:
        rows = fact_tools.facts_for(cfg, repo, path, start, end, FACTS_IN_WINDOW)
    except Exception:  # noqa: BLE001 - facts are a bonus; materials never fail on them
        return ""
    if not rows:
        return ""
    head = "Facts in these lines (list the ids your card relies on in `facts`):"
    return "\n".join([head, *(_fact_line(r) for r in rows)])


def _path_materials(cfg, root, ref: str, lead: dict) -> str:
    path = lead["path"]
    if gitq.object_type(root, ref, path) != "blob":
        return ""
    data = gitq.show_file(root, ref, path)
    if b"\0" in data[:8192]:
        return ""
    blob = gitq.run(root, "rev-parse", f"{ref}:{path}").strip()
    # whole file first, so a window that starts inside a key block is still masked
    lines = gitq.split_lines(secrets.guard(cfg, data.decode(errors="replace")))
    total = len(lines)
    span = lead.get("lines")
    start = 1
    if span:
        mid = (span[0] + span[1]) // 2
        start = max(1, min(mid - WINDOW_LINES // 2, total - WINDOW_LINES + 1))
    end = min(total, start + WINDOW_LINES - 1)
    numbered = [f"{i}\t{ln}" for i, ln in enumerate(lines[start - 1 : end], start)]
    out = [
        f"{path} at {ref}: blob {blob[:10]}, {total} lines; lines {start}-{end}:",
        "```",
        *numbered,
        "```",
    ]
    if end < total:
        out.append(f"… {total - end} more lines after {end}")
    if end >= start:
        rows = gitq.blame_range(root, ref, path, start, end)
        shares = Counter(r["author"] for r in rows).most_common(3)
        out.append(
            "blame for those lines: "
            + ", ".join(f"{a} {round(100 * n / len(rows))}%" for a, n in shares)
        )
    dates = gitq.split_lines(gitq.run(root, "log", "--date=short", "--format=%ad", ref, "--", path))
    if dates:
        out.append(f"first commit touching it: {dates[-1]}; last: {dates[0]}")
    known = lead.get("repo") in getattr(cfg, "repos", {})
    fact_block = _facts_section(cfg, lead.get("repo") if known else None, path, start, end)
    if fact_block:
        out.append(fact_block)
    text = "\n".join(out)
    explain = lead.get("story_type") in EXPLAIN_TYPES
    files = cfg.fileset(lead["repo"]) if lead.get("repo") in getattr(cfg, "repos", {}) else None
    cap = EXPLAIN_LEAD_CAP if explain else LEAD_CAP
    sections: list[str] = []
    lang = _lang_for(path) if explain else None
    repo = lead.get("repo")
    queries = cfg.profile(repo).queries if repo in getattr(cfg, "repos", {}) else None
    facts = (
        structure.parse(path, "\n".join(lines), queries)
        if explain and structure.available()
        else None
    )
    if lang or facts:
        names = (
            _defined_in(facts, start, end)
            if facts
            else _defined_names(lang, lines[start - 1 : end])
        )
        room = cap - len(text.encode())
        defs = _fit_lines("Defines:", [", ".join(names)] if names else [], room)
        if defs:
            sections.append(defs)
            room -= len(defs.encode()) + 2
        calls = _called_from(root, ref, lang, path, names, files, facts, queries) if names else []
        called = _fit_lines("Called from:", calls, room)
        if called:
            sections.append(called)
            room -= len(called.encode()) + 2
        why = _why_section(cfg, lead, room)
        if why:
            sections.append(why)
            room -= len(why.encode()) + 2
        imps = _fit_lines("Imports:", _import_lines(lang, lines, facts), room)
        if imps:
            sections.append(imps)
    else:
        why = _why_section(cfg, lead, cap - len(text.encode()) - 2)
        if why:
            sections.append(why)
    return "\n\n".join([text, *sections])


def materials_for(cfg, lead: dict, cache: dict | None = None) -> str:
    """Markdown evidence for one lead (a `Lead` as a dict); "" when there is none."""
    kind = lead.get("kind")
    if kind not in ("commit", "path"):
        return ""
    span = lead.get("lines")
    explain = lead.get("story_type") in EXPLAIN_TYPES
    key = (lead.get("repo"), kind, lead.get("commit"), lead.get("path"), tuple(span or ()), explain)
    if cache is not None and key in cache:
        return cache[key]
    try:
        root, ref = research._resolve(cfg, lead["repo"], None)
        if kind == "commit":
            text = _commit_materials(cfg, root, lead)
        else:
            text = _path_materials(cfg, root, ref, lead)
    except (research.ResearchError, gitq.GitError, KeyError, TypeError, ValueError, OSError):
        text = ""
    text = _cap(secrets.guard(cfg, text), EXPLAIN_LEAD_CAP if explain else LEAD_CAP)
    if cache is not None:
        cache[key] = text
    return text


def packet_materials(cfg, refs: list[dict]) -> str:
    """Materials for the top LEADS_PER_TYPE leads of each story type, at most PACKET_CAP bytes."""
    cache: dict = {}
    parts: list[str] = []
    used = 0
    per_type: dict[str, int] = {}
    for lead in refs:
        if per_type.get(lead["story_type"], 0) >= LEADS_PER_TYPE:
            continue
        per_type[lead["story_type"]] = per_type.get(lead["story_type"], 0) + 1
        body = materials_for(cfg, lead, cache)
        if not body:
            continue
        part = f"### [{lead['story_type']}] {lead['text'][:100]}\n\n{body}"
        room = PACKET_CAP - used
        if len(part.encode()) > room:
            parts.append(_cap(part, max(room, 0)) if room > 200 else MARKER)
            break
        parts.append(part)
        used += len(part.encode()) + 2
    if not parts:
        return ""
    return NOTE + "\n\n" + "\n\n".join(parts)

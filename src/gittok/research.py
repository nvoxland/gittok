"""Read-only repo research tools exposed to the card-writing agent."""

from __future__ import annotations

import re

from gittok import gitq, secrets
from gittok.config import unknown_repo

MAX_LOG = 200  # commits one git_log call returns at most


class ResearchError(Exception):
    """Message is shown to the agent: keep it short and actionable."""


def has_commits(root) -> bool:
    """False when the repo at `root` has no commit on any ref. True when git cannot tell."""
    try:
        return bool(gitq.run(root, "rev-list", "--max-count=1", "--all").strip())
    except gitq.GitError:
        return True


def git_cause(repo, error: Exception) -> str:
    """One line for a git failure in a configured repo. A repo with no commits says so,
    because git's own message for it ("unknown revision") does not."""
    if not has_commits(repo.path):
        return f"repo '{repo.name}' has no commits yet. Make the first commit, then try again."
    return str(error)


def _clean_path(path: str) -> str:
    if "\0" in path:
        raise ResearchError("invalid path: contains NUL")
    if path.startswith("/"):
        raise ResearchError(f"path must be relative to the repo root: {path}")
    if path.startswith("-"):
        raise ResearchError(f"invalid path (leading '-'): {path}")
    parts = [p for p in path.split("/") if p not in ("", ".")]
    if ".." in parts:
        raise ResearchError(f"path must stay inside the repo (no '..'): {path}")
    return "/".join(parts)


def _resolve(cfg, repo: str, ref: str | None):
    r = cfg.repos.get(repo)
    if r is None:
        raise ResearchError(unknown_repo(cfg.repos, repo))
    ref = ref or r.ref
    try:
        gitq.rev_parse(r.path, ref)
    except gitq.GitError as e:
        raise ResearchError(f"unknown or invalid ref: {ref}") from e
    return r.path, ref


def _check_span(lines, limit: int) -> tuple[int, int]:
    try:
        start, end = lines
        ok = isinstance(start, int) and isinstance(end, int)
    except (TypeError, ValueError):
        ok = False
    if not ok:
        raise ResearchError(f"lines must be [start, end] with two integers; got {lines!r}")
    if start < 1 or end < start:
        raise ResearchError(f"invalid lines {list(lines)}: need 1 <= a <= b")
    return start, min(end, start + limit - 1)


def _git(cfg, root, *args: str) -> str:
    try:
        return gitq.run(root, *args, max_bytes=cfg.settings.research.max_output_bytes)
    except gitq.GitError as e:
        raise ResearchError(f"git {args[0]} failed: {str(e).rsplit(': ', 1)[-1]}") from e


def read_file(cfg, repo: str, path: str, ref=None, lines=None) -> str:
    path = _clean_path(path)
    root, ref = _resolve(cfg, repo, ref)
    if gitq.object_type(root, ref, path) == "tree":
        raise ResearchError(f"{path or '.'} is a directory; use list_dir")
    try:
        _, data = gitq.run_bytes(
            root,
            "cat-file",
            "blob",
            f"{ref}:{path}",
            max_bytes=cfg.settings.research.max_output_bytes,
        )
    except gitq.GitError as e:
        raise ResearchError(f"path not found at {ref}: {path}") from e
    if b"\0" in data[:8192]:
        raise ResearchError(f"binary file: {path}")
    text = secrets.guard(cfg, data.decode(errors="replace"))
    all_lines = gitq.split_lines(text)
    limit = cfg.settings.research.max_read_lines
    if lines is None:
        shown = all_lines[:limit]
        start = 1
    else:
        start, end = _check_span(lines, limit)
        shown = all_lines[start - 1 : end]
    out = "\n".join(f"{i}\t{line}" for i, line in enumerate(shown, start))
    if lines is None and len(all_lines) > limit:
        out += f"\n… file has {len(all_lines)} lines; pass lines=[a,b]"
    return out


def list_dir(cfg, repo: str, path: str = "", ref=None) -> str:
    path = _clean_path(path)
    root, ref = _resolve(cfg, repo, ref)
    if path:
        kind = gitq.object_type(root, ref, path)
        if kind is None:
            raise ResearchError(f"path not found at {ref}: {path}")
        if kind != "tree":
            raise ResearchError(f"{path} is a file; use read_file")
    out = _git(cfg, root, "ls-tree", "--format=%(objecttype) %(path)", f"{ref}:{path}")
    dirs, files = [], []
    for row in gitq.split_lines(out):
        kind, _, name = row.partition(" ")
        name = name.rsplit("/", 1)[-1]
        (dirs if kind == "tree" else files).append(name + "/" if kind == "tree" else name)
    return "\n".join(sorted(dirs) + sorted(files))


# Perl-style classes as POSIX classes, for a git built without PCRE: (outside a bracket
# expression, inside one). The negated forms have no form inside brackets.
_POSIX = {
    "s": ("[[:space:]]", "[:space:]"),
    "S": ("[^[:space:]]", None),
    "w": ("[[:alnum:]_]", "[:alnum:]_"),
    "W": ("[^[:alnum:]_]", None),
    "d": ("[0-9]", "0-9"),
    "D": ("[^0-9]", None),
}
MAX_PATHSPECS = 32


def posix_classes(pattern: str) -> str:
    """`pattern` with `\\s`, `\\w`, `\\d` (and the negated forms) as POSIX classes."""
    out, i, in_bracket = [], 0, False
    while i < len(pattern):
        c = pattern[i]
        if c == "\\" and i + 1 < len(pattern):
            nxt = pattern[i + 1]
            form = _POSIX.get(nxt, (None, None))[1 if in_bracket else 0]
            out.append(form if form is not None else c + nxt)
            i += 2
            continue
        if c == "[" and not in_bracket:
            in_bracket = True
            out.append(c)
            i += 1
            if i < len(pattern) and pattern[i] == "^":
                out.append("^")
                i += 1
            if i < len(pattern) and pattern[i] == "]":  # a literal ] first in the bracket
                out.append("]")
                i += 1
            continue
        if c == "]" and in_bracket:
            in_bracket = False
        out.append(c)
        i += 1
    return "".join(out)


def expand_braces(spec: str) -> list[str]:
    """`src/{a,b}.py` -> [`src/a.py`, `src/b.py`]. Git pathspecs have no braces."""
    m = re.search(r"\{([^{}]*,[^{}]*)\}", spec)
    if not m:
        return [spec]
    out: list[str] = []
    for part in m.group(1).split(","):
        out += expand_braces(spec[: m.start()] + part + spec[m.end() :])
        if len(out) > MAX_PATHSPECS:
            raise ResearchError(f"pathspec {spec!r} expands to more than {MAX_PATHSPECS} paths")
    return out


def _no_pcre(e: gitq.GitError) -> bool:
    text = str(e).lower()
    return "perl" in text or "pcre" in text


def git_grep(
    cfg,
    repo: str,
    pattern: str,
    pathspec: str | None = None,
    ref=None,
    limit: int = 100,
    fixed: bool = False,
) -> str:
    """Search file contents; at most `limit` hits. The pattern is a Perl-style regex (`\\s`,
    `\\w`, `\\d` work), as the profile rules are. `pathspec` keeps git glob behavior
    (e.g. `src/*.py`) and takes braces (`src/{a,b}.py`); every other tool treats paths
    literally."""
    if limit < 1:
        raise ResearchError("limit must be >= 1")
    root, ref = _resolve(cfg, repo, ref)
    specs = expand_braces(spec) if pathspec and (spec := _clean_path(pathspec)) else []

    def run(mode: str, pat: str) -> bytes:
        args = ["grep", "-n", "-I", mode, "-e", pat, ref, "--", *specs]
        _, data = gitq.run_bytes(
            root,
            *args,
            ok_codes=(0, 1),
            max_bytes=cfg.settings.research.max_output_bytes,
            literal_pathspecs=False,
        )
        return data

    try:
        if fixed:
            data = run("-F", pattern)
        else:
            try:
                data = run("-P", pattern)
            except gitq.GitError as e:
                if not _no_pcre(e):
                    raise
                data = run("-E", posix_classes(pattern))  # a git built without PCRE
    except gitq.GitError as e:
        detail = str(e).rsplit(": ", 1)[-1]
        raise ResearchError(f"git grep failed: {detail}") from e
    prefix = f"{ref}:"
    hits = [
        h[len(prefix) :] if h.startswith(prefix) else h
        for h in gitq.split_lines(data.decode(errors="replace"))
    ]
    if not hits:
        return "no matches"
    extra = len(hits) - limit
    if extra > 0:
        hits = [*hits[:limit], f"… {extra} more"]
    return secrets.guard(cfg, "\n".join(hits))


def git_log(
    cfg,
    repo: str,
    path: str | None = None,
    since: str | None = None,
    limit: int = 50,
    grep: str | None = None,
    ref=None,
) -> str:
    if limit < 1:
        raise ResearchError("limit must be >= 1")
    root, ref = _resolve(cfg, repo, ref)
    args = ["log", f"--max-count={min(limit, MAX_LOG)}", "--date=short", "--format=%h %ad %an %s"]
    if since:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", since):
            raise ResearchError(f"since must be YYYY-MM-DD: {since}")
        args.append(f"--since={since} 00:00:00 +0000")  # UTC start of day, not "now" on that date
    if grep:
        args += ["--regexp-ignore-case", f"--grep={grep}"]
    args += [ref, "--"]
    if path and (spec := _clean_path(path)):
        args.append(spec)
    return secrets.guard(cfg, _git(cfg, root, *args).rstrip("\n")) or "no commits"


def git_show(cfg, repo: str, commit: str, path: str | None = None, stat: bool = False) -> str:
    root, _ = _resolve(cfg, repo, None)
    try:
        sha = gitq.rev_parse(root, commit)
    except gitq.GitError as e:
        raise ResearchError(f"unknown commit: {commit}") from e
    args = ["show", "--date=short", "--format=commit %H%nAuthor: %an%nDate:   %ad%n%n%B"]
    if stat:
        args.append("--stat")
    args += [sha, "--"]
    if path and (spec := _clean_path(path)):
        args.append(spec)
    return secrets.guard(cfg, _git(cfg, root, *args))


def limit_default(lines, limit: int):
    return (1, limit) if lines is None else lines


def git_blame(cfg, repo: str, path: str, lines=None, ref=None) -> str:
    path = _clean_path(path)
    root, ref = _resolve(cfg, repo, ref)
    limit = cfg.settings.research.max_read_lines
    args = ["blame", "--date=short"]
    start, end = _check_span(limit_default(lines, limit), limit)
    kind = gitq.object_type(root, ref, path) if path else "tree"
    if kind is None:
        raise ResearchError(f"path not found at {ref}: {path}")
    if kind != "blob":
        raise ResearchError(f"{path or '.'} is a directory; use list_dir")
    total = len(gitq.split_lines(gitq.show_file(root, ref, path).decode(errors="replace")))
    if start > total:
        raise ResearchError(f"line range past end of file: {path} has {total} lines")
    args += ["-L", f"{start},{end}", ref, "--", path]
    try:
        out = gitq.run(root, *args, max_bytes=cfg.settings.research.max_output_bytes)
    except gitq.GitError as e:
        raise ResearchError(f"path not found at {ref}: {path}") from e
    return secrets.guard(cfg, out.rstrip("\n"))

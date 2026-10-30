"""The only module that spawns git. Every call is read-only."""

from __future__ import annotations

import os
import re
import subprocess
import threading
from pathlib import Path

HEX_ID_PATTERN = r"[0-9a-f]{7,40}"
_HEX_RE = re.compile(HEX_ID_PATTERN)
TIMEOUT_S = 120
MAX_STDERR_BYTES = 64 * 1024
TRUNCATED_MARKER = "\n…[truncated]"

_ENV_OVERRIDES = {
    "GIT_OPTIONAL_LOCKS": "0",  # never write the index (e.g. from `git status`)
    "GIT_TERMINAL_PROMPT": "0",
    "LC_ALL": "C",
    "GIT_PAGER": "cat",
}


class GitError(Exception):
    pass


def _env() -> dict[str, str]:
    return {**os.environ, **_ENV_OVERRIDES}


def run_bytes(
    repo: Path | str,
    *args: str,
    ok_codes: tuple[int, ...] = (0,),
    max_bytes: int | None = None,
    literal_pathspecs: bool = True,
) -> tuple[int, bytes]:
    """Run git. Pathspecs are literal (no globs or `:(magic)`) unless asked otherwise."""
    lit = ["--literal-pathspecs"] if literal_pathspecs else []
    cmd = ["git", "-C", str(repo), "-c", "core.quotepath=off", "--no-pager", *lit, *args]
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_env(),
        )
    except OSError as e:
        raise GitError(f"git {' '.join(args)} could not start: {e}") from e
    timed_out = threading.Event()

    def _expire() -> None:
        timed_out.set()
        proc.kill()

    timer = threading.Timer(TIMEOUT_S, _expire)
    err_buf = bytearray()

    def _drain_stderr() -> None:
        assert proc.stderr is not None
        while chunk := proc.stderr.read(8192):
            room = MAX_STDERR_BYTES - len(err_buf)
            if room > 0:
                err_buf.extend(chunk[:room])

    err_thread = threading.Thread(target=_drain_stderr, daemon=True)
    chunks: list[bytes] = []
    size = 0
    truncated = False
    timer.start()
    err_thread.start()
    try:
        assert proc.stdout is not None
        while chunk := proc.stdout.read(65536):
            chunks.append(chunk)
            size += len(chunk)
            if max_bytes is not None and size > max_bytes:
                truncated = True
                proc.kill()
                break
    except BaseException:
        proc.kill()
        raise
    finally:
        timer.cancel()
        proc.wait()
        err_thread.join()
        proc.stdout.close()
        proc.stderr.close()
    if timed_out.is_set():
        raise GitError(f"git {' '.join(args)} timed out")
    out = b"".join(chunks)
    if truncated:
        assert max_bytes is not None
        return 0, out[:max_bytes] + TRUNCATED_MARKER.encode()
    if proc.returncode not in ok_codes:
        msg = bytes(err_buf).decode(errors="replace").strip()
        raise GitError(f"git {' '.join(args)} failed ({proc.returncode}): {msg}")
    return proc.returncode, out


def run(repo: Path | str, *args: str, max_bytes: int | None = None) -> str:
    _, out = run_bytes(repo, *args, max_bytes=max_bytes)
    return out.decode(errors="replace")


def _check_rev(rev: str) -> str:
    if not rev or rev.startswith("-") or any(c.isspace() for c in rev):
        raise GitError(f"invalid revision: {rev!r}")
    return rev


def rev_parse(repo: Path | str, rev: str) -> str:
    """Full commit SHA for `rev`, or GitError."""
    _check_rev(rev)
    code, out = run_bytes(
        repo,
        "rev-parse",
        "--verify",
        "--quiet",
        "--end-of-options",
        f"{rev}^{{commit}}",
        ok_codes=(0, 1, 128),
    )
    if code != 0:
        raise GitError(f"unknown commit: {rev}")
    return out.decode().strip()


def resolve_commit_id(repo: Path | str, hexprefix: str) -> str:
    """Full SHA of the one commit whose object id starts with `hexprefix` (7-40 hex chars).

    Unlike `rev_parse`, a branch or tag with the same name is ignored. GitError if no
    commit matches or if the prefix is ambiguous.
    """
    if not _HEX_RE.fullmatch(hexprefix):
        raise GitError(f"not a hex object id: {hexprefix!r}")
    _, out = run_bytes(repo, "rev-parse", f"--disambiguate={hexprefix}", ok_codes=(0, 1, 128))
    commits = []
    for oid in out.decode().split():
        code, kind = run_bytes(repo, "cat-file", "-t", oid, ok_codes=(0, 128))
        if code == 0 and kind.decode().strip() == "commit":
            commits.append(oid)
    if not commits:
        raise GitError(f"unknown commit: {hexprefix}")
    if len(commits) > 1:
        raise GitError(f"ambiguous commit id: {hexprefix} matches {len(commits)} commits")
    return commits[0]


def show_file(repo: Path | str, commit: str, path: str) -> bytes:
    _check_rev(commit)
    code, out = run_bytes(repo, "cat-file", "blob", f"{commit}:{path}", ok_codes=(0, 128))
    if code != 0:
        raise GitError(f"{path} is not a file at {commit}")
    return out


def is_ancestor(repo: Path | str, ancestor: str, descendant: str) -> bool:
    _check_rev(ancestor)
    _check_rev(descendant)
    code, _ = run_bytes(repo, "merge-base", "--is-ancestor", ancestor, descendant, ok_codes=(0, 1))
    return code == 0


def commit_time(repo: Path | str, rev: str) -> int:
    """Committer timestamp (unix seconds) of `rev`."""
    sha = rev_parse(repo, rev)
    return int(run(repo, "log", "-1", "--format=%ct", sha).strip())


def object_type(repo: Path | str, rev: str, path: str) -> str | None:
    """'blob', 'tree', etc. for `rev:path`, or None if it does not exist."""
    _check_rev(rev)
    code, out = run_bytes(repo, "cat-file", "-t", f"{rev}:{path}", ok_codes=(0, 128))
    return out.decode().strip() if code == 0 else None


def split_lines(text: str) -> list[str]:
    """Split like git does: on "\n" only, dropping one trailing empty element and any "\r"."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return [ln[:-1] if ln.endswith("\r") else ln for ln in lines]


_BLAME_HEAD = re.compile(r"^([0-9a-f]{40}) \d+ \d+")
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+")


def blame_range(repo: Path | str, rev: str, path: str, start: int, end: int) -> list[dict]:
    """One `{"sha", "author", "author_time"}` per line of `path` lines start..end at `rev`."""
    _check_rev(rev)
    out = run(repo, "blame", "--line-porcelain", "-L", f"{start},{end}", rev, "--", path)
    rows: list[dict] = []
    for line in out.split("\n"):
        if m := _BLAME_HEAD.match(line):
            rows.append({"sha": m.group(1), "author": "", "author_time": 0, "author_tz": "+0000"})
        elif rows and line.startswith("author "):
            rows[-1]["author"] = line[len("author ") :]
        elif rows and line.startswith("author-time "):
            rows[-1]["author_time"] = int(line[len("author-time ") :])
        elif rows and line.startswith("author-tz "):
            rows[-1]["author_tz"] = line[len("author-tz ") :].strip()
    return rows


def path_removed_by(repo: Path | str, commit: str, path: str) -> bool:
    """True when `path` is not a file at `commit`: a delete or the old side of a rename."""
    return object_type(repo, commit, path) != "blob"


def first_parent(repo: Path | str, rev: str) -> str | None:
    """Full SHA of the first parent of `rev`, or None for a root commit."""
    sha = rev_parse(repo, rev)
    parts = run(repo, "rev-list", "--parents", "-n", "1", sha).split()
    return parts[1] if len(parts) > 1 else None


def changed_old_ranges(repo: Path | str, commit: str, path: str) -> list[tuple[int, int]]:
    """Line ranges of `path` on the first-parent side that `commit` changes.

    A pure insertion after line N reports (N, N). A root commit has no old side: [].
    """
    parent = first_parent(repo, commit)
    if parent is None:
        return []
    out = run(repo, "diff", "--no-color", "--no-ext-diff", "-U0", parent, commit, "--", path)
    ranges = []
    for line in out.split("\n"):
        if m := _HUNK.match(line):
            start = int(m.group(1))
            count = 1 if m.group(2) is None else int(m.group(2))
            ranges.append((start, start + max(count, 1) - 1))
    return ranges


def recent_commits(repo: Path | str, ref: str, since_ts: int) -> list[dict]:
    """Non-merge commits on `ref` newer than `since_ts`, newest first, with changed files."""
    _check_rev(ref)
    out = run(
        repo, "log", ref, "--no-merges", f"--since=@{since_ts}", "--name-only",
        "--format=%x1e%H%x1f%an%x1f%ct%x1f%s", "--end-of-options",
    )  # fmt: skip
    commits = []
    for block in out.split("\x1e")[1:]:
        head, _, rest = block.partition("\n")
        sha, author, ts, subject = head.split("\x1f", 3)
        files = [ln for ln in rest.splitlines() if ln]
        commits.append(
            {"sha": sha, "author": author, "ts": int(ts), "subject": subject, "files": files}
        )
    return commits

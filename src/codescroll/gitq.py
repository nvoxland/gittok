"""The only module that spawns git. Every call is read-only."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

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


def remote_url(repo: Path | str) -> str | None:
    """The `origin` remote URL as configured, or None when there is no origin."""
    code, out = run_bytes(repo, "remote", "get-url", "origin", ok_codes=(0, 2, 128))
    url = out.decode(errors="replace").strip()
    return url if code == 0 and url else None


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


def path_messages(repo: Path | str, ref: str, path: str, since_ts: int) -> list[dict]:
    """Non-merge commits on `ref` touching `path` since `since_ts`, newest first, with bodies."""
    _check_rev(ref)
    out = run(
        repo, "log", ref, "--no-merges", f"--since=@{since_ts}", "--date=short",
        "--format=%x1e%H%x1f%ad%x1f%s%x1f%b", "--end-of-options", "--", path,
    )  # fmt: skip
    rows = []
    for block in out.split("\x1e")[1:]:
        sha, date, subject, body = block.split("\x1f", 3)
        rows.append({"sha": sha, "date": date, "subject": subject, "body": body.strip()})
    return rows


def grep_word(
    repo: Path | str, ref: str, word: str, max_bytes: int = 64 * 1024
) -> list[tuple[str, int, str]]:
    """`git grep -n -w` for a fixed string at `ref`: [(path, line, text)], [] when none."""
    _check_rev(ref)
    _, out = run_bytes(
        repo, "grep", "-n", "-I", "-w", "-F", "-e", word, ref, "--",
        ok_codes=(0, 1), max_bytes=max_bytes,
    )  # fmt: skip
    rows = []
    prefix = f"{ref}:"
    for ln in out.decode(errors="replace").splitlines():
        if not ln.startswith(prefix):
            continue
        path, _, rest = ln[len(prefix) :].partition(":")
        num, _, text = rest.partition(":")
        if num.isdigit():
            rows.append((path, int(num), text))
    return rows


def ls_tree_blobs(repo: Path | str, ref: str) -> dict[str, str]:
    """Path -> blob sha for every file at `ref`, in one call."""
    _check_rev(ref)
    _, out = run_bytes(repo, "ls-tree", "-r", "-z", ref)
    blobs = {}
    for rec in out.decode(errors="replace").split("\0"):
        meta, _, path = rec.partition("\t")  # "<mode> <type> <sha>"
        if path:
            blobs[path] = meta.split()[-1]
    return blobs


def ls_tree_files(repo: Path | str, ref: str) -> list[tuple[str, str, int]]:
    """(path, blob sha, size in bytes) for every regular file at `ref`, in one call."""
    _check_rev(ref)
    _, out = run_bytes(repo, "ls-tree", "-r", "-l", "-z", ref)
    files = []
    for rec in out.decode(errors="replace").split("\0"):
        meta, _, path = rec.partition("\t")  # "<mode> <type> <sha> <size>"
        parts = meta.split()
        if path and len(parts) == 4 and parts[1] == "blob" and parts[3].isdigit():
            files.append((path, parts[2], int(parts[3])))
    return files


def read_blobs(repo: Path | str, shas: list[str], chunk: int = 400) -> dict[str, bytes]:
    """Contents of many blobs through `git cat-file --batch` (a few processes, not one per file)."""
    out: dict[str, bytes] = {}
    for i in range(0, len(shas), chunk):
        batch = shas[i : i + chunk]
        for sha in batch:
            if not _HEX_RE.fullmatch(sha):
                raise GitError(f"invalid blob id: {sha!r}")
        try:
            proc = subprocess.run(
                ["git", "-C", str(repo), "--no-pager", "cat-file", "--batch"],
                input=("\n".join(batch) + "\n").encode(),
                capture_output=True,
                env=_env(),
                timeout=TIMEOUT_S,
                check=True,
            )
        except (OSError, subprocess.SubprocessError) as e:
            raise GitError(f"git cat-file --batch failed: {e}") from e
        data, pos = proc.stdout, 0
        while pos < len(data):
            nl = data.index(b"\n", pos)
            header = data[pos:nl].split()
            if len(header) != 3 or header[1] != b"blob":
                pos = nl + 1  # "<sha> missing"
                continue
            size = int(header[2])
            out[header[0].decode()] = data[nl + 1 : nl + 1 + size]
            pos = nl + 1 + size + 1
    return out


def paths_changed_since(repo: Path | str, ref: str, since_ts: int) -> set[str]:
    """Paths touched by any commit reachable from `ref` and newer than `since_ts`."""
    _check_rev(ref)
    out = run(
        repo, "log", ref, "--no-renames", "--name-only", "--format=", f"--since=@{since_ts}", "--"
    )
    return {ln for ln in out.splitlines() if ln}


FETCH_TIMEOUT_S = 60
_last_fetch: dict[str, float] = {}  # repo path -> time.monotonic() of the last attempt
_fetch_lock = threading.Lock()


def _split_remote_ref(repo: Path | str, ref: str) -> tuple[str, str] | None:
    """('origin', 'master') for the remote-tracking ref 'origin/master'; None for any other ref."""
    if ref.startswith("-") or "/" not in ref:
        return None
    try:
        remotes = run(repo, "remote").split()
    except GitError:
        return None
    for remote in sorted(remotes, key=len, reverse=True):
        prefix = remote + "/"
        if ref.startswith(prefix) and len(ref) > len(prefix):
            code, _ = run_bytes(
                repo, "rev-parse", "--verify", "-q", f"refs/remotes/{ref}", ok_codes=(0, 1)
            )
            return (remote, ref[len(prefix) :]) if code == 0 else None
    return None


def fetch_ref(
    repo: Path | str,
    ref: str,
    min_interval_s: int = 0,
    timeout_s: int = FETCH_TIMEOUT_S,
) -> str:
    """Refresh the remote-tracking ref `ref` (e.g. 'origin/master') from its remote.

    The one write gitq does, and only when the user turned `fetch` on for the repo. It updates
    remote-tracking refs only: never the working tree, the index or local branches.
    Never raises. Returns 'fetched', 'throttled', 'skipped' (not a remote-tracking ref) or 'failed'.
    """
    split = _split_remote_ref(repo, ref)
    if split is None:
        log.info("fetch skipped for %s: %s is not a remote-tracking ref", repo, ref)
        return "skipped"
    key = str(repo)
    with _fetch_lock:
        last = _last_fetch.get(key)
        if last is not None and time.monotonic() - last < min_interval_s:
            return "throttled"
        _last_fetch[key] = time.monotonic()  # failures count too: a dead network is not retried hot
    remote, branch = split
    cmd = ["git", "-C", str(repo), "fetch", "--no-tags", "--quiet", remote, branch]
    try:
        subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            env=_env(),
            timeout=timeout_s,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as e:
        detail = (getattr(e, "stderr", b"") or b"").decode(errors="replace").strip()
        log.warning("fetch %s %s failed, using the old ref: %s %s", repo, ref, e, detail)
        return "failed"
    return "fetched"

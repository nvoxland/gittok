"""The only module that spawns git. Every call is read-only."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

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
) -> tuple[int, bytes]:
    cmd = ["git", "-C", str(repo), "-c", "core.quotepath=off", "--no-pager", *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, env=_env(), timeout=120)
    except subprocess.TimeoutExpired as e:
        raise GitError(f"git {' '.join(args)} timed out") from e
    if proc.returncode not in ok_codes:
        msg = proc.stderr.decode(errors="replace").strip()
        raise GitError(f"git {' '.join(args)} failed ({proc.returncode}): {msg}")
    out = proc.stdout
    if max_bytes is not None and len(out) > max_bytes:
        out = out[:max_bytes] + TRUNCATED_MARKER.encode()
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
        repo, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{rev}^{{commit}}",
        ok_codes=(0, 1, 128),
    )
    if code != 0:
        raise GitError(f"unknown commit: {rev}")
    return out.decode().strip()


def show_file(repo: Path | str, commit: str, path: str) -> bytes:
    _check_rev(commit)
    code, out = run_bytes(repo, "show", f"{commit}:{path}", ok_codes=(0, 128))
    if code != 0:
        raise GitError(f"{path} does not exist at {commit}")
    return out


def is_ancestor(repo: Path | str, ancestor: str, descendant: str) -> bool:
    _check_rev(ancestor)
    _check_rev(descendant)
    code, _ = run_bytes(
        repo, "merge-base", "--is-ancestor", ancestor, descendant, ok_codes=(0, 1)
    )
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

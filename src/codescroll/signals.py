"""Git analysis signals (SPEC §10.2). No LLM. All git access goes through gitq."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from codescroll import gitq


@dataclass(frozen=True)
class FileChange:
    path: str
    added: int | None
    deleted: int | None


@dataclass(frozen=True)
class Commit:
    sha: str
    parents: tuple[str, ...]
    ts: int
    local_hour: int
    author: str
    email: str
    subject: str
    files: tuple[FileChange, ...]


_FORMAT = "--format=%x1e%H%x1f%P%x1f%at%x1f%ai%x1f%aN%x1f%aE%x1f%s"


def parse_log(repo: Path | str, ref: str, since_ts: int | None = None) -> list[Commit]:
    args = ["log", ref, "--no-merges", "--no-renames", "--numstat", "--date=unix", _FORMAT]
    if since_ts is not None:
        args.append(f"--since=@{since_ts}")
    args.append("--")
    out = gitq.run(repo, *args)
    commits = []
    for rec in out.split("\x1e"):
        if not rec.strip():
            continue
        head, _, body = rec.partition("\n")
        sha, parents, ts, ai, author, email, subject = head.split("\x1f", 6)
        files = tuple(f for f in (_parse_numstat(ln) for ln in body.splitlines()) if f)
        commits.append(
            Commit(
                sha=sha,
                parents=tuple(parents.split()),
                ts=int(ts),
                local_hour=int(ai[11:13]),
                author=author,
                email=email,
                subject=subject,
                files=files,
            )
        )
    return commits


def _parse_numstat(line: str) -> FileChange | None:
    parts = line.split("\t", 2)
    if len(parts) != 3:
        return None
    a, d, path = parts
    return FileChange(path, None if a == "-" else int(a), None if d == "-" else int(d))


def _lines(f: FileChange) -> int:
    return (f.added or 0) + (f.deleted or 0)


def _parent_dirs(path: str) -> list[str]:
    parts = path.split("/")[:-1]
    if not parts:
        return ["."]
    return ["/".join(parts[: i + 1]) for i in range(len(parts))]


def _rank(acc: dict[str, list[int]], top: int) -> list[dict]:
    ranked = sorted(acc.items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0]))[:top]
    return [{"path": p, "commits": n, "lines": ln} for p, (n, ln) in ranked]


def churn(commits: list[Commit], t0: int, windows=(30, 90, 365), top=25) -> dict:
    """Per-window churn. A dir counts a commit once, however many of its files changed."""
    files: dict[str, list[dict]] = {}
    dirs: dict[str, list[dict]] = {}
    for days in windows:
        cutoff = t0 - days * 86400
        facc: dict[str, list[int]] = {}
        dacc: dict[str, list[int]] = {}
        for c in commits:
            if c.ts < cutoff:
                continue
            seen: set[str] = set()
            for f in c.files:
                row = facc.setdefault(f.path, [0, 0])
                row[0] += 1
                row[1] += _lines(f)
                for d in _parent_dirs(f.path):
                    drow = dacc.setdefault(d, [0, 0])
                    if d not in seen:
                        drow[0] += 1
                        seen.add(d)
                    drow[1] += _lines(f)
        files[str(days)] = _rank(facc, top)
        dirs[str(days)] = _rank(dacc, top)
    return {"files": files, "dirs": dirs}


def co_change(commits: list[Commit], min_count=3, max_files=20, top=25) -> list[dict]:
    """Pairs of files changed together. jaccard = count / commits touching a or b."""
    touched: dict[str, int] = {}
    pair_counts: dict[tuple[str, str], int] = {}
    for c in commits:
        paths = sorted({f.path for f in c.files})
        for p in paths:
            touched[p] = touched.get(p, 0) + 1
        if len(paths) < 2 or len(paths) > max_files:
            continue
        for i, a in enumerate(paths):
            for b in paths[i + 1 :]:
                pair_counts[(a, b)] = pair_counts.get((a, b), 0) + 1
    rows = []
    for (a, b), n in pair_counts.items():
        if n < min_count:
            continue
        rows.append(
            {
                "a": a,
                "b": b,
                "count": n,
                "jaccard": n / (touched[a] + touched[b] - n),
                "same_dir": _parent_dirs(a)[-1] == _parent_dirs(b)[-1],
            }
        )
    rows.sort(key=lambda r: (-r["count"], -r["jaccard"], r["a"], r["b"]))
    return rows[:top]


def author_shares(commits: list[Commit], top=5) -> dict:
    """Per top-level dir: authors ranked by changed lines, with their line share."""
    acc: dict[str, dict[str, list[int]]] = {}
    for c in commits:
        seen: set[tuple[str, str]] = set()
        for f in c.files:
            top_dir = f.path.split("/")[0] if "/" in f.path else "."
            row = acc.setdefault(top_dir, {}).setdefault(c.author, [0, 0])
            if (top_dir, c.author) not in seen:
                row[0] += 1
                seen.add((top_dir, c.author))
            row[1] += _lines(f)
    by_dir: dict[str, list[dict]] = {}
    for d, authors in sorted(acc.items()):
        total = sum(ln for _, ln in authors.values())
        ranked = sorted(authors.items(), key=lambda kv: (-kv[1][1], -kv[1][0], kv[0]))[:top]
        by_dir[d] = [
            {
                "author": a,
                "commits": n,
                "lines": ln,
                "share": round(ln / total, 3) if total else 0.0,
            }
            for a, (n, ln) in ranked
        ]
    return {"by_dir": by_dir}


def commit_times(commits: list[Commit]) -> dict:
    hist = [0] * 24
    late: list[dict] = []
    by_author: dict[str, int] = {}
    for c in sorted(commits, key=lambda c: -c.ts):
        hist[c.local_hour] += 1
        if c.local_hour >= 23 or c.local_hour < 5:
            by_author[c.author] = by_author.get(c.author, 0) + 1
            late.append(
                {
                    "sha": c.sha,
                    "author": c.author,
                    "local_hour": c.local_hour,
                    "subject": c.subject,
                    "ts": c.ts,
                }
            )
    return {"hour_histogram": hist, "late_night": late[:20], "late_by_author": by_author}


def huge_diffs(commits: list[Commit], threshold=1000, top=10) -> list[dict]:
    """Commits whose added+deleted lines exceed `threshold` (binary files count 0)."""
    rows = [
        {
            "sha": c.sha,
            "subject": c.subject,
            "author": c.author,
            "ts": c.ts,
            "lines": sum(_lines(f) for f in c.files),
            "files": len(c.files),
        }
        for c in commits
    ]
    rows = [r for r in rows if r["lines"] > threshold]
    rows.sort(key=lambda r: (-r["lines"], -r["ts"], r["sha"]))
    return rows[:top]


def new_files(repo: Path | str, ref: str, since_ts: int | None) -> list[dict]:
    args = [
        "log", ref, "--diff-filter=A", "--no-renames", "--name-only",
        "--format=%x1e%H%x1f%at%x1f%aN%x1f%s",
    ]  # fmt: skip
    if since_ts is not None:
        args.append(f"--since=@{since_ts}")
    args.append("--")
    rows: list[dict] = []
    for rec in gitq.run(repo, *args).split("\x1e"):
        if not rec.strip():
            continue
        head, _, body = rec.partition("\n")
        sha, ts, author, subject = head.split("\x1f", 3)
        for path in body.splitlines():
            if path:
                rows.append(
                    {"path": path, "sha": sha, "ts": int(ts), "author": author, "subject": subject}
                )
    return rows

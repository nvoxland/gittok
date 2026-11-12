"""Git analysis signals (SPEC §10.2). No LLM. All git access goes through gitq."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from gittok import candidates, config, conventions, db, facts, gitq, ledger, profiles
from gittok.config import AnalysisSettings, Repo


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
                    "paths": [f.path for f in c.files][:50],
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
            "paths": [f.path for f in c.files][:50],
        }
        for c in commits
    ]
    rows = [r for r in rows if r["lines"] > threshold]
    rows.sort(key=lambda r: (-r["lines"], -r["ts"], r["sha"]))
    return rows[:top]


def new_files(repo: Path | str, ref: str, since_ts: int | None) -> list[dict]:
    args = [
        "log", ref, "--diff-filter=A", "-M", "--name-only",
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


_REVERT_RE = re.compile(r"This reverts commit ([0-9a-f]{7,40})")


def reverts(repo: Path | str, ref: str, since_ts: int | None = None) -> list[dict]:
    args = ["log", ref, '--grep=^Revert "', "--format=%x1e%H%x1f%at%x1f%aN%x1f%s%x1f%b"]
    if since_ts is not None:
        args.append(f"--since=@{since_ts}")
    args.append("--")
    rows: list[dict] = []
    for rec in gitq.run(repo, *args).split("\x1e"):
        if not rec.strip():
            continue
        sha, ts, author, subject, body = rec.strip("\n").split("\x1f", 4)
        m = _REVERT_RE.search(body)
        if not m:
            continue
        try:
            reverted = gitq.run(repo, "log", "-1", "--format=%s", m.group(1)).strip()
        except gitq.GitError:
            continue
        rows.append(
            {
                "sha": sha,
                "ts": int(ts),
                "author": author,
                "subject": subject,
                "reverted_sha": m.group(1),
                "reverted_subject": reverted,
            }
        )
    return rows


_FIX_RE = re.compile(r"^(fix|hotfix|oops|typo)\b|\bfix(es|ed)?\b|\bagain\b", re.IGNORECASE)


def fix_chains(commits: list[Commit], window_days=7, min_len=2) -> list[dict]:
    """Runs of fix-ish commits on one path, each within `window_days` of the previous."""
    per_path: dict[str, list[Commit]] = {}
    for c in sorted(commits, key=lambda c: c.ts):
        if not _FIX_RE.search(c.subject):
            continue
        for p in {f.path for f in c.files}:
            per_path.setdefault(p, []).append(c)
    gap = window_days * 86400
    chains: list[dict] = []
    for path, cs in per_path.items():
        run: list[Commit] = []
        for c in cs:
            if run and c.ts - run[-1].ts > gap:
                _flush_chain(chains, path, run, min_len)
                run = []
            run.append(c)
        _flush_chain(chains, path, run, min_len)
    chains.sort(key=lambda ch: (-len(ch["commits"]), ch["path"]))
    return chains


def _flush_chain(out: list[dict], path: str, run: list[Commit], min_len: int) -> None:
    if len(run) >= min_len:
        out.append(
            {
                "path": path,
                "commits": [
                    {"sha": c.sha, "ts": c.ts, "subject": c.subject, "author": c.author}
                    for c in run
                ],
            }
        )


def added_map(repo: Path | str, ref: str) -> dict[str, list[dict]]:
    """path -> every add ({sha, ts, author}) over the full history, newest first."""
    out: dict[str, list[dict]] = {}
    for r in new_files(repo, ref, None):  # newest first
        out.setdefault(r["path"], []).append(
            {"sha": r["sha"], "ts": r["ts"], "author": r["author"]}
        )
    return out


def _birth_before(adds, died_ts: int) -> dict | None:
    """The latest add at or before `died_ts` (adds is a dict, or a list newest first)."""
    if isinstance(adds, dict):
        return adds
    return next((a for a in adds or [] if a["ts"] <= died_ts), None)


def deleted_paths(
    repo: Path | str,
    ref: str,
    since_ts: int | None = None,
    added: dict[str, list[dict] | dict] | None = None,
) -> list[dict]:
    args = [
        "log", ref, "--diff-filter=D", "-M", "--name-only",
        "--format=%x1e%H%x1f%at%x1f%aN%x1f%s",
    ]  # fmt: skip
    if since_ts is not None:
        args.append(f"--since=@{since_ts}")
    args.append("--")
    if added is None:
        added = added_map(repo, ref)
    rows: list[dict] = []
    for rec in gitq.run(repo, *args).split("\x1e"):
        if not rec.strip():
            continue
        head, _, body = rec.partition("\n")
        sha, ts, author, subject = head.split("\x1f", 3)
        for path in body.splitlines():
            if not path:
                continue
            born = _birth_before(added.get(path), int(ts))
            rows.append(
                {
                    "path": path,
                    "died_sha": sha,
                    "died_ts": int(ts),
                    "died_author": author,
                    "cause": subject,
                    "born_sha": born["sha"] if born else None,
                    "born_ts": born["ts"] if born else None,
                    "born_author": born["author"] if born else None,
                    "lived_days": (int(ts) - born["ts"]) // 86400 if born else None,
                }
            )
    return rows


def commits_since(repo: Path | str, ref: str, last_sha: str | None) -> dict:
    none = {"base": None, "count": None, "commits": []}
    if not last_sha:
        return none
    try:
        base = gitq.rev_parse(repo, last_sha)
        if not gitq.is_ancestor(repo, base, ref):
            return none
    except gitq.GitError:
        return none
    out = gitq.run(
        repo, "log", f"{base}..{ref}", "--no-merges", "--format=%x1e%H%x1f%at%x1f%aN%x1f%s"
    )
    rows = []
    for rec in out.split("\x1e"):
        if not rec.strip():
            continue
        sha, ts, author, subject = rec.strip("\n").split("\x1f", 3)
        rows.append({"sha": sha, "ts": int(ts), "author": author, "subject": subject})
    return {"base": last_sha, "count": len(rows), "commits": rows[:50]}


_TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b")
# \b is not portable in POSIX ERE (macOS libc); spell out the word boundaries for git grep.
_TODO_GREP = "(^|[^[:alnum:]_])(TODO|FIXME|HACK|XXX)([^[:alnum:]_]|$)"


def _parse_blame(out: str) -> list[dict]:
    """Parse `git blame --line-porcelain` into one dict per line."""
    rows: list[dict] = []
    cur: dict | None = None
    for ln in out.split("\n"):
        if cur is None:
            parts = ln.split(" ")
            if len(parts) >= 3 and len(parts[0]) == 40:
                cur = {"sha": parts[0], "line": int(parts[2])}
            continue
        if ln.startswith("\t"):
            cur["text"] = ln[1:]
            rows.append(cur)
            cur = None
        elif ln.startswith("author "):
            cur["author"] = ln[7:]
        elif ln.startswith("author-time "):
            cur["ts"] = int(ln[12:])
    return rows


def todo_ages(repo: Path | str, ref: str, max_hits=150) -> list[dict]:
    out = gitq.run_bytes(
        repo, "grep", "-n", "-z", "-I", "-E", _TODO_GREP, ref, "--", ok_codes=(0, 1)
    )[1].decode(errors="replace")
    prefix = f"{ref}:"
    hits: dict[str, list[tuple[int, str]]] = {}
    n = 0
    for ln in out.split("\n"):
        if ln.startswith(prefix):
            ln = ln[len(prefix) :]
        # -z: "path\0line\0text"; the path may contain ":".
        path, _, rest = ln.partition("\0")
        num, _, text = rest.partition("\0")
        if not num.isdigit():
            continue
        if n >= max_hits:
            break
        hits.setdefault(path, []).append((int(num), text))
        n += 1
    rows: list[dict] = []
    for path, items in hits.items():
        args = ["blame", "--line-porcelain"]
        for num, _ in items:
            args += ["-L", f"{num},{num}"]
        try:
            raw = gitq.run_bytes(repo, *args, ref, "--", path)[1].decode(errors="replace")
        except gitq.GitError:
            continue  # skip this file; one bad blame must not abort the analysis
        blamed = {b["line"]: b for b in _parse_blame(raw)}
        for num, text in items:
            b = blamed.get(num)
            m = _TODO_RE.search(text)
            if not b or not m:
                continue
            rows.append(
                {
                    "path": path,
                    "line": num,
                    "text": text.strip(),
                    "tag": m.group(1),
                    "author": b["author"],
                    "ts": b["ts"],
                    "sha": b["sha"],
                }
            )
    rows.sort(key=lambda r: (r["ts"], r["path"], r["line"]))
    return rows


def _source_files(repo: Path | str, ref: str, max_bytes: int) -> list[str]:
    """Source-like files at `ref` no bigger than `max_bytes`, in ls-tree order."""
    out = gitq.run(repo, "ls-tree", "-r", "-l", ref)
    paths = []
    for ln in out.splitlines():
        meta, _, path = ln.partition("\t")
        parts = meta.split()
        if len(parts) < 4 or parts[1] != "blob" or not parts[3].isdigit():
            continue
        if int(parts[3]) > max_bytes:
            continue
        if Path(path).suffix in config.source_extensions():
            paths.append(path)
    return paths


def oldest_lines(
    repo: Path | str,
    ref: str,
    commits: list[Commit],
    max_files=50,
    max_bytes=2_000_000,
    top=20,
    added: dict[str, list[dict]] | None = None,
) -> list[dict]:
    """Oldest surviving line (by blame author-time) of a bounded set of files.

    The oldest half of the files is chosen by true birth (earliest add in the full
    history); the rest by churn inside the history window.
    """
    candidates = _source_files(repo, ref, max_bytes)
    if added is None:
        added = added_map(repo, ref)
    born: dict[str, int] = {}
    touches: dict[str, int] = {}
    for c in commits:
        for f in c.files:
            born[f.path] = min(born.get(f.path, c.ts), c.ts)
            touches[f.path] = touches.get(f.path, 0) + 1
    for path, adds in added.items():
        if adds:  # true birth beats first appearance inside the window
            born[path] = min(a["ts"] for a in adds)
    order = {p: i for i, p in enumerate(candidates)}
    by_age = sorted(candidates, key=lambda p: (born.get(p, float("inf")), order[p]))
    chosen = by_age[: max_files // 2]
    by_churn = sorted(candidates, key=lambda p: (-touches.get(p, 0), order[p]))
    for p in by_churn:
        if len(chosen) >= max_files:
            break
        if p not in chosen:
            chosen.append(p)
    rows: list[dict] = []
    for path in chosen:
        out = gitq.run_bytes(repo, "blame", "--line-porcelain", ref, "--", path)[1]
        lines = [b for b in _parse_blame(out.decode(errors="replace")) if "ts" in b]
        if not lines:
            continue
        b = min(lines, key=lambda b: (b["ts"], b["line"]))
        rows.append(
            {
                "path": path,
                "line": b["line"],
                "text": b["text"],
                "author": b["author"],
                "ts": b["ts"],
                "sha": b["sha"],
            }
        )
    rows.sort(key=lambda r: (r["ts"], r["path"]))
    return rows[:top]


def recent_commits(commits: list[Commit], t0: int, days=30, limit=200, max_files=20) -> list[dict]:
    """Non-merge commits of the last `days` days before t0, newest first (cross-repo leads)."""
    cutoff = t0 - days * 86400
    rows = sorted((c for c in commits if c.ts >= cutoff), key=lambda c: (-c.ts, c.sha))
    return [
        {
            "sha": c.sha,
            "ts": c.ts,
            "author": c.author,
            "subject": c.subject,
            "files": [f.path for f in c.files][:max_files],
        }
        for c in rows[:limit]
    ]


def fix_hunks(path: Path | str, chains: list[dict], limit: int = 30) -> list[dict]:
    """First parent and old-side changed lines of each fix commit in `chains`.

    Lets spot_the_bug and before_after leads name the buggy version directly, so the
    agent does not have to look it up. At most `limit` commits; git errors skip one.
    """
    out: list[dict] = []
    for chain in chains:
        for c in chain["commits"]:
            if len(out) >= limit:
                return out
            try:
                parent = gitq.first_parent(path, c["sha"])
                ranges = gitq.changed_old_ranges(path, c["sha"], chain["path"])
            except gitq.GitError:
                continue
            if parent and ranges:
                out.append(
                    {
                        "sha": c["sha"],
                        "path": chain["path"],
                        "parent": parent,
                        "ranges": [list(r) for r in ranges],
                    }
                )
    return out


SIGNAL_KINDS = (
    "churn",
    "co_change",
    "author_shares",
    "commit_times",
    "huge_diffs",
    "new_files",
    "reverts",
    "fix_chains",
    "fix_hunks",
    "deleted_paths",
    "commits_since",
    "oldest_lines",
    "todo_ages",
    "recent_commits",
)


def _cached(conn, repo_id: int, head: str) -> dict | None:
    rows = conn.execute(
        "SELECT kind, payload FROM git_signals WHERE repo_id = ? AND head_sha = ?",
        (repo_id, head),
    ).fetchall()
    found = {r["kind"]: db.loads(r["payload"]) for r in rows}
    if not all(k in found for k in SIGNAL_KINDS):
        return None
    return {k: found[k] for k in SIGNAL_KINDS}


def analyze(
    conn, repo: Repo, settings: AnalysisSettings, force: bool = False, profile=None
) -> dict:
    if repo.fetch:  # never raises; a failure keeps the old ref
        gitq.fetch_ref(repo.path, repo.ref, settings.fetch_min_interval_s)
    head = gitq.rev_parse(repo.path, repo.ref)
    t0 = gitq.commit_time(repo.path, head)
    row = conn.execute(
        "SELECT id, last_analyzed_sha FROM repos WHERE name = ?", (repo.name,)
    ).fetchone()
    previous = row["last_analyzed_sha"] if row else None
    meta = {"head_sha": head, "t0": t0, "group": repo.group, "path": str(repo.path)}
    if row and not force and previous == head:
        cached = _cached(conn, row["id"], head)
        if cached is not None:
            facts.refresh(conn, repo.name, repo.path, head, t0, settings, profile)
            conventions.refresh(conn, repo.name, repo.path, head, settings, profile)
            return {**meta, "cached": True, "signals": cached}

    # All git work happens first, with no write transaction open.
    path, ref = repo.path, head
    since = t0 - settings.history_window_days * 86400
    commits = parse_log(path, ref, since)
    added = added_map(path, ref)
    chains = fix_chains(commits)
    steps = {
        "churn": lambda: churn(commits, t0, windows=settings.churn_windows_days),
        "co_change": lambda: co_change(commits),
        "author_shares": lambda: author_shares(commits),
        "commit_times": lambda: commit_times(commits),
        "huge_diffs": lambda: huge_diffs(commits),
        "new_files": lambda: new_files(path, ref, since),
        "reverts": lambda: reverts(path, ref, since),
        "fix_chains": lambda: chains,
        "fix_hunks": lambda: fix_hunks(path, chains),
        "deleted_paths": lambda: deleted_paths(path, ref, since, added=added),
        "commits_since": lambda: commits_since(path, ref, previous),
        "oldest_lines": lambda: oldest_lines(
            path,
            ref,
            commits,
            settings.blame_max_files,
            settings.blame_max_bytes,
            added=added,
        ),
        "todo_ages": lambda: todo_ages(path, ref, settings.todo_max_hits),
        "recent_commits": lambda: recent_commits(commits, t0),
    }
    computed: list[tuple[str, str, int]] = []
    for kind in SIGNAL_KINDS:
        started = time.monotonic()
        text = db.dumps(steps[kind]())
        computed.append((kind, text, int((time.monotonic() - started) * 1000)))

    # Then one short transaction writes everything.
    with db.immediate(conn):
        conn.execute(
            "INSERT INTO repos(name, path, ref, mascot) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET path=excluded.path, ref=excluded.ref, "
            "mascot=excluded.mascot",
            (repo.name, str(repo.path), repo.ref, repo.mascot),
        )
        repo_id = conn.execute("SELECT id FROM repos WHERE name = ?", (repo.name,)).fetchone()[0]
        now = db.now_iso()
        for kind, text, ms in computed:
            conn.execute(
                "INSERT OR REPLACE INTO git_signals"
                "(repo_id, head_sha, kind, payload, computed_at, duration_ms) "
                "VALUES (?,?,?,?,?,?)",
                (repo_id, head, kind, text, now, ms),
            )
        conn.execute(
            "UPDATE repos SET last_analyzed_sha = ?, last_analyzed_at = ? WHERE id = ?",
            (head, now, repo_id),
        )
    result = {kind: db.loads(text) for kind, text, _ in computed}
    candidates.refresh(conn, repo.name, path, head, t0, result, settings, profile)
    ledger.refresh(
        conn,
        repo.name,
        result,
        t0,
        head,
        gitq.ls_tree_blobs(path, ref),
        datetime.now(UTC),
        profiles.fileset_for(profile),
    )
    facts.refresh(conn, repo.name, path, head, t0, settings, profile)
    conventions.refresh(conn, repo.name, path, head, settings, profile)
    return {**meta, "cached": False, "signals": result}


def load_signals(conn, repo_name: str) -> dict | None:
    row = conn.execute(
        "SELECT id, last_analyzed_sha FROM repos WHERE name = ?", (repo_name,)
    ).fetchone()
    if row is None or row["last_analyzed_sha"] is None:
        return None
    rows = conn.execute(
        "SELECT kind, payload FROM git_signals WHERE repo_id = ? AND head_sha = ?",
        (row["id"], row["last_analyzed_sha"]),
    ).fetchall()
    return {r["kind"]: db.loads(r["payload"]) for r in rows} or None

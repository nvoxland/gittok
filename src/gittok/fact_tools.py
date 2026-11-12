"""Read-only fact queries for the writer's MCP tools.

Every row keeps its `fact_id` and `source`. Output is capped and redacted like the other
research tools. An unknown symbol gives `[]`, an unknown repo raises ResearchError.
"""

from __future__ import annotations

from . import db, factcheck, facts, gitq, secrets
from .config import unknown_repo
from .research import ResearchError

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def _limit(n: int) -> int:
    if n < 1:
        raise ResearchError("limit must be >= 1")
    return min(n, MAX_LIMIT)


def _open(cfg, repo: str):
    """`with _open(cfg, repo) as conn:`; the connection is closed when the block ends."""
    if repo not in cfg.repos:
        raise ResearchError(unknown_repo(cfg.repos, repo))
    return db.session(cfg.settings.data_dir / "gittok.db")


def _out(cfg, rows: list[dict]):
    """Drop repo_id, add `rank` (0 analyzer, 1 schema, 2 macro, 3 syntax), best source first."""
    rows = [
        {**{k: v for k, v in r.items() if k != "repo_id"}, "rank": factcheck.rank(r.get("source"))}
        for r in rows
    ]
    rows.sort(key=lambda r: r["rank"])  # stable: the query's own order holds within a rank
    return rows if not cfg.settings.research.redact_secrets else secrets.redact_value(rows)


def defined_where(cfg, repo: str, name: str, limit: int = DEFAULT_LIMIT) -> list[dict]:
    n = _limit(limit)
    with _open(cfg, repo) as conn:
        return _out(cfg, facts.definitions(conn, repo, name)[:n])


def who_calls(cfg, repo: str, symbol: str, limit: int = DEFAULT_LIMIT) -> list[dict]:
    n = _limit(limit)
    with _open(cfg, repo) as conn:
        return _out(cfg, facts.callers_of(conn, repo, symbol, n))


def what_calls(cfg, repo: str, symbol: str, limit: int = DEFAULT_LIMIT) -> list[dict]:
    n = _limit(limit)
    with _open(cfg, repo) as conn:
        return _out(cfg, facts.callees_of(conn, repo, symbol, n))


def symbol_history(cfg, repo: str, symbol: str, limit: int = DEFAULT_LIMIT) -> list[dict]:
    """Touches newest first, each with `sha`, `date` (ISO), and commit `subject`."""
    n = _limit(limit)
    with _open(cfg, repo) as conn:
        touches = facts.touches_of(conn, repo, symbol, n)
    subjects = _subjects(cfg.repos[repo].path, [t["commit_sha"] for t in touches])
    rows = []
    for t in touches:
        sha = t["commit_sha"]
        rows.append({**t, "sha": sha, "date": _iso(t["ts"]), "subject": subjects.get(sha, "")})
    return _out(cfg, rows)


def facts_for(cfg, repo: str, path: str, start: int, end: int | None = None, limit: int = 100):
    n = _limit(limit)
    with _open(cfg, repo) as conn:
        rows = facts.facts_in(conn, repo, path, start, end)
        rid = facts._repo_id(conn, repo)
        rows += facts._rows(
            conn,
            "SELECT * FROM fact_schema WHERE repo_id = ? AND path = ? AND line BETWEEN ? AND ?"
            " ORDER BY line",
            rid, path, start, start if end is None else end,
        )  # fmt: skip
        return _out(cfg, rows)[:n]


def _iso(ts: int) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(ts, UTC).isoformat()


def _subjects(root, shas: list[str]) -> dict[str, str]:
    uniq = sorted(set(shas))
    if not uniq:
        return {}
    try:
        out = gitq.run(root, "show", "-s", "--format=%H%x1f%s", *uniq)
    except gitq.GitError:
        return {}
    pairs = (line.split("\x1f", 1) for line in out.splitlines() if "\x1f" in line)
    return {sha: subject for sha, subject in pairs}

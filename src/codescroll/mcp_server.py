"""CodeScroll MCP server: brief, read-only repo research, and card submission.

A Claude Code (or Codex) session runs the `codescroll-generate` skill against this
server. There is no headless `claude -p` anywhere in CodeScroll.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from codescroll import brief as brief_mod
from codescroll import db, gitq, research, runs, signals, validator
from codescroll.config import Config, ConfigError, load_config

INSTRUCTIONS = """\
CodeScroll turns git history into feed cards. To generate cards, follow the
codescroll-generate skill: call get_brief, hand each work packet to a cheap subagent
(the packet's suggested model) that researches with git_log / git_show / git_blame /
git_grep / read_file / list_dir and returns card JSON, then submit_cards and finish_run.
All repo tools are read-only and take a configured repo name, never a path."""

_ERRORS = (research.ResearchError, runs.RunError, ConfigError, gitq.GitError)
log = logging.getLogger(__name__)


def _db(cfg: Config):
    return db.open_db(cfg.settings.data_dir / "codescroll.db")


def recent_cards(conn, days: int = 30, limit: int = 30) -> list[dict]:
    since = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = conn.execute(
        "SELECT story_type, spec FROM cards WHERE created_at >= ? ORDER BY created_at DESC LIMIT ?",
        (since, limit),
    ).fetchall()
    return [{"story_type": r["story_type"], "hook": db.loads(r["spec"])["hook"]} for r in rows]


def build_server(get_config: Callable[[], Config] = load_config) -> MCPServer:
    server = MCPServer("codescroll", instructions=INSTRUCTIONS)

    def tool(fn):
        """Register `fn`, translate our errors to ToolError, and count calls per run.

        Only calls that name their run count: those passing run_id, plus get_brief on the
        run it opens. Counting never fails a tool call.
        """

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            cfg = get_config()
            try:
                result = fn(cfg, *args, **kwargs)
            except _ERRORS as e:
                raise ToolError(str(e)) from e
            run_id = kwargs.get("run_id")
            if not run_id and fn.__name__ == "get_brief" and isinstance(result, dict):
                run_id = result.get("run_id")
            if run_id:
                try:
                    conn = _db(cfg)
                    try:
                        runs.bump_call(conn, run_id, fn.__name__)
                    finally:
                        conn.close()
                except Exception:
                    log.warning(
                        "could not count %s call for %s", fn.__name__, run_id, exc_info=True
                    )
            return result

        # Hide the cfg parameter from the tool schema.
        import inspect

        sig = inspect.signature(fn)
        wrapper.__signature__ = sig.replace(parameters=list(sig.parameters.values())[1:])
        server.tool()(wrapper)
        return fn

    @tool
    def list_repos(cfg: Config) -> list[dict]:
        """List the configured repos: name, group, ref, and mascot."""
        return [
            {"name": r.name, "group": r.group, "ref": r.ref, "mascot": r.mascot}
            for r in cfg.repos.values()
        ]

    @tool
    def get_brief(cfg: Config, repo: str | None = None, count: int | None = None) -> dict:
        """Analyze the repos (cached by HEAD), open a generation run, and return the brief.

        The brief is split into work packets. Give each packet to one subagent on its
        suggested model, together with that packet's own guidance_markdown (base rules plus
        its format sections). The top-level guidance_markdown is the base rules only.
        Returns run_id for submit_cards.
        """
        count = count or cfg.settings.agent.default_count
        names = [cfg.repo(repo).name] if repo else sorted(cfg.repos)
        with _db(cfg) as conn:
            repo_signals: dict[str, dict] = {}
            skipped: list[dict] = []
            for n in names:
                try:
                    repo_signals[n] = signals.analyze(conn, cfg.repos[n], cfg.settings.analysis)
                except gitq.GitError as e:
                    skipped.append({"repo": n, "error": str(e)})
            if not repo_signals:
                why = "; ".join(f"{s['repo']}: {s['error']}" for s in skipped)
                raise ToolError(f"no repo could be analyzed: {why}")
            b = brief_mod.build_brief(
                repo_signals=repo_signals,
                defaults=cfg.defaults,
                personas=list(cfg.personas),
                count=count,
                packet_size=cfg.settings.agent.packet_size,
                recent=recent_cards(conn),
                max_illustrations=cfg.settings.render.max_illustrations_per_run,
            )
            md = b.to_markdown()
            run_id = runs.open_run(conn, cfg, repo=repo, brief=md, requested=count)
        return {
            "run_id": run_id,
            "brief_markdown": md,
            "guidance_markdown": brief_mod.guidance_markdown(cfg.personas, formats=[]),
            "packets": [
                {
                    **pk,
                    "guidance_markdown": brief_mod.guidance_markdown(
                        cfg.personas, pk["formats"], cfg.meme_templates, cfg.mascots
                    ),
                }
                for pk in b.to_dict()["packets"]
            ],
            "skipped": skipped,
        }

    @tool
    def get_card_schema(cfg: Config) -> dict:
        """The JSON Schema that submit_cards validates against ({"cards": [...]})."""
        return validator.card_schema(list(cfg.personas))

    @tool
    def git_log(
        cfg: Config,
        repo: str,
        path: str | None = None,
        since: str | None = None,
        max: int = 50,
        grep: str | None = None,
        ref: str | None = None,
        run_id: str | None = None,
    ) -> str:
        """Commits as "<sha> <date> <author> <subject>". since is YYYY-MM-DD; max <= 200."""
        return research.git_log(cfg, repo, path=path, since=since, max=max, grep=grep, ref=ref)

    @tool
    def git_show(
        cfg: Config,
        repo: str,
        commit: str,
        path: str | None = None,
        stat: bool = False,
        run_id: str | None = None,
    ) -> str:
        """A commit's header and patch, optionally limited to one path or just --stat."""
        return research.git_show(cfg, repo, commit, path=path, stat=stat)

    @tool
    def git_blame(
        cfg: Config,
        repo: str,
        path: str,
        lines: list[int] | None = None,
        ref: str | None = None,
        run_id: str | None = None,
    ) -> str:
        """Blame for a file, optionally for lines [a, b] (span is capped)."""
        return research.git_blame(cfg, repo, path, lines=tuple(lines) if lines else None, ref=ref)

    @tool
    def git_grep(
        cfg: Config,
        repo: str,
        pattern: str,
        pathspec: str | None = None,
        ref: str | None = None,
        max_hits: int = 100,
        fixed: bool = False,
        run_id: str | None = None,
    ) -> str:
        """Search tracked files at a ref. Extended regex unless fixed=true."""
        return research.git_grep(
            cfg, repo, pattern, pathspec=pathspec, ref=ref, max_hits=max_hits, fixed=fixed
        )

    @tool
    def read_file(
        cfg: Config,
        repo: str,
        path: str,
        ref: str | None = None,
        lines: list[int] | None = None,
        run_id: str | None = None,
    ) -> str:
        """A file at a ref with line numbers. Pass lines=[a, b] for files over 300 lines."""
        return research.read_file(cfg, repo, path, ref=ref, lines=tuple(lines) if lines else None)

    @tool
    def list_dir(
        cfg: Config,
        repo: str,
        path: str = "",
        ref: str | None = None,
        run_id: str | None = None,
    ) -> str:
        """Entries of a directory at a ref; directories end with "/"."""
        return research.list_dir(cfg, repo, path=path, ref=ref)

    @tool
    def submit_cards(cfg: Config, run_id: str, cards: list[dict[str, Any]]) -> dict:
        """Validate cards against git and store the good ones.

        Returns accepted card ids and, for each rejected card, its index, a reason code,
        and a detail message. Fix rejected cards once and resubmit only those.
        """
        with _db(cfg) as conn:
            return runs.submit(conn, cfg, run_id, cards)

    @tool
    def finish_run(cfg: Config, run_id: str, notes: dict[str, Any] | None = None) -> dict:
        """Close the run. Put the models used per packet in notes, e.g. {"models": {...}}."""
        with _db(cfg) as conn:
            summary = runs.finish_run(conn, run_id, notes)
        return summary

    return server


def main() -> None:
    build_server().run("stdio")

# Project Instructions for AI Agents

This file provides instructions and context for AI coding agents working on this project.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:7510c1e2 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Session Completion

This repo has no git remote. When ending a work session:

1. **File issues for remaining work** with `bd create`.
2. **Run quality gates** if code changed: `uv run pytest`, `uv run ruff check`, `npm --prefix web test`.
3. **Update issue status**: close finished work, update in-progress items.
4. **Commit** all changes with a clear message. Do not try to push.
5. **Hand off**: summarize what was done and what is next.
<!-- END BEADS INTEGRATION -->


## Build & Test

```bash
uv sync                          # install Python deps (Python 3.13)
uv run pytest                    # unit tests (live tests skipped unless CODESCROLL_LIVE=1)
uv run ruff check                # lint
npm --prefix web install
npm --prefix web test            # vitest component tests
npm --prefix web run build       # static build into web/build
uv run codescroll serve          # feed at http://127.0.0.1:8008
uv run codescroll mcp            # MCP server over stdio (Claude Code starts it from .mcp.json)
```

Red/green TDD is required: write the failing test first.

## Architecture Overview

CodeScroll (working name; see `SPEC.md`) is a personal TikTok-style feed of cards about your own codebases.

- `src/codescroll/` is a Python package. It analyzes git history into signals, builds a brief, validates card specs against git, stores cards in SQLite, and serves the feed API.
- Card generation does **not** shell out to `claude -p`. A Claude Code session runs the `codescroll-generate` skill. The skill calls the CodeScroll MCP server for a brief, researches repos through read-only MCP tools, and submits card specs back for validation. Cheap subagents (haiku/sonnet) write the cards; the driver only orchestrates.
- `web/` is a SvelteKit static app: vertical snap-scroll feed, horizontal depth panels.
- Config lives in `config/*.yaml`; the card contract is `schema/card.schema.json`; runtime data goes in `data/` (gitignored).

## Conventions & Patterns

- `gitq.py` is the only module that spawns git. Analysis is read-only and never writes to user repos.
- Time windows are relative to the analyzed ref's last commit date, not wall-clock.
- Tests build their own fixture git repo; unit tests never need network or a Claude session.

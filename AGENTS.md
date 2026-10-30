# Agent Instructions

This project uses **bd** (beads) for issue tracking. Run `bd prime` for full workflow context.

> **Architecture in one line:** Issues live in a local Dolt database
> (`.beads/dolt/`); cross-machine sync uses `bd dolt push/pull` (a
> git-compatible protocol), stored under `refs/dolt/data` on your git
> remote — separate from `refs/heads/*` where your code lives.
> `.beads/issues.jsonl` is a passive export, not the wire protocol.
>
> See [SYNC_CONCEPTS.md](https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md)
> for the one-screen overview and anti-patterns (don't treat JSONL as the
> source of truth; don't `bd import` during normal operation; don't
> reach for third-party Dolt hosting before trying the default).

## Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work atomically
bd close <id>         # Complete work
bd dolt push          # Push beads data to remote
```

## Non-Interactive Shell Commands

**ALWAYS use non-interactive flags** with file operations to avoid hanging on confirmation prompts.

Shell commands like `cp`, `mv`, and `rm` may be aliased to include `-i` (interactive) mode on some systems, causing the agent to hang indefinitely waiting for y/n input.

**Use these forms instead:**
```bash
# Force overwrite without prompting
cp -f source dest           # NOT: cp source dest
mv -f source dest           # NOT: mv source dest
rm -f file                  # NOT: rm file

# For recursive operations
rm -rf directory            # NOT: rm -r directory
cp -rf source dest          # NOT: cp -r source dest
```

**Other commands that may prompt:**
- `scp` - use `-o BatchMode=yes` for non-interactive
- `ssh` - use `-o BatchMode=yes` to fail instead of prompting
- `apt-get` - use `-y` flag
- `brew` - use `HOMEBREW_NO_AUTO_UPDATE=1` env var

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

This repo has no git remote. When ending a work session: file issues for remaining work, run quality gates (`uv run pytest`, `uv run ruff check`, `npm --prefix web test`), update issue status, **commit** all changes (do not push), and hand off a short summary.
<!-- END BEADS INTEGRATION -->

## Build & Test

```bash
uv sync                          # install Python deps (Python 3.13)
uv run pytest                    # unit tests (live tests skipped unless CODESCROLL_LIVE=1)
uv run ruff check                # lint
npm --prefix web install
npm --prefix web test            # vitest component tests
npm --prefix web run build       # static build into web/build
uv run codescroll serve          # feed at http://127.0.0.1:8008 and MCP at /mcp
uv run codescroll mcp            # stdio MCP fallback; normally MCP is served by `serve` at /mcp
uv sync --group images           # optional: mflux for mascot illustrations, comics, avatars
uv run codescroll render         # one render pass (serve also renders in the background)
uv run codescroll avatars        # generate persona avatar PNGs (needs the images group)
```

Red/green TDD is required: write the failing test first.

## Architecture Overview

CodeScroll (working name; see `SPEC.md`) is a personal TikTok-style feed of cards about your own codebases.

- `src/codescroll/` is a Python package. It analyzes git history into signals, builds a brief, validates card specs against git, stores cards in SQLite, and serves the feed API.
- **One server process.** `codescroll serve` runs a FastAPI app that serves the feed API, the web build, and the MCP endpoint at `/mcp`. The project `.mcp.json` points Claude Code at `http://127.0.0.1:8008/mcp`, so the server must be running before a generation session. `codescroll mcp` (stdio) is a fallback.
- Card generation does **not** shell out to `claude -p`. A Claude Code session runs the `codescroll-generate` skill (`.claude/skills/`). The skill calls `get_brief`, gives each work packet to a haiku or sonnet subagent that researches through the read-only MCP tools, and submits card specs back for validation. The driver only orchestrates.
- `web/` is a SvelteKit static app: vertical snap-scroll feed, horizontal depth panels.
- Card formats, visual kinds, and the `resolved` shapes the client renders are specified in `docs/formats.md`. Meme, illustration, and comic cards are stored `pending_render` and appear in the feed after the render worker draws them (memegen for memes, mflux for illustrations).
- Config lives in `config/*.yaml`; the card contract is `src/codescroll/schema/card.schema.json`; agent guidance is `src/codescroll/prompts/generate.md`; runtime data goes in `data/` (gitignored).

## Conventions & Patterns

- `gitq.py` is the only module that spawns git. Analysis is read-only and never writes to user repos.
- Time windows are relative to the analyzed ref's last commit date, not wall-clock.
- Tests build their own fixture git repo; unit tests never need network or a Claude session.

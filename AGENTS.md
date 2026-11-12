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
uv run pytest                    # unit tests (live tests skipped unless BLAMESCROLL_LIVE=1)
uv run ruff check                # lint
npm --prefix web install
npm --prefix web test            # vitest component tests
npm --prefix web run build       # static build into web/build
uv run blamescroll mcp --ui --lan # what .mcp.json runs: stdio MCP, plus an auto-reloading feed on :8008 while the session lasts
uv run blamescroll serve          # standalone feed at http://127.0.0.1:8008 and MCP at /mcp (no Claude session)
uv run blamescroll install        # dry run: MCP + skills + LaunchAgent (--apply to do it; see docs/install.md)
uv sync --group images           # optional: mflux for mascot illustrations, comics, avatars
uv run blamescroll structure --prefetch   # download its grammars (once, needs network)
uv run blamescroll render         # one render pass (serve also renders in the background)
uv run blamescroll avatars        # generate persona avatar PNGs (needs the images group)
```

Red/green TDD is required: write the failing test first.

## Architecture Overview

Blamescroll (working name; see `SPEC.md`) is a personal TikTok-style feed of cards about your own codebases.

- `src/blamescroll/` is a Python package. It analyzes git history into signals, builds a brief, validates card specs against git, stores cards in SQLite, and serves the feed API.
- **The session owns the server.** The project `.mcp.json` makes Claude Code start `blamescroll mcp --ui --lan`. That process talks MCP over stdio and starts a child `blamescroll serve --reload` that serves the feed API, the web build, and the render/learning workers on port 8008 for the LAN (pairing token; `/mcp` over HTTP stays loopback-only). The child reloads when a file in `src/blamescroll/` changes, and it exits when the MCP process ends, even after a hard kill. If 8008 is already taken, it runs MCP only. Changes to the MCP tools themselves need `/mcp` → blamescroll → Reconnect. `blamescroll serve` runs the same app without a session.
- Card generation does **not** shell out to `claude -p`. A Claude Code session runs the `blamescroll-generate` skill (`.claude/skills/`). The skill calls `get_brief` and gives each packet id to a `blamescroll-writer` subagent (`.claude/agents/`) on haiku or sonnet. The writer calls `get_packet`, reads the evidence attached to its leads, researches only what is missing, and submits its own cards with `submit_cards(packet_id)`. The driver never handles card JSON.
- **Keeping the feed full.** Two SessionStart hook lines do this. `blamescroll health --hint` prints one line when the feed wants cards now (unseen cards last under `agent.target_runway_days`): run `/blamescroll-generate`. `blamescroll feed-watch --hint` always prints one line: start `uv run --quiet blamescroll feed-watch` with Bash `run_in_background`, once per session. The feed server appends a fixed line to `data/feed-wants-cards.log` when the feed wants cards (not while a run is open, and at most once per `agent.wake_cooldown_hours`). The watch exits on that line. When it exits, run `/blamescroll-generate` without asking, then start the watch again. The `get_brief` daily run cap still applies.
- **Repo profiles.** `local/profiles/<repo>.yaml` holds rules as data (regex or ast-grep patterns, roles, ignore globs) that Blamescroll runs and scores itself (`docs/learning.md`, "Candidate score and repo profiles"). The `blamescroll-profile-repo` skill (sonnet) writes and revises them with `survey_repo`, `test_detector`, `save_profile`, `rule_stats`. `blamescroll health --hint` prints one line when a repo has no profile or its manifests changed; offer `/blamescroll-profile-repo <repo>`, do not start it unasked.
- `web/` is a SvelteKit static app: vertical snap-scroll feed, horizontal depth panels.
- Card formats, visual kinds, and the `resolved` shapes the client renders are specified in `docs/formats.md`. Meme, illustration, and comic cards are stored `pending_render` and appear in the feed after the render worker draws them (memegen for memes, mflux for illustrations).
- Config lives in `config/*.yaml`; the card contract is `src/blamescroll/schema/card.schema.json`; agent guidance is `src/blamescroll/prompts/generate.md`; runtime data goes in `data/` (gitignored).
- **Two roots.** `config.resolve_roots()` gives (shared, home). Shared files (`config/`, `web/build`, `.claude/skills|agents`) come from `cfg.shared_path(...)`; user files (`local/`, relative `data_dir`) come from `cfg.root`. In a clone both are the clone. Installed (`uv tool install`), shared is the wheel's `blamescroll/_bundled/` and home is `BLAMESCROLL_HOME` (default `~/.blamescroll`). Never use `parents[2]`; use `config.shipped_root()`. A wheel needs `web/build` first (`hatch_build.py` checks). See `docs/install.md`.

## Conventions & Patterns

- `gitq.py` is the only module that spawns git. Analysis is read-only and never writes to user repos. One exception: a repo with `fetch: true` in `local/repos.yaml` gets `fetch --no-tags` before analysis. It updates remote-tracking refs only (never the working tree, index or local branches), and only when the user turned it on.
- Time windows are relative to the analyzed ref's last commit date, not wall-clock.
- Tests build their own fixture git repo; unit tests never need network or a Claude session.

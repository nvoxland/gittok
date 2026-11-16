# Agent Instructions

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

## Session Completion

When ending a work session: run the quality gates (`uv run pytest`, `uv run ruff check`, `npm --prefix web test`, and `uv run --only-group docs mkdocs build --strict` when `docs/` changed), and hand off a short summary that lists the changes. Commit only when the user asks, and push only when the user asks.

## Build & Test

```bash
uv sync                          # install Python deps (Python 3.13)
uv run pytest                    # unit tests (live tests skipped unless GITTOK_LIVE=1)
uv run ruff check                # lint
npm --prefix web install
npm --prefix web test            # vitest component tests
npm --prefix web run build       # static build into web/build
uv run gittok mcp --ui       # what .mcp.json runs: stdio MCP, plus an auto-reloading feed on :7313 while the session lasts
uv run gittok serve          # the feed server by hand at http://127.0.0.1:7313 (no session, no MCP); --no-lan for loopback only
uv run gittok init <dir>     # make a GitTok directory (what a user of the installed tool does; see docs/install.md)
uv run gittok update <dir>   # rewrite the files that init owns, after an upgrade
uv sync --group images           # optional: mflux for mascot illustrations, comics, avatars (without it: agent images, SVG in Claude)
uv run gittok structure --prefetch   # download its grammars (once, needs network)
uv run gittok render         # one render pass (serve also renders in the background)
uv run gittok avatars        # generate persona avatar PNGs (needs the images group)
uv run python -m gittok.home   # after editing src/gittok/workflows/: regenerate both agents' skills and workers
```

Red/green TDD is required: write the failing test first. `DEV.md` has the developer guide (setup, running from the clone, building the wheel, the docs site, the release steps). The user docs are the MkDocs site in `docs/` (<https://nvoxland.github.io/gittok/>); `README.md` is a short intro that links to it, with absolute links only (it is the PyPI page). Release notes are blog posts in `docs/blog/posts/`; there is no CHANGELOG to keep up.

## Architecture Overview

GitTok is a personal TikTok-style feed of cards about your own codebases.

- `src/gittok/` is a Python package. It analyzes git history into signals, builds a brief, validates card specs against git, stores cards in SQLite, and serves the feed API.
- **The session owns the server.** A user runs GitTok in a GitTok directory that `gittok init <dir>` makes; a clone works the same way and is its own GitTok directory. The `.mcp.json` of the directory makes Claude Code start `gittok mcp --ui`. That process talks MCP over stdio (the only MCP transport) and starts a child `gittok serve` (`--reload` in a clone only) that serves the feed API, the web build, and the render/learning workers on port 7313. LAN serving is on by default (`server.lan: true`; plain HTTP, pairing token, a device pairs only by code: `pair_device`; the feed server has no MCP endpoint); `server.lan: false` or `--no-lan` serves loopback only. The server answers only to its own Host names (`docs/social.md`, "LAN access"). In a clone the child reloads when a file in `src/gittok/` changes. It exits when the MCP process ends, even after a hard kill. If 7313 is already taken, it runs MCP only, and the MCP `instructions` tell the agent which GitTok directory has the port (from `/healthz`, loopback only). Changes to the MCP tools themselves need `/mcp` → gittok → Reconnect. `gittok serve` runs the feed server by hand, without a session. Nothing starts by itself and nothing is written outside the directory.
- **The user manages GitTok by asking Claude.** Repos (`add_repo`, `remove_repo`), phone access (`feed_address`, `pair_device`, `set_lan`) and steering (`add_rule`, ...) are MCP tools; the `gittok-steer` skill and the server's MCP `instructions` map plain requests to them. The CLI gives the same functions as an alternative. User-facing text says what to ask Claude first and gives the command second. Text that Claude reads (SessionStart hints, tool results and errors) tells Claude what to do or offer. Config-editing tools are only for a request the user made; writers, scouts and the generation and profiling skills never get them (`tests/test_pairing.py`). The one exception is `save_profile`: the profiling skill uses it for its own repo, also when the generation skill runs it first for a repo that has no profile.
- Card generation does **not** shell out to `claude -p` or start a model. An agent session (Claude Code or Codex) runs the `gittok-generate` skill. The skill calls `get_brief` and gives each packet id to a `gittok-writer` worker at the packet's tier (`light` or `standard`; `agent.models` in settings maps each tier to a model of each agent program, an empty entry means the session's model, and `get_brief` returns the resolved `model`). The writer calls `get_packet` (its leads and their evidence) and `get_guidance` (how to write its formats), reads the evidence, researches only what is missing, and submits its own cards with `submit_cards(packet_id)`. The driver never handles card JSON.
- **Keeping the feed full.** Two SessionStart hook lines do this. `gittok health --hint` prints one line when the feed wants cards now (unseen cards last under `agent.target_runway_days`): run `/gittok-generate`. `gittok feed-watch --hint` always prints one line: start the feed watch with Bash `run_in_background`, once per session (`uv run --quiet gittok feed-watch` in a clone, `gittok feed-watch` in a GitTok directory; `home.feed_watch_command` gives it, and the permission entry of the settings names the same command). The feed server appends one JSON line (a time and a count) to `data/feed-wants-cards.log` when the feed wants cards (`supply.signal_wants_cards`, on each pass of the notification worker). It writes no line while a run is open, when the daily run cap is reached, or within `agent.wake_cooldown_hours` of the last line. One exception to the cooldown: the feed is empty (the reader reached its end) and a run started after the last line. The watch exits on that line. When it exits, run `/gittok-generate` without asking, then start the watch again. The `get_brief` daily run cap still applies. The first cards of a new repo need no request either: after `add_repo` the agent profiles the repo and then runs `/gittok-generate`. `GET /api/feed` has `generating` (a run is open now); the end-of-feed card of the web app uses it.
- **The feed address.** A third SessionStart line, `gittok url --hint`, gives the addresses of the feed from `server.port` (phone/LAN when phone access is on; computer address only when phone access is off); give that address in the first reply. Text that an agent reads never names a port: it points to that line, to `gittok url`, or to `server.urls` of the `status` tool.
- **Repo profiles.** `local/profiles/<repo>.yaml` holds rules as data (regex or ast-grep patterns, roles, ignore globs) that GitTok runs and scores itself (`docs/learning.md`, "Candidate score and repo profiles"). The `gittok-profile-repo` skill (sonnet) writes and revises them with `survey_repo`, `test_detector`, `save_profile`, `rule_stats`. There is no profile step that the user must ask for. A repo with no profile is profiled at once, with one line to the user and no question: right after `add_repo` (`steering.next_step`), from the `gittok health --hint` line, and in step 0 of `gittok-generate` (`list_repos` gives `profiled` for each repo). A new profile for a repo that has one is only an offer, never automatic: `gittok health --hint` prints a line when its manifests changed, or when 3 or more of its rules have a factor under 0.8 (`profiling.reprofile_hint`, at most once per repo in 7 days).
- `web/` is a SvelteKit static app: vertical snap-scroll feed, horizontal depth panels.
- Card formats, visual kinds, and the `resolved` shapes the client renders are specified in `docs/formats.md`. Meme, illustration, and comic cards are stored `pending_render` and appear once images are attached. Memes use the bundled renderer. `render.image_backend` selects illustrations/comics: `auto` defaults to agent images in Codex (`GITTOK_AGENT=codex` in its MCP launch) and local mflux in Claude; `agent` and `local` override that default. Missing mflux always falls back to the agent. Cards persist the assignment in `resolved.image_backend`; the background worker skips agent cards. The driver uses `get_image_requests` and its native image tool, then `submit_images` (staged paths or image data URLs). Claude Code has no image tool: the driver gives each card to a `gittok-illustrator` subagent (`.claude/agents/`), which draws SVG and submits it as `svgs`; `agent_images.svg_image` rejects outside references (resvg would read local files) and rasterizes at the requested size with resvg. The backend-neutral `render_jobs.py` owns `RenderRequest`/`RenderCompletion`, prompt construction, validation, claiming, retries and asset storage; `render.py` and `agent_images.py` are adapters for local execution and agent transport. No model download starts for agent mode. Native tool failures leave cards pending and are reported; never silently substitute a paid API.
- Config: the shipped defaults live in `config/*.yaml` (reference: `docs/config.md`); the card contract is `src/gittok/schema/card.schema.json`; agent guidance is `src/gittok/prompts/generate.md`; runtime data goes in `data/` (gitignored).
- **Every shipped config file has a local override.** `overlay.py` merges `local/<file>` of the home over `config/<file>`: maps merge key by key, lists add, removal is explicit (`$remove`, `$replace`); an unknown key is a warning in `Config.warnings`, a broken file is a one-line `ConfigError`. Read a config file through `overlay` (`overlay.data(name)`, `overlay.derived(...)` for compiled values, or the `Config` fields), never from `shipped_root()` directly: the result is cached until a file changes. `load_config` names the home for readers that have no `Config` (`overlay.activate`). The shipped files hold defaults for any user: nothing about one repo, one project's macros, or one computer. No mascot is shipped (`local/mascots.yaml` only; the add flow makes one; mflux or agent images draw it).
- **Changing a default by asking.** There is no tool that writes any setting. On the user's request the agent edits the file in `local/` with its file tools, with three read-only tools around the edit: `config_files`, `get_config(file, key)`, `check_config` (CLI: `gittok config files|get|check`). The `gittok-steer` skill has the steps ("Change a default"). Writers, scouts, generation and profiling never edit `local/` by hand.
- **Two roots.** `config.resolve_roots()` gives (shared, home). Shared files (`config/`, `web/build`) come from `cfg.shared_path(...)`; the workflow sources are package data (`src/gittok/workflows/`); user files (`local/`, relative `data_dir`) come from `cfg.root`. The home is found by walking up from the current directory. A directory with the marker `gittok.yaml` (written by `gittok init`) is a GitTok directory: home is that directory, shared is the wheel's `gittok/_bundled/`. A directory with `config/settings.yaml` is a clone: both roots are the clone. `GITTOK_ROOT` names one of the two directly. With neither, every command but `init` fails with one line. `home.py` has `init` and `update`: `core_files` is for every agent program (`AGENTS.md`), and each entry of `HARNESSES` is the unit of one program (Claude Code and Codex); the templates are in `src/gittok/templates/`. Never use `parents[2]`; use `config.shipped_root()`. A wheel needs `web/build` first (`hatch_build.py` checks). See `docs/install.md`.

## Conventions & Patterns

- `gitq.py` is the only module that spawns git. Analysis is read-only and never writes to user repos. One exception: a repo with `fetch: true` in `local/repos.yaml` gets `fetch --no-tags` before analysis. It updates remote-tracking refs only (never the working tree, index or local branches), and only when the user turned it on. A repo added by URL (`gittok repos add <url>`, or `add_repo` with a URL) is a clone that GitTok makes and owns in `cfg.root / "repos" / <name>`; its entry has `remote: <url>` and `fetch: true`, and `gittok repos remove` deletes only such a clone. Removing a repo (`remove_repo`, `gittok repos remove`) also deletes all that GitTok made for it: cards with their rows and image files, repo-keyed rows, the profile, and a mascot of the repo that the user defined. The learned weights stay, and so do the rewards behind them, without the card link. `gc.delete_cards` is the one place that deletes a card and `gc.purge_repo` the one place that deletes a repo's data; a new table with a `repo`, `repo_id` or `card_id` column must be added there (`tests/test_remove_repo.py` checks it). Garbage collection also purges a repo that is no longer configured, and the feed never serves its cards.
- Time windows are relative to the analyzed ref's last commit date, not wall-clock.
- Tests build their own fixture git repo; unit tests never need network or a Claude session.

## Codex integration

- `.codex/config.toml` starts the same stdio MCP/server session as `.mcp.json`, through `uv run` in a clone.
- `.codex/hooks.json` has the same SessionStart hints as `.claude/settings.json`. Codex users trust the project configuration and review `/hooks`.
- **One neutral source for both agents.** The skills and workers live once in `src/gittok/workflows/`: `skills/<name>.md` and `workers/<name>.md` name no agent program (`tests/test_workflow_files.py`), and say "start a worker", "run a skill", "in a shell". `harness/claude.md` and `harness/codex.md` are the last section of every generated skill: how that program starts a worker, runs a skill or a shell command, connects or restarts the server, and makes images. `home.claude_code_files` and `home.codex_files` generate full copies: `.claude/skills/`, `.claude/agents/` (tools as `mcp__gittok__*`, model from the tier) and `.agents/skills/`, `.agents/workers/`. Never edit a generated copy. After editing a source, run `uv run python -m gittok.home` in the clone; the clone commits the copies and a test checks them. `.agents/GITTOK.md` holds only Codex session notes (connection, startup hints, the Codex feed watch).
- When using GitTok in Codex, read `.agents/GITTOK.md` for startup and feed watching. Generation delegates to Codex subagents; it never starts Claude. The opt-in `feed-watch --codex-thread THREAD` queues a fixed refill prompt with `codex queue --resume` for the local daemon. Plain `feed-watch` retains Claude's completion-based behavior; never invoke Codex for a Claude watch. Queue failures and resume warnings need a per-turn health fallback.
- `init` and `update` write the generated files and the templates (package data) for both programs.

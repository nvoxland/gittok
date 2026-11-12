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

When ending a work session: run the quality gates (`uv run pytest`, `uv run ruff check`, `npm --prefix web test`), **commit** all changes (push only when the user asks), and hand off a short summary.

## Build & Test

```bash
uv sync                          # install Python deps (Python 3.13)
uv run pytest                    # unit tests (live tests skipped unless GITTOK_LIVE=1)
uv run ruff check                # lint
npm --prefix web install
npm --prefix web test            # vitest component tests
npm --prefix web run build       # static build into web/build
uv run gittok mcp --ui       # what .mcp.json runs: stdio MCP, plus an auto-reloading feed on :8008 while the session lasts
uv run gittok serve          # the feed server by hand at http://127.0.0.1:8008 (no session, no MCP); --no-lan for loopback only
uv run gittok init <dir>     # make a GitTok directory (what a user of the installed tool does; see docs/install.md)
uv run gittok update <dir>   # rewrite the files that init owns, after an upgrade
uv sync --group images           # optional: mflux for mascot illustrations, comics, avatars
uv run gittok structure --prefetch   # download its grammars (once, needs network)
uv run gittok render         # one render pass (serve also renders in the background)
uv run gittok avatars        # generate persona avatar PNGs (needs the images group)
```

Red/green TDD is required: write the failing test first. `DEV.md` has the developer guide (setup, running from the clone, building the wheel, the release steps); `README.md` is for users of the installed tool.

## Architecture Overview

GitTok is a personal TikTok-style feed of cards about your own codebases.

- `src/gittok/` is a Python package. It analyzes git history into signals, builds a brief, validates card specs against git, stores cards in SQLite, and serves the feed API.
- **The session owns the server.** A user runs GitTok in a GitTok directory that `gittok init <dir>` makes; a clone works the same way and is its own GitTok directory. The `.mcp.json` of the directory makes Claude Code start `gittok mcp --ui`. That process talks MCP over stdio (the only MCP transport) and starts a child `gittok serve` (`--reload` in a clone only) that serves the feed API, the web build, and the render/learning workers on port 8008. LAN serving is on by default (`server.lan: true`; plain HTTP, pairing token, the `/pairing` QR page stays loopback-only; the feed server has no MCP endpoint); `server.lan: false` or `--no-lan` serves loopback only. The server answers only to its own Host names (`docs/social.md`, "LAN access"). In a clone the child reloads when a file in `src/gittok/` changes. It exits when the MCP process ends, even after a hard kill. If 8008 is already taken, it runs MCP only, and the MCP `instructions` tell the agent which GitTok directory has the port (from `/healthz`, loopback only). Changes to the MCP tools themselves need `/mcp` → gittok → Reconnect. `gittok serve` runs the feed server by hand, without a session. Nothing starts by itself and nothing is written outside the directory.
- **The user manages GitTok by asking Claude.** Repos (`add_repo`, `remove_repo`), phone access (`pairing_link`, `set_lan`) and steering (`add_rule`, ...) are MCP tools; the `gittok-steer` skill and the server's MCP `instructions` map plain requests to them. The CLI gives the same functions as an alternative. User-facing text says what to ask Claude first and gives the command second. Text that Claude reads (SessionStart hints, tool results and errors) tells Claude what to do or offer. Config-editing tools are only for a request the user made; writers, scouts and the generation and profiling skills never get them (`tests/test_pairing.py`). The one exception is `save_profile`: the profiling skill uses it for its own repo, also when the generation skill runs it first for a repo that has no profile.
- Card generation does **not** shell out to `claude -p`. A Claude Code session runs the `gittok-generate` skill (`.claude/skills/`). The skill calls `get_brief` and gives each packet id to a `gittok-writer` subagent (`.claude/agents/`) on haiku or sonnet. The writer calls `get_packet`, reads the evidence attached to its leads, researches only what is missing, and submits its own cards with `submit_cards(packet_id)`. The driver never handles card JSON.
- **Keeping the feed full.** Two SessionStart hook lines do this. `gittok health --hint` prints one line when the feed wants cards now (unseen cards last under `agent.target_runway_days`): run `/gittok-generate`. `gittok feed-watch --hint` always prints one line: start the feed watch with Bash `run_in_background`, once per session (`uv run --quiet gittok feed-watch` in a clone, `gittok feed-watch` in a GitTok directory; `home.feed_watch_command` gives it, and the permission entry of the settings names the same command). The feed server appends one JSON line (a time and a count) to `data/feed-wants-cards.log` when the feed wants cards (`supply.signal_wants_cards`, on each pass of the notification worker). It writes no line while a run is open, when the daily run cap is reached, or within `agent.wake_cooldown_hours` of the last line. One exception to the cooldown: the feed is empty (the reader reached its end) and a run started after the last line. The watch exits on that line. When it exits, run `/gittok-generate` without asking, then start the watch again. The `get_brief` daily run cap still applies. The first cards of a new repo need no request either: after `add_repo` the agent profiles the repo and then runs `/gittok-generate`. `GET /api/feed` has `generating` (a run is open now); the end-of-feed card of the web app uses it.
- **Repo profiles.** `local/profiles/<repo>.yaml` holds rules as data (regex or ast-grep patterns, roles, ignore globs) that GitTok runs and scores itself (`docs/learning.md`, "Candidate score and repo profiles"). The `gittok-profile-repo` skill (sonnet) writes and revises them with `survey_repo`, `test_detector`, `save_profile`, `rule_stats`. There is no profile step that the user must ask for. A repo with no profile is profiled at once, with one line to the user and no question: right after `add_repo` (`steering.next_step`), from the `gittok health --hint` line, and in step 0 of `gittok-generate` (`list_repos` gives `profiled` for each repo). A new profile for a repo that has one is only an offer, never automatic: `gittok health --hint` prints a line when its manifests changed, or when 3 or more of its rules have a factor under 0.8 (`profiling.reprofile_hint`, at most once per repo in 7 days).
- `web/` is a SvelteKit static app: vertical snap-scroll feed, horizontal depth panels.
- Card formats, visual kinds, and the `resolved` shapes the client renders are specified in `docs/formats.md`. Meme, illustration, and comic cards are stored `pending_render` and appear in the feed after the render worker draws them (memegen for memes, mflux for illustrations).
- Config lives in `config/*.yaml` (reference: `docs/config.md`); the card contract is `src/gittok/schema/card.schema.json`; agent guidance is `src/gittok/prompts/generate.md`; runtime data goes in `data/` (gitignored).
- **Two roots.** `config.resolve_roots()` gives (shared, home). Shared files (`config/`, `web/build`, `.claude/skills|agents`) come from `cfg.shared_path(...)`; user files (`local/`, relative `data_dir`) come from `cfg.root`. The home is found by walking up from the current directory. A directory with the marker `gittok.yaml` (written by `gittok init`) is a GitTok directory: home is that directory, shared is the wheel's `gittok/_bundled/`. A directory with `config/settings.yaml` is a clone: both roots are the clone. `GITTOK_ROOT` names one of the two directly. With neither, every command but `init` fails with one line. `home.py` has `init` and `update`: `core_files` is for every agent program (`AGENTS.md`), and each entry of `HARNESSES` is the unit of one program (now only Claude Code); the templates are in `src/gittok/templates/`. Never use `parents[2]`; use `config.shipped_root()`. A wheel needs `web/build` first (`hatch_build.py` checks). See `docs/install.md`.

## Conventions & Patterns

- `gitq.py` is the only module that spawns git. Analysis is read-only and never writes to user repos. One exception: a repo with `fetch: true` in `local/repos.yaml` gets `fetch --no-tags` before analysis. It updates remote-tracking refs only (never the working tree, index or local branches), and only when the user turned it on. A repo added by URL (`gittok repos add <url>`, or `add_repo` with a URL) is a clone that GitTok makes and owns in `cfg.root / "repos" / <name>`; its entry has `remote: <url>` and `fetch: true`, and `gittok repos remove` deletes only such a clone.
- Time windows are relative to the analyzed ref's last commit date, not wall-clock.
- Tests build their own fixture git repo; unit tests never need network or a Claude session.

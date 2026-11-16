# Keeping the feed full

Cards are written by an agent session: Claude Code or Codex. GitTok does not start a model by itself, and it does not run `claude -p`. So generation needs a session that is open. All other work (analysis, rendering, learning, notifications, garbage collection) is local Python and needs no session.

## What runs without an agent

| Job | How |
|---|---|
| The feed server: the feed, and the render, learning, profile, notification and garbage-collection workers | An agent session in the GitTok directory starts it (`.mcp.json` in Claude Code, `.codex/config.toml` in Codex) and it stops with the session. `gittok serve` starts it by hand. Nothing keeps it running when no session is open |
| Analysis of the repos | `gittok analyze` (cached by head commit). `get_brief` also runs it |
| Notifications | `gittok notify`. The server also runs this pass |

## Ways to generate

| Way | Notes |
|---|---|
| On demand: "make more cards", or `/gittok-generate` (`$gittok-generate` in Codex) | Always works. The run makes as many cards as the feed needs |
| After a repo is added | Your agent profiles the new repo and then runs `/gittok-generate` for the first cards. It does not ask first. The run ends at `nothing_to_do` when the feed has enough cards |
| The SessionStart hint | `gittok health --hint` prints one line at the start of a session when the unseen cards will not last `agent.target_runway_days`. The line says to run `/gittok-generate` |
| The feed watch | `gittok feed-watch` blocks until the server says the feed wants cards, then exits. A session that runs it in the background is woken at that moment and runs `/gittok-generate`, then starts the watch again. Codex uses its own variant ("Codex sessions" below) |
| Claude Code only: `/loop 4h /gittok-generate` in a session you leave open | Most ticks end at `nothing_to_do` and cost one MCP call |

`gittok init` writes the hooks to `.claude/settings.json` of the GitTok directory for Claude Code, and to `.codex/hooks.json` for Codex (`docs/install.md`, "Session hooks"). A clone has them in its own project files.

## Codex sessions

`gittok init` also writes `.codex/config.toml`, `.codex/hooks.json` and
`.agents/skills/`. Codex connects to the same stdio server and reads the same
workflow and worker instructions. Trust the project configuration and review the
hooks with `/hooks`. The startup instructions run the same hints if hooks did not.
Use `$gittok-generate` in place of `/gittok-generate`; generation uses Codex
subagents on the models of `agent.models.codex` (none: your session's model).

The Codex runtime adapter starts `gittok feed-watch --codex-thread "$CODEX_THREAD_ID"`
in the background (with `uv run --quiet` in a source clone). When the feed asks
for cards, the watch queues a fixed refill prompt with `codex queue --thread <id>
--message <prompt> --resume`, then exits. The local Codex daemon is asked to resume
the existing thread, so shell completion notifications are not needed to request
an idle refill. Private delivery receipts under `data/codex-wake/` remember the
last signal queued to each thread, including across watch restarts. A per-thread
file lock covers the fresh receipt check, queue call and receipt write, so
overlapping watches cannot queue the same signal twice. The agent generates cards and starts the same watch again.

This requires a local Codex CLI with `queue --resume`, a nonempty thread id, and
a reachable daemon. A successful queue can still print a resume warning; the
agent preserves that warning rather than claiming it woke. A failed queue leaves
the feed request pending. Clients without this capability use the plain watch
and check health on the next user turn; automatic idle refill is unavailable there.
The Claude Code watch is unchanged and does not invoke Codex. The limits below still apply
to both clients.

## How the feed watch works

- The server appends one line to `<data_dir>/feed-wants-cards.log` when the feed wants cards. The line is one JSON object that holds a time and a count only, such as `{"at":"2026-06-01T12:00:00+00:00","want":12}`. `gittok feed-watch` reads whole lines of this shape and ignores any other text.
- The notification worker of the feed server makes this check once a minute. A feed request does not make it.
- The feed wants cards when the unseen cards will not last `agent.target_runway_days` at the reading speed of the last 7 days.
- It does not write a line when there are no repos, while a run that started in the last `agent.wake_cooldown_hours` is still open, when `agent.per_day_runs` runs started in the last 24 hours (a new run could not start), or within `agent.wake_cooldown_hours` of the last line.
- The end of the feed is the exception to the last rule. When no unseen card is left and a run started after the last line, the server writes a new line at once. So a reader who reads every card does not wait for the cooldown. When no run answered the last line, a second line would say nothing new, and the server writes none.
- `gittok feed-watch` checks the file every `--poll` seconds. It exits when a new line arrives. It also exits at once if the last line is newer than the newest run, because no run answered that line.
- `gittok feed-watch --hint` prints the line that tells the session to start the watch. `--codex-thread THREAD` adds one queue-and-resume attempt for that Codex thread when a signal arrives. The prompt contains only a parsed count and fixed instructions, never raw log text or repo contents.

## When cards are made without a request

All of these must be true:

1. An agent session is open in the GitTok directory, and it started the feed watch. The SessionStart hook tells it to. In Claude Code, a turn starts for the session when the watch exits, also when the session is idle. If the session is in the middle of other work, the run starts after that work. In Codex, the watch queues a refill prompt for the thread ("Codex sessions" above); without that, Codex checks the feed on your next message.
2. The feed server runs (the session starts it) and at least one repo is configured.
3. The feed wants cards: the unseen cards last under `agent.target_runway_days` (3).
4. No run is open, and fewer than `agent.per_day_runs` (10) runs started in the last 24 hours.
5. The last signal is older than `agent.wake_cooldown_hours` (4), or the feed is empty and a run answered the last signal.

With no session open, nothing makes cards. The server still writes the line, and the next session that starts the watch answers it at once.

The web app says this at the end of the feed. `GET /api/feed` has `generating`, which is true while a run is open; the end-of-feed card then says that new cards are being made now. Otherwise it says that more cards come by themselves while a session is open, and that the reader can ask for more at once.

## Limits

The server enforces the limits, whatever starts the run: `agent.max_count` cards per run and `agent.per_day_runs` runs per day (`docs/config.md`). The worker models come from `agent.models`: in Claude Code Haiku and Sonnet by default, in Codex the session's model unless you name others.

A cloud agent cannot generate cards: it cannot reach `127.0.0.1` on your Mac, and it cannot read your local repos.

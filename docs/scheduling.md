# Keeping the feed full

Cards are written by a Claude Code session. GitTok does not start a model by itself, and it does not run `claude -p`. So generation needs a session that is open. All other work (analysis, rendering, learning, notifications, garbage collection) is local Python and needs no session.

## What runs without Claude

| Job | How |
|---|---|
| The server: feed, MCP, and the render, learning, profile, notification and garbage-collection workers | `gittok serve`. `gittok install --launchd --apply` adds a LaunchAgent that keeps it running. In a clone, a Claude Code session starts it instead (the project `.mcp.json`) |
| Analysis of the repos | `gittok analyze` (cached by head commit). `get_brief` also runs it |
| Notifications | `gittok notify`. The server also runs this pass |

## Ways to generate

| Way | Notes |
|---|---|
| On demand: `/gittok-generate` | Always works. The run makes as many cards as the feed needs |
| The SessionStart hint | `gittok health --hint` prints one line at the start of a session when the unseen cards will not last `agent.target_runway_days`. The line says to run `/gittok-generate` |
| The feed watch | `gittok feed-watch` blocks until the server says the feed wants cards, then exits. A session that runs it in the background is woken at that moment and runs `/gittok-generate`, then starts the watch again |
| `/loop 4h /gittok-generate` in a session you leave open | Most ticks end at `nothing_to_do` and cost one MCP call |

In a clone, the project `.claude/settings.json` has both hooks. For an installed tool, add them yourself: see `docs/install.md`, "Session hooks".

## How the feed watch works

- The server appends one line to `<data_dir>/feed-wants-cards.log` when the feed wants cards. The line is one JSON object that holds a time and a count only, such as `{"at":"2026-06-01T12:00:00+00:00","want":12}`. `gittok feed-watch` reads whole lines of this shape and ignores any other text.
- It does not write a line when there are no repos, while a run that started in the last `agent.wake_cooldown_hours` is still open, or within `agent.wake_cooldown_hours` of the last line.
- `gittok feed-watch` checks the file every `--poll` seconds. It exits when a new line arrives. It also exits at once if the last line is newer than the newest run, because no run answered that line.
- `gittok feed-watch --hint` prints the line that tells the session to start the watch.

## Limits

The server enforces the limits, whatever starts the run: `agent.max_count` cards per run and `agent.per_day_runs` runs per day (`docs/config.md`). The skill pins its own model (sonnet for the driver, haiku or sonnet for each packet).

A cloud agent cannot generate cards: it cannot reach `127.0.0.1` on your Mac, and it cannot read your local repos.

# Scheduling generation (M5 investigation)

Generation needs an interactive Claude Code session, because headless `claude -p` is not allowed on a subscription. Everything else (analysis, rendering, learning, notifications, the profile) is plain local Python and can run on any schedule.

## What can run without Claude

| Job | How | Schedule |
|---|---|---|
| Keep the server up (feed, MCP, render/learning/profile/notification workers) | launchd LaunchAgent running `gittok serve` with `KeepAlive` | always |
| Re-analyze repos | `gittok analyze` (cached by HEAD, so cheap) | hourly, or a git post-commit hook |
| Notifications | `gittok notify` (also runs inside `serve`) | with `serve` |

A LaunchAgent for `serve` also fixes the main friction of the MCP design: the `.mcp.json` URL only works while the server is running.

## Options for generation itself

| Option | Works with local MCP? | Cost control | Verdict |
|---|---|---|---|
| `/loop 6h /gittok-generate` in a dedicated, long-lived Claude Code session | Yes (same machine) | Skill pins Sonnet; packets on haiku/sonnet; server caps runs per day (`agent.per_day_runs`) | **Recommended** for now. Needs a terminal tab left open. |
| Claude Code routines (`/schedule`, cloud agents) | No: a cloud agent cannot reach `127.0.0.1:8008` and cannot read the local repos. Would need a tunnel (Tailscale, deferred to M6) plus repos on the remote side | Same | Not viable until M6 networking. |
| Claude desktop app scheduled tasks | Possibly, if they run locally with project MCP servers. Not verified | Same | Worth checking by hand. |
| launchd + `claude -p` | n/a | n/a | Not allowed on a subscription. |
| On demand (`/gittok-generate` when you want fresh cards) | Yes | Best | Always available. |

## Recommendation

1. Install a LaunchAgent for `gittok serve` (`gittok install --launchd`, see the install command) so the feed and MCP server are always up.
2. Generate on demand, plus optionally a dedicated tab running `/loop 6h /gittok-generate`. The daily run cap protects the subscription.
3. Revisit cloud routines when Tailscale lands (M6).

The final choice is the user's.

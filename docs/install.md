# Installing CodeScroll for daily use

`codescroll install` sets up three things on your machine. It has three parts.

| Part | Flag | What it does |
|---|---|---|
| MCP | `--mcp` | Runs `claude mcp add --scope user --transport http codescroll http://<host>:<port>/mcp`. Claude Code then sees the server from any directory. Skipped if `claude mcp get codescroll` already shows the same URL. |
| Skills | `--skills` | Copies `codescroll-generate` and `codescroll-steer` from `.claude/skills/` to `~/.claude/skills/`. |
| LaunchAgent | `--launchd` | Writes `~/Library/LaunchAgents/dev.codescroll.serve.plist` and loads it. `codescroll serve` then starts at login and restarts if it stops. Logs go to `<data_dir>/logs/serve.log`. |

With no part flag, all three run. Host and port come from `config/settings.yaml` (`server.host`, `server.port`).

## Dry run is the default

```bash
uv run codescroll install            # prints what it would do, changes nothing
uv run codescroll install --apply    # does it
uv run codescroll install --skills --apply
```

The dry run only runs read-only checks (`claude mcp get`). It ends with a checklist of changes and the undo steps.

Rules for safe changes:

- If a skill file in `~/.claude/skills/` exists and differs from the repo, it is skipped. The output shows a short diff. Use `--force` to overwrite.
- If `claude` is not on PATH, the MCP command is printed for you to run.
- If `launchctl` is not on PATH, the plist is written and the `launchctl bootstrap` command is printed.
- The LaunchAgent PATH holds the directories of `uv`, `git`, and `claude` as found at install time. Run `install --launchd --apply` again if you move them.

## Undo

| Part | Undo |
|---|---|
| MCP | `claude mcp remove codescroll --scope user` |
| Skills | `rm -r ~/.claude/skills/codescroll-generate ~/.claude/skills/codescroll-steer` |
| LaunchAgent | `uv run codescroll install --uninstall --launchd --apply` (runs `launchctl bootout gui/<uid> <plist>` and removes the plist) |

## Using Codex

The MCP server also works with Codex. Add this to `~/.codex/config.toml`:

```toml
[mcp_servers.codescroll]
url = "http://127.0.0.1:8008/mcp"
```

This is a streamable-HTTP MCP server. Use the host and port from your settings. Keep `codescroll serve` running (the LaunchAgent does this).

Notes:

- The `codescroll-generate` skill pins models (Sonnet for the driver, Haiku or Sonnet for packets). This is Claude-specific. Codex users should run each work packet by hand on a small model.
- Comparing Codex card quality with Claude card quality is tracked in beads. It spends ChatGPT quota, so the user runs it.

## LAN notes

`codescroll serve --lan` binds all interfaces. The feed and `/api/*` need a pairing cookie from non-loopback peers: open the `pair:` URL printed at start-up once on each device. The token lives in `<data_dir>/lan_token` (mode 0600). `/mcp` is loopback-only and refuses LAN peers. PWA install and offline mode need HTTPS, because service workers do not register on plain-HTTP LAN origins. See `docs/social.md`.

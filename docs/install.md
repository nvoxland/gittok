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

## Meme renderer (memegen)

Meme cards are drawn by a local [memegen](https://github.com/jacebrowning/memegen) server at `settings.render.memegen_url` (default `http://127.0.0.1:5001`). There is no public image, so build it from source. The build file is `Containerfile`, and the app listens on 5000 inside the container.

```bash
git clone --depth 1 https://github.com/jacebrowning/memegen.git ~/src/other/memegen
cd ~/src/other/memegen && docker build -f Containerfile -t memegen .
docker run -d --name memegen --restart unless-stopped -p 127.0.0.1:5001:5000 memegen
curl -s http://127.0.0.1:5001/templates/ | head -c 200   # JSON means it works
```

Restart `codescroll serve` afterwards. Until memegen answers, the brief skips the `meme` format and meme cards stay `pending_render`.

## Illustration renderer (mflux)

Illustration and comic cards, and the persona avatars, are drawn by [mflux](https://github.com/filipstrand/mflux) on Apple Silicon. Install it into the project venv:

```bash
uv sync --group images
```

**Save a quantized copy of the model first.** The default model, `z-image-turbo`, is 25 GB of bf16 weights. Without a saved copy, every render reads all 25 GB and quantizes it in memory, which swaps a 36 GB Mac and times out after 300 s. Save it once (this downloads the weights on the first run; close memory-hungry apps while it runs):

```bash
uv run mflux-save --model z-image-turbo --quantize 4 --path ~/.cache/mflux/z-image-turbo-q4
```

Then point the renderer at the folder in `config/settings.yaml`:

```yaml
render:
  mflux_path: ~/.cache/mflux/z-image-turbo-q4   # what mflux-save wrote
  mflux_model: z-image-turbo                    # the family it is based on
```

With `mflux_path` set, a render loads about 7 GB (q4) or 14 GB (q8) and takes 10 to 20 s per image at 8 steps. Use `--quantize 6` or `8` if the flat-vector mascots look rough at 4. Restart `codescroll serve` (or `/mcp` → codescroll → Reconnect) after installing, then check with:

```bash
uv run codescroll avatars      # draws the persona avatars; the first image also warms the Metal cache
```

Until mflux is importable, the brief skips `mascot_scene` and `comic` and those cards stay `pending_render`.

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

`codescroll serve --lan` and `codescroll mcp --ui --lan` (what the project `.mcp.json` runs) bind all interfaces. The feed and `/api/*` need a pairing cookie from non-loopback peers: open the `pair:` URL printed at start-up once on each device. The token lives in `<data_dir>/lan_token` (mode 0600). `/mcp` is loopback-only and refuses LAN peers. PWA install and offline mode need HTTPS, because service workers do not register on plain-HTTP LAN origins. See `docs/social.md`.

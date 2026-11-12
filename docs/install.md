# Installing Blamescroll for daily use

## Install without a clone

You do not need a clone to use Blamescroll. You need `uv` and `git`.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh        # if you do not have uv yet
uv tool install ./blamescroll-0.1.0-py3-none-any.whl   # from a wheel file
uv tool install blamescroll                            # or from PyPI, when it is published
```

To build the wheel in a clone: `npm --prefix web run build`, then `uv build --wheel` (the file goes to `dist/`). A git URL install does not work yet, because the web build is not committed.

Optional extras:

```bash
uv tool install 'blamescroll[structure,profiles]'      # from PyPI: tree-sitter layer, ast-grep rules
uv tool install 'blamescroll[structure,profiles] @ ./blamescroll-0.1.0-py3-none-any.whl'   # from a wheel
uv tool install 'blamescroll[images]'                  # mflux art (Apple silicon only)
```

The package carries its own shared files: `config/`, the web app, and the skills and agents. You edit none of them. Your own files live in one home folder:

- `~/.blamescroll/local/`: `repos.yaml`, `profiles/`, and the `settings.yaml`, `personas.yaml`, `mascots.yaml` overlays.
- `~/.blamescroll/data/`: the database, card images, and logs.

Set `BLAMESCROLL_HOME` to use another folder. Blamescroll makes it on first use.

Then set up Claude Code and the background server:

```bash
blamescroll install            # dry run: shows what it would do
blamescroll install --apply    # MCP at http://127.0.0.1:8008/mcp, skills, LaunchAgent (macOS)
```

The LaunchAgent runs `blamescroll serve` from your home folder. To run it by hand, use `blamescroll serve`. The feed is at `http://127.0.0.1:8008`.

Add a repo in one of two ways:

- Ask Claude to call the `add_repo` MCP tool.
- Write `~/.blamescroll/local/repos.yaml` yourself:

```yaml
repos:
  myapp:
    path: ~/src/myapp
```

Upgrade with `uv tool upgrade blamescroll`, then run `blamescroll install --apply --force` to refresh the skills. Uninstall with `blamescroll install --uninstall --launchd --apply`, then `uv tool uninstall blamescroll`. Your `~/.blamescroll` folder stays until you delete it.

The project `.mcp.json` flow (a Claude session owns the server) works only in a clone. A clone keeps working as before: it uses its own `config/`, `local/` and `data/`. `BLAMESCROLL_ROOT` points to a clone from any directory.

How Blamescroll picks its folders:

1. `BLAMESCROLL_ROOT`, if set: that clone holds everything.
2. A clone found by walking up from the current directory (a `config/settings.yaml`).
3. Otherwise the installed app: shared files from the package, your files from `BLAMESCROLL_HOME`.

To build a wheel yourself: `npm --prefix web install && npm --prefix web run build && uv build`. The build fails if `web/build` is missing.

## What `blamescroll install` does

`blamescroll install` sets up three things on your machine. It has three parts.

| Part | Flag | What it does |
|---|---|---|
| MCP | `--mcp` | Runs `claude mcp add --scope user --transport http blamescroll http://<host>:<port>/mcp`. Claude Code then sees the server from any directory. Skipped if `claude mcp get blamescroll` already shows the same URL. |
| Skills | `--skills` | Copies `blamescroll-generate`, `blamescroll-steer` and `blamescroll-profile-repo` (and the writer and scout agents) from `.claude/` in a clone, or from the package when installed, to `~/.claude/skills/`. |
| LaunchAgent | `--launchd` | Writes `~/Library/LaunchAgents/dev.blamescroll.serve.plist` and loads it. `blamescroll serve` then starts at login and restarts if it stops. Logs go to `<data_dir>/logs/serve.log`. |

With no part flag, all three run. Host and port come from `config/settings.yaml` (`server.host`, `server.port`).

## Local config

Settings that belong to one machine live in `local/`. This directory is in `.gitignore` and is never committed. `config/` keeps only shared product data. All parts are optional; a missing `local/` means no repos.

- `local/repos.yaml`: the repos and groups to analyze.
- `local/profiles/<repo>.yaml`: the profile of each repo.
- `local/settings.yaml`: merged over `config/settings.yaml`, key by key inside each section.
- `local/personas.yaml` and `local/mascots.yaml`: merged over the shared files, per name and field by field. The edit tools write only here.
- `local/.edit.lock`: the lock file of the edit tools.

## Dry run is the default

```bash
uv run blamescroll install            # prints what it would do, changes nothing
uv run blamescroll install --apply    # does it
uv run blamescroll install --skills --apply
```

The dry run only runs read-only checks (`claude mcp get`). It ends with a checklist of changes and the undo steps.

Rules for safe changes:

- If a skill file in `~/.claude/skills/` exists and differs from the shipped copy, it is skipped. The output shows a short diff. Use `--force` to overwrite.
- If `claude` is not on PATH, the MCP command is printed for you to run.
- If `launchctl` is not on PATH, the plist is written and the `launchctl bootstrap` command is printed.
- The LaunchAgent PATH holds the directories of `uv`, `git`, and `claude` as found at install time. Run `install --launchd --apply` again if you move them.

## Undo

| Part | Undo |
|---|---|
| MCP | `claude mcp remove blamescroll --scope user` |
| Skills | `rm -r ~/.claude/skills/blamescroll-generate ~/.claude/skills/blamescroll-steer` |
| LaunchAgent | `uv run blamescroll install --uninstall --launchd --apply` (runs `launchctl bootout gui/<uid> <plist>` and removes the plist) |

## Structure layer (optional, tree-sitter)

Blamescroll reads code structure (definitions, imports, comments) with tree-sitter when the optional group is installed. Without it everything works on the regex patterns in `config/languages.yaml` and, for other file types, on plain text rules.

```bash
uv sync --group structure          # tree-sitter-language-pack 1.22.x, about 2 MB
uv run blamescroll structure        # status: installed, grammars needed, grammars missing (JSON)
uv run blamescroll structure --prefetch   # download the grammars for the repos in local/repos.yaml
```

The package holds no grammars. They are a bundle of about 26 MB (12 languages) that the pack downloads from GitHub on first use into `~/Library/Caches/tree-sitter-language-pack/` (Linux: `~/.cache/`). `--prefetch` does this once, on purpose, so a mining run never waits on the network. A grammar that is not in the cache is not used; `blamescroll health --hint` (the SessionStart hook) prints one line naming the missing grammars. Offline, run `--prefetch` on a machine with network and copy the cache dir. Shipped queries: python, typescript/tsx/javascript/svelte, clojure, go, ruby, java, rust. Another stack: let the profile skill write a `queries` entry (docs/learning.md, "The structure layer").

## Meme renderer (memegen)

Meme cards are drawn by a local [memegen](https://github.com/jacebrowning/memegen) server at `settings.render.memegen_url` (default `http://127.0.0.1:5001`). There is no public image, so build it from source. The build file is `Containerfile`, and the app listens on 5000 inside the container.

```bash
git clone --depth 1 https://github.com/jacebrowning/memegen.git ~/src/other/memegen
cd ~/src/other/memegen && docker build -f Containerfile -t memegen .
docker run -d --name memegen --restart unless-stopped -p 127.0.0.1:5001:5000 memegen
curl -s http://127.0.0.1:5001/templates/ | head -c 200   # JSON means it works
```

Restart `blamescroll serve` afterwards. Until memegen answers, the brief skips the `meme` format and meme cards stay `pending_render`.

## Illustration renderer (mflux)

Illustration and comic cards, and the persona avatars, are drawn by [mflux](https://github.com/filipstrand/mflux) on Apple Silicon. Install it into the project venv:

```bash
uv sync --group images
```

**Save a quantized copy of the model first.** The default model, `z-image-turbo`, is 25 GB of bf16 weights. Without a saved copy, every render reads all 25 GB and quantizes it in memory, which swaps a 36 GB Mac and times out after 300 s. Save it once (this downloads the weights on the first run; close memory-hungry apps while it runs):

```bash
uv run mflux-save --model z-image-turbo --quantize 4 --path ~/.cache/mflux/z-image-turbo-q4
```

Then point the renderer at the folder in `config/settings.yaml` (or `local/settings.yaml`):

```yaml
render:
  mflux_path: ~/.cache/mflux/z-image-turbo-q4   # what mflux-save wrote
  mflux_model: z-image-turbo                    # the family it is based on
```

With `mflux_path` set, a render loads about 7 GB (q4) or 14 GB (q8) and takes 10 to 20 s per image at 8 steps. Use `--quantize 6` or `8` if the flat-vector mascots look rough at 4. Restart `blamescroll serve` (or `/mcp` → blamescroll → Reconnect) after installing, then check with:

```bash
uv run blamescroll avatars      # draws the persona avatars; the first image also warms the Metal cache
```

Until mflux is importable, the brief skips `mascot_scene` and `comic` and those cards stay `pending_render`.

## Using Codex

The MCP server also works with Codex. Add this to `~/.codex/config.toml`:

```toml
[mcp_servers.blamescroll]
url = "http://127.0.0.1:8008/mcp"
```

This is a streamable-HTTP MCP server. Use the host and port from your settings. Keep `blamescroll serve` running (the LaunchAgent does this).

Notes:

- The `blamescroll-generate` skill pins models (Sonnet for the driver, Haiku or Sonnet for packets). This is Claude-specific. Codex users should run each work packet by hand on a small model.
- Comparing Codex card quality with Claude card quality is tracked in beads. It spends ChatGPT quota, so the user runs it.

## Keeping "today" fresh (optional fetch)

Analysis reads your local clone, so "recent" means the last time you pulled. For a repo other people push to, set `fetch: true`. Blamescroll then fetches the branch of the configured ref before it reads the repo (`fetch --no-tags --quiet <remote> <branch>`):

```yaml
repos:
  myapp:
    path: ~/src/myapp
    ref: origin/master   # must be a remote-tracking ref; remote and branch come from it
    fetch: true          # default false
```

Fetch updates remote-tracking refs only. It never changes the working tree, the index or local branches. It runs with prompts off and a 60 s timeout. If it fails, Blamescroll logs it and uses the old ref. A ref that is not remote-tracking (for example `HEAD`) skips the fetch. At most one fetch per repo runs in each `analysis.fetch_min_interval_s` (default 900) seconds.

## LAN notes

`blamescroll serve --lan` and `blamescroll mcp --ui --lan` (what the project `.mcp.json` runs) bind all interfaces. The feed and `/api/*` need a pairing cookie from non-loopback peers: open the `pair:` URL printed at start-up once on each device. The token lives in `<data_dir>/lan_token` (mode 0600). `/mcp` is loopback-only and refuses LAN peers. PWA install and offline mode need HTTPS, because service workers do not register on plain-HTTP LAN origins. See `docs/social.md`.

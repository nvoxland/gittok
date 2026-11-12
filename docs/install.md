# Installing GitTok for daily use

## Install without a clone

You do not need a clone to use GitTok. You need `uv` and `git`.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh        # if you do not have uv yet
uv tool install ./gittok-0.1.0-py3-none-any.whl   # from a wheel file
uv tool install gittok                            # or from PyPI, when it is published
```

To build the wheel in a clone: `npm --prefix web run build`, then `uv build --wheel` (the file goes to `dist/`). A git URL install does not work yet, because the web build is not committed.

The tree-sitter structure layer and ast-grep rules come with every install. One extra is optional, because it is large (torch and mlx, about 1 GB, plus the models it downloads later):

```bash
uv tool install 'gittok[images] @ ./gittok-0.1.0-py3-none-any.whl'   # mflux art (Apple silicon only)
```

The package carries its own shared files: `config/`, the web app, and the skills and agents. You edit none of them. Your own files live in one home folder:

- `~/.gittok/local/`: `repos.yaml`, `profiles/`, and the `settings.yaml`, `personas.yaml`, `mascots.yaml` overlays.
- `~/.gittok/data/`: the database, card images, and logs.

Set `GITTOK_HOME` to use another folder. GitTok makes it on first use.

Then set up Claude Code and the background server:

```bash
gittok install            # dry run: shows what it would do
gittok install --apply    # MCP at http://127.0.0.1:8008/mcp, skills, LaunchAgent (macOS)
```

The LaunchAgent runs `gittok serve` from your home folder. To run it by hand, use `gittok serve`. The feed is at `http://127.0.0.1:8008`.

Add a repo in one of these ways:

- Run `gittok repos add <name> <path-or-url>` in a terminal.
  - A local path must be the root of a git repo that has a commit. GitTok reads it and never changes it.
  - A remote URL (`https://`, `ssh://`, `git://` or `git@host:org/repo.git`) is cloned into the GitTok home folder, at `repos/<name>` (installed: `~/.gittok/repos/<name>`). For a URL the name is optional: `gittok repos add https://example.com/acme/harbor.git` uses `harbor`. GitTok fetches this clone before each analysis.
  - A URL must not hold a password or token. For a private repo, use an ssh URL or a git credential helper. The clone does not ask for a password; it fails.
- Ask Claude to call the `add_repo` MCP tool. For a local path, the tool only accepts a repo inside `repos.allowed_roots` (`local/settings.yaml`), or next to a local repo you already added. It accepts a remote URL in all cases.
- Write `~/.gittok/local/repos.yaml` yourself:

```yaml
repos:
  myapp:
    path: ~/src/myapp
```

`gittok repos` lists the repos. `gittok repos remove <name>` removes one. It deletes the clone only when GitTok made it (a repo added by URL); it never touches a directory you gave. Cards already made from the repo stay.

Upgrade with `uv tool upgrade gittok`, then run `gittok install --apply --force` to refresh the skills. Uninstall with `gittok install --uninstall --launchd --apply`, then `uv tool uninstall gittok`. Your `~/.gittok` folder stays until you delete it.

The project `.mcp.json` flow (a Claude session owns the server) works only in a clone. A clone keeps working as before: it uses its own `config/`, `local/` and `data/`. `GITTOK_ROOT` points to a clone from any directory.

How GitTok picks its folders:

1. `GITTOK_ROOT`, if set: that clone holds everything.
2. A clone found by walking up from the current directory (a `config/settings.yaml`).
3. Otherwise the installed app: shared files from the package, your files from `GITTOK_HOME`.

To build a wheel yourself: `npm --prefix web install && npm --prefix web run build && uv build`. The build fails if `web/build` is missing.

## What `gittok install` does

`gittok install` sets up three things on your machine. It has three parts.

| Part | Flag | What it does |
|---|---|---|
| MCP | `--mcp` | Runs `claude mcp add --scope user --transport http gittok http://<host>:<port>/mcp`. Claude Code then sees the server from any directory. Skipped if `claude mcp get gittok` already shows the same URL. |
| Skills | `--skills` | Copies `gittok-generate`, `gittok-steer` and `gittok-profile-repo` (and the writer and scout agents) from `.claude/` in a clone, or from the package when installed, to `~/.claude/skills/`. |
| LaunchAgent | `--launchd` | Writes `~/Library/LaunchAgents/dev.gittok.serve.plist` and loads it. `gittok serve` then starts at login and restarts if it stops. Logs go to `<data_dir>/logs/serve.log`. |

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
uv run gittok install            # prints what it would do, changes nothing
uv run gittok install --apply    # does it
uv run gittok install --skills --apply
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
| MCP | `claude mcp remove gittok --scope user` |
| Skills | `rm -r ~/.claude/skills/gittok-generate ~/.claude/skills/gittok-steer` |
| LaunchAgent | `uv run gittok install --uninstall --launchd --apply` (runs `launchctl bootout gui/<uid> <plist>` and removes the plist) |

## Structure layer (tree-sitter)

GitTok reads code structure (definitions, imports, comments) with tree-sitter. It is a normal dependency. A language whose grammar is not downloaded yet works on the regex patterns in `config/languages.yaml` and, for other file types, on plain text rules.

```bash
uv run gittok structure        # status: installed, grammars needed, grammars missing (JSON)
uv run gittok structure --prefetch   # download the grammars for the repos in local/repos.yaml
```

The package holds no grammars. They are a bundle of about 26 MB (12 languages) that the pack downloads from GitHub on first use into `~/Library/Caches/tree-sitter-language-pack/` (Linux: `~/.cache/`). `--prefetch` does this once, on purpose, so a mining run never waits on the network. A grammar that is not in the cache is not used; `gittok health --hint` (the SessionStart hook) prints one line naming the missing grammars. Offline, run `--prefetch` on a machine with network and copy the cache dir. Shipped queries: python, typescript/tsx/javascript/svelte, clojure, go, ruby, java, rust. Another stack: let the profile skill write a `queries` entry (docs/learning.md, "The structure layer").

## Meme renderer (memegen)

Meme cards are drawn by a local [memegen](https://github.com/jacebrowning/memegen) server at `settings.render.memegen_url` (default `http://127.0.0.1:5001`). There is no public image, so build it from source. The build file is `Containerfile`, and the app listens on 5000 inside the container.

```bash
git clone --depth 1 https://github.com/jacebrowning/memegen.git ~/src/other/memegen
cd ~/src/other/memegen && docker build -f Containerfile -t memegen .
docker run -d --name memegen --restart unless-stopped -p 127.0.0.1:5001:5000 memegen
curl -s http://127.0.0.1:5001/templates/ | head -c 200   # JSON means it works
```

Restart `gittok serve` afterwards. Until memegen answers, the brief skips the `meme` format and meme cards stay `pending_render`.

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

With `mflux_path` set, a render loads about 7 GB (q4) or 14 GB (q8) and takes 10 to 20 s per image at 8 steps. Use `--quantize 6` or `8` if the flat-vector mascots look rough at 4. Restart `gittok serve` (or `/mcp` → gittok → Reconnect) after installing, then check with:

```bash
uv run gittok avatars      # draws the persona avatars; the first image also warms the Metal cache
```

Until mflux is importable, the brief skips `mascot_scene` and `comic` and those cards stay `pending_render`.

## Using Codex

The MCP server also works with Codex. Add this to `~/.codex/config.toml`:

```toml
[mcp_servers.gittok]
url = "http://127.0.0.1:8008/mcp"
```

This is a streamable-HTTP MCP server. Use the host and port from your settings. Keep `gittok serve` running (the LaunchAgent does this).

Notes:

- The `gittok-generate` skill pins models (Sonnet for the driver, Haiku or Sonnet for packets). This is Claude-specific. Codex users should run each work packet by hand on a small model.
- Comparing Codex card quality with Claude card quality is still open. It spends ChatGPT quota, so the user runs it.

## Keeping "today" fresh (optional fetch)

Analysis reads your local clone, so "recent" means the last time you pulled. For a repo other people push to, set `fetch: true`. GitTok then fetches the branch of the configured ref before it reads the repo (`fetch --no-tags --quiet <remote> <branch>`):

```yaml
repos:
  myapp:
    path: ~/src/myapp
    ref: origin/master   # must be a remote-tracking ref; remote and branch come from it
    fetch: true          # default false
```

Fetch updates remote-tracking refs only. It never changes the working tree, the index or local branches. It runs with prompts off and a 60 s timeout. If it fails, GitTok logs it and uses the old ref. A ref that is not remote-tracking (for example `HEAD`) skips the fetch. At most one fetch per repo runs in each `analysis.fetch_min_interval_s` (default 900) seconds.

## LAN notes

LAN serving is off by default: the project `.mcp.json` runs `gittok mcp --ui`, which serves loopback only. To turn it on, pass `--lan` to `gittok serve` or `gittok mcp --ui`, or set `server.lan: true` in `local/settings.yaml` (the LaunchAgent's `gittok serve` and the `.mcp.json` session then serve the LAN without a flag). With LAN serving on, the server binds all interfaces. A bind to any other non-loopback `--host` is token-protected in the same way. The feed and `/api/*` need a pairing cookie from non-loopback peers: open the `pair:` URL printed at start-up once on each device. The token lives in `<data_dir>/lan_token` (mode 0600). `/mcp` is loopback-only and refuses LAN peers. PWA install and offline mode need HTTPS, because service workers do not register on plain-HTTP LAN origins. See `docs/social.md`.

## HTTPS on a LAN (optional, for PWA install)

You do not need this to use the feed. Plain HTTP on the LAN works in a browser tab. HTTPS is needed only for "Add to Home Screen" as an installed app with offline mode, because browsers register a service worker only on HTTPS or `localhost`.

**The project does not test these recipes.** GitTok itself serves plain HTTP only. The recipes use a second program on the same computer that holds the certificate and forwards to `http://127.0.0.1:8008`. Read the two warnings first.

**Warning 1: a proxy on the same computer skips pairing and opens `/mcp`.** GitTok decides "local or LAN" from the address of the peer, and it does not read `X-Forwarded-For`. Every request that comes through a local proxy looks like a loopback request. So the pairing token is not asked for, and `/mcp` (which can read your configured repos) answers too. Whoever can reach the proxy can reach all of GitTok. Block `/mcp` in the proxy when the proxy can do that, and limit who can reach the proxy.

**Warning 2: the proxy's host name must be allowed.** GitTok answers only to `Host` names it knows (`127.0.0.1`, `localhost`, the LAN addresses, this computer's host name and `<short name>.local`). Any other name gets HTTP 421. Add the name that the phone uses to `server.allowed_hosts` in `local/settings.yaml` (installed: `~/.gittok/local/settings.yaml`), then restart `gittok serve`:

```yaml
server:
  allowed_hosts: [mymac.example-tailnet.ts.net]
```

### Recipe A: Tailscale Serve

For devices in your own tailnet. Tailscale gets a real certificate, so the phone needs no setup beyond Tailscale itself. HTTPS certificates must be on for the tailnet (Tailscale admin console, DNS page).

```bash
tailscale serve --bg 8008        # serves https://<machine>.<tailnet>.ts.net to the tailnet
tailscale serve status           # shows the URL
```

Put `<machine>.<tailnet>.ts.net` in `server.allowed_hosts`. Keep `server.lan` off: Tailscale connects to `127.0.0.1`. Tailscale Serve forwards every path, also `/mcp` (warning 1), so every device and user that your tailnet ACLs let reach this computer can use it. Do not use `tailscale funnel`: it opens the server to the internet.

### Recipe B: mkcert and a local reverse proxy

For devices on the same Wi-Fi. [mkcert](https://github.com/FiloSottile/mkcert) makes a private certificate authority and a certificate for a name of your choice. Each phone must then trust that authority, which is the hard part.

```bash
mkcert -install
mkcert mymac.local               # writes mymac.local.pem and mymac.local-key.pem
mkcert -CAROOT                   # the folder with rootCA.pem: install this file on each phone
```

On iOS, open `rootCA.pem` to install the profile, then turn it on in Settings, General, About, Certificate Trust Settings. On Android, install it as a CA certificate in the security settings. Never share `rootCA-key.pem`.

A [Caddy](https://caddyserver.com) config that forwards to GitTok and blocks `/mcp`:

```
mymac.local:8443 {
	tls /path/to/mymac.local.pem /path/to/mymac.local-key.pem
	@mcp path /mcp /mcp/*
	respond @mcp 403
	reverse_proxy 127.0.0.1:8008
}
```

Open `https://mymac.local:8443` on the phone. If the name is this computer's own `<short name>.local`, it is already allowed. For any other name, add it to `server.allowed_hosts`.

### If it does not work

- HTTP 421 `unknown Host`: the name in the address bar is not in `server.allowed_hosts`.
- HTTP 403 `cross-origin request` on taps (like, save, answer): the same cause; the check uses the same list.
- The page loads but there is no install prompt or offline mode: the certificate is not trusted on that device. A page with a certificate warning does not register a service worker.

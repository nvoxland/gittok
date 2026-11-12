# Installing GitTok for daily use

## Install

You need macOS, `uv`, `git`, and Claude Code. You do not need a clone.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh        # if you do not have uv yet
uv tool install gittok
gittok --version
```

The wheel is also attached to each GitHub release of the repository: `uv tool install ./gittok-<version>-py3-none-any.whl` installs such a file. A git URL install (`uv tool install git+<url>`) does not work, because the web build is not committed. `DEV.md` says how to build the wheel in a clone.

The tree-sitter structure layer and ast-grep rules come with every install. One extra is optional, because it is large (torch and mlx, about 1 GB, plus the models it downloads later):

```bash
uv tool install 'gittok[images]'   # mflux art (Apple silicon only)
```

The package carries its own shared files: `config/`, the web app, and the skills and agents. You edit none of them. Your own files live in one home folder:

- `~/.gittok/local/`: `repos.yaml`, `profiles/`, and the `settings.yaml`, `personas.yaml`, `mascots.yaml` overlays (`docs/config.md`).
- `~/.gittok/data/`: the database, card images, and logs.
- `~/.gittok/repos/`: the clones of repos you added by URL.

Set `GITTOK_HOME` to use another folder. GitTok makes it on first use.

Then set up Claude Code and the background server:

```bash
gittok install            # dry run: shows what it would do
gittok install --apply    # MCP at http://127.0.0.1:8008/mcp, skills and agents, LaunchAgent
```

The LaunchAgent runs `gittok serve` from your home folder. To run it by hand, use `gittok serve`. The feed is at `http://127.0.0.1:8008` on this computer. The server also serves the feed to your local network, for a phone: read "Phone access" below.

After the install, start a new Claude Code session. You manage GitTok by asking Claude. The sections below say what to ask, and give the command for each step for people who prefer a terminal.

## Add and remove repos

Ask Claude:

- "Add the repo at ~/src/myapp to GitTok."
- "Add https://example.com/acme/storefront.git to GitTok."
- "Which repos does GitTok have?"
- "Remove storefront from GitTok."

Claude calls the `add_repo`, `list_repos` and `remove_repo` MCP tools. Claude Code asks for your permission before each call.

- A local path must be the root of a git repo that has a commit, and not a directory inside a repo that is already added. It may be anywhere on this computer. GitTok reads it and never changes it.
- A remote URL (`https://`, `ssh://`, `git://` or `git@host:org/repo.git`) is cloned into the GitTok home folder, at `repos/<name>` (installed: `~/.gittok/repos/<name>`). GitTok fetches this clone before each analysis.
- A URL must not hold a password or token. For a private repo, use an ssh URL or a git credential helper. The clone does not ask for a password; it fails.
- To limit where the `add_repo` tool may add a local repo, set `repos.allowed_roots` in `local/settings.yaml` (`docs/config.md`). The list is empty by default, which means no limit.
- Removing a repo takes it out of `local/repos.yaml`. GitTok deletes the directory only when it is a clone that GitTok made itself (a repo added by URL, at `repos/<name>`). It never touches a directory that you gave. Cards already made from the repo stay.

After a repo is added, Claude offers to profile it (`/gittok-profile-repo <name>`). Then ask for cards ("make GitTok cards", or `/gittok-generate`).

The same steps as commands:

```bash
gittok repos add myapp ~/src/myapp
gittok repos add https://example.com/acme/storefront.git    # the name comes from the URL: storefront
gittok repos                                            # list
gittok repos remove storefront
```

`gittok repos add` in a terminal is your own act: `repos.allowed_roots` does not apply to it. You can also write `~/.gittok/local/repos.yaml` yourself:

```yaml
repos:
  myapp:
    path: ~/src/myapp
```

## Phone access

GitTok is made for a phone, so LAN serving is on by default (`server.lan: true`). The server binds all interfaces, and a device that is not this computer must pair once.

To pair a phone, ask Claude: "Pair my phone." Claude calls the `pairing_link` tool. It opens `http://127.0.0.1:8008/pairing` in the browser of this computer. That page shows one QR code for each LAN address of the computer, with the link as text. Scan the code with the phone camera. Both devices must be on the same network. The page answers this computer only. A server that you start by hand with `gittok serve` also prints the pairing links (lines that begin with `pair:`).

What this means for your network:

- The feed goes over plain HTTP, not HTTPS.
- Any device on the same network can reach the port. It gets nothing until it opens the pairing link or QR code once. The MCP endpoint (`/mcp`) is never served to the network.
- Someone who can watch traffic on that network could read the pairing token and the cards. Cards hold excerpts of your code.
- So use it on a network you trust, such as your home network. Take care on shared or public Wi-Fi.
- "HTTPS on a LAN" below has an optional recipe.

To turn it off, ask Claude: "Turn off phone access." Claude calls `set_lan(enabled=false)`, which writes `server.lan: false` to `local/settings.yaml`. You can also write that yourself, or start the server with `--no-lan`. The server then answers this computer only. The setting is read when the server starts, so restart it: `launchctl kickstart -k gui/$(id -u)/dev.gittok.serve` for the LaunchAgent (Claude can run this), or `/mcp`, gittok, Reconnect for a server that a Claude Code session owns. "Turn on phone access" does the reverse.

The pairing link holds a secret token. Do not put it in a file, a commit or a chat with other people. To make a new token, delete `<data_dir>/lan_token` and restart the server; every device must then pair again.

## Upgrade

```bash
uv tool upgrade gittok
gittok install --apply --force
```

The second command refreshes the skills and agents, and loads the LaunchAgent again so the new server starts. To remove GitTok, see "Undo".

## Clone or installed tool

The project `.mcp.json` flow (a Claude session owns the server) works only in a clone (`DEV.md`). A clone uses its own `config/`, `local/` and `data/`. `GITTOK_ROOT` points to a clone from any directory.

How GitTok picks its folders:

1. `GITTOK_ROOT`, if set: that clone holds everything.
2. A clone found by walking up from the current directory (a `config/settings.yaml`).
3. Otherwise the installed app: shared files from the package, your files from `GITTOK_HOME`.

## What `gittok install` does

`gittok install` has three parts. In a clone, write `uv run gittok install`.

| Part | Flag | What it does |
|---|---|---|
| MCP | `--mcp` | Runs `claude mcp add --scope user --transport http gittok http://<host>:<port>/mcp`. Claude Code then sees the server from any directory. Skipped if `claude mcp get gittok` already shows the same URL. |
| Skills | `--skills` | Copies the skills `gittok-generate`, `gittok-steer` and `gittok-profile-repo` to `~/.claude/skills/`, and the agents `gittok-writer.md` and `gittok-scout.md` to `~/.claude/agents/`. The source is `.claude/` in a clone, or the package when installed. |
| LaunchAgent | `--launchd` | Writes `~/Library/LaunchAgents/dev.gittok.serve.plist` and loads it with `launchctl bootstrap`. `gittok serve` then starts at login and restarts if it stops. Logs go to `<data_dir>/logs/serve.log`. |

With no part flag, all three run. The MCP address comes from the settings (`server.host`, `server.port`). The output ends with a note about phone access, because the server that the LaunchAgent starts serves the feed to your local network ("Phone access").

The other flags:

- `--apply`: make the changes. Without it, the command only prints what it would do.
- `--force`: overwrite a skill or agent file that differs from the shipped copy.
- `--uninstall`: remove the LaunchAgent. It does not remove the MCP entry or the skills; it prints the commands for those.

The installer does not change your Claude Code settings. It adds no hooks (see "Session hooks") and no permissions.

How the LaunchAgent runs the server:

- Installed tool: it runs the `gittok` executable with `serve`, in your GitTok home folder, with `GITTOK_HOME` set to that folder.
- Clone: it runs `uv run --project <clone> gittok serve` in the clone. A Claude Code session in the clone then finds port 8008 in use, so its own `gittok mcp --ui` runs MCP only and the LaunchAgent serves the feed.

## Local config

Settings that belong to one machine live in `local/`. `docs/config.md` describes each file and key. This directory is in `.gitignore` and is never committed. `config/` keeps only shared product data. All parts are optional; a missing `local/` means no repos.

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

- If a skill or agent file under `~/.claude/` exists and differs from the shipped copy, it is skipped. The output shows a short diff. Use `--force` to overwrite.
- If `claude` is not on PATH, the MCP command is printed for you to run.
- If `launchctl` is not on PATH, the plist is written and the `launchctl bootstrap` command is printed.
- The LaunchAgent PATH holds the directories of `uv`, `git`, and `claude` as found at install time. Run `install --launchd --apply` again if you move them.

## Undo

Each part has its own undo. `gittok install` prints the first three at the end of every run.

| Part | Undo |
|---|---|
| MCP entry | `claude mcp remove gittok --scope user` |
| Skills and agents | `rm -rf ~/.claude/skills/gittok-generate ~/.claude/skills/gittok-steer ~/.claude/skills/gittok-profile-repo ~/.claude/agents/gittok-writer.md ~/.claude/agents/gittok-scout.md` |
| LaunchAgent | `gittok install --uninstall --launchd --apply` (runs `launchctl bootout gui/<uid> <plist>` and removes `~/Library/LaunchAgents/dev.gittok.serve.plist`) |
| Session hooks | Remove the two hook lines and the permission line that you added (see "Session hooks") |
| The tool | `uv tool uninstall gittok` |
| Your data | `rm -rf ~/.gittok` (or your `GITTOK_HOME`). This deletes your repo list, profiles, cards, and the clones GitTok made. It never touches a repo directory that you gave by path |
| Grammar cache | `rm -rf ~/Library/Caches/tree-sitter-language-pack` |

Remove the LaunchAgent before you uninstall the tool. The optional renderers have their own undo: remove the memegen container and image (`docker rm -f memegen`, `docker rmi memegen`), and delete the folder that `mflux-save` wrote.

## Session hooks (optional)

Two SessionStart hooks tell a Claude Code session when the feed wants cards (`docs/scheduling.md`). A clone has them in its project `.claude/settings.json`. `gittok install` does not add them. For an installed tool, add them yourself to `~/.claude/settings.json` (every session), or to the `.claude/settings.local.json` of one project (sessions in that project only). Merge this into the file:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          { "type": "command", "command": "gittok health --hint 2>/dev/null || true" },
          { "type": "command", "command": "gittok feed-watch --hint 2>/dev/null || true" }
        ]
      }
    ]
  },
  "permissions": {
    "allow": ["Bash(uv run --quiet gittok feed-watch)"]
  }
}
```

- `gittok health --hint` prints nothing when nothing is needed. It prints one line when the feed is low, when a repo has no profile or its manifests changed, when a grammar is missing, or when analyzer facts are stale.
- `gittok feed-watch --hint` always prints one line. It tells the session to start `uv run --quiet gittok feed-watch` in the background. The permission line lets that exact command run without a prompt. The command also works for an installed tool, because `uv run` starts the `gittok` on your PATH. In a directory that is itself a uv project, `uv run` first syncs that project's environment.
- Leave out the second hook and the permission if you do not want sessions to start card generation by themselves.

The clone's own file uses `uv run --quiet gittok ...` in both hook commands.

## Structure layer (tree-sitter)

GitTok reads code structure (definitions, imports, comments) with tree-sitter. It is a normal dependency. A language whose grammar is not downloaded yet works on the regex patterns in `config/languages.yaml` and, for other file types, on plain text rules.

To get the grammars, ask Claude: "Download the GitTok grammars." Claude runs the second command below. With the session hooks on, Claude offers this itself when a grammar is missing.

```bash
gittok structure               # status: installed, grammars needed, grammars missing (JSON)
gittok structure --prefetch    # download the grammars for the repos in local/repos.yaml
```

In a clone, write `uv run gittok structure`. The package holds no grammars. They are a bundle of about 26 MB (12 languages) that the pack downloads from GitHub on first use into `~/Library/Caches/tree-sitter-language-pack/`. `--prefetch` does this once, on purpose, so a mining run never waits on the network. A grammar that is not in the cache is not used; `gittok health --hint` (the SessionStart hook) prints one line naming the missing grammars. Offline, run `--prefetch` on a machine with network and copy the cache dir. Shipped queries: python, typescript/tsx/javascript/svelte, clojure, go, ruby, java, rust. Another stack: let the profile skill write a `queries` entry (docs/learning.md, "The structure layer").

## Meme renderer (memegen)

Meme cards are drawn by a local [memegen](https://github.com/jacebrowning/memegen) server at `settings.render.memegen_url` (default `http://127.0.0.1:5001`). There is no public image, so build it from source. The build file is `Containerfile`, and the app listens on 5000 inside the container.

```bash
git clone --depth 1 https://github.com/jacebrowning/memegen.git
cd memegen && docker build -f Containerfile -t memegen .
docker run -d --name memegen --restart unless-stopped -p 127.0.0.1:5001:5000 memegen
curl -s http://127.0.0.1:5001/templates/ | head -c 200   # JSON means it works
```

Restart `gittok serve` afterwards. Until memegen answers, the brief skips the `meme` format and meme cards stay `pending_render`.

## Illustration renderer (mflux)

Illustration and comic cards, and the persona avatars, are drawn by [mflux](https://github.com/filipstrand/mflux) on Apple Silicon. It is a large download (torch and mlx, plus the model).

```bash
uv sync --group images                                                   # in a clone
uv tool install --force 'gittok[images]'                                 # installed tool
```

The commands below are for a clone. For an installed tool, write `gittok` in place of `uv run gittok`. `mflux-save` is then in the tool's environment and not on your PATH: run `"$(uv tool dir)/gittok/bin/mflux-save"` in place of `uv run mflux-save`.

**Save a quantized copy of the model first.** The default model, `z-image-turbo`, is 25 GB of bf16 weights. Without a saved copy, every render reads all 25 GB and quantizes it in memory, which swaps a 36 GB Mac and times out after 300 s. Save it once (this downloads the weights on the first run; close memory-hungry apps while it runs):

```bash
uv run mflux-save --model z-image-turbo --quantize 4 --path ~/.cache/mflux/z-image-turbo-q4
```

Then point the renderer at the folder in `local/settings.yaml`:

```yaml
render:
  mflux_path: ~/.cache/mflux/z-image-turbo-q4   # what mflux-save wrote
  mflux_model: z-image-turbo                    # the family it is based on
```

With `mflux_path` set, a render loads about 7 GB (q4) or 14 GB (q8) and takes 10 to 20 s per image at 8 steps. Use `--quantize 6` or `8` if the flat-vector mascots look rough at 4. Restart `gittok serve` (or `/mcp` → gittok → Reconnect) after installing. Then ask Claude to draw the persona avatars, or run:

```bash
uv run gittok avatars      # draws the persona avatars; the first image also warms the Metal cache
```

Until mflux is importable, the brief skips `mascot_scene` and `comic` and those cards stay `pending_render`.

## Other MCP clients

`gittok serve` gives a streamable-HTTP MCP endpoint at `http://127.0.0.1:8008/mcp` (the host and port come from your settings). It answers loopback peers only. The project tests it with Claude Code only. The skills and agents are Claude Code files, and they pin Claude models, so another client must drive the tools by hand.

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

LAN serving is on by default (`server.lan: true`): `gittok serve` and `gittok mcp --ui` bind all interfaces. "Phone access" above says what that means and how to pair a device. To turn it off, set `server.lan: false` in `local/settings.yaml`, or pass `--no-lan`; the server then binds `127.0.0.1`. An explicit `--host` is used as given, and `--lan` forces LAN serving. A bind to any non-loopback address is token-protected in the same way. The feed and `/api/*` need a pairing cookie from non-loopback peers: scan the QR code from the pairing page, or open a `pair:` link, once on each device. The token lives in `<data_dir>/lan_token` (mode 0600). `/mcp` and the pairing page (`/pairing`) are loopback-only and refuse LAN peers. PWA install and offline mode need HTTPS, because service workers do not register on plain-HTTP LAN origins. See `docs/social.md`.

## HTTPS on a LAN (optional, for PWA install)

You do not need this to use the feed. Plain HTTP on the LAN works in a browser tab. HTTPS is needed only for "Add to Home Screen" as an installed app with offline mode, because browsers register a service worker only on HTTPS or `localhost`.

**The project does not test these recipes.** GitTok itself serves plain HTTP only. The recipes use a second program on the same computer that holds the certificate and forwards to `http://127.0.0.1:8008`. Read the two warnings first.

**Warning 1: a proxy needs LAN serving on (the default), and each device must pair.** A proxy on the same computer connects from `127.0.0.1`. GitTok does not treat such a request as local when it has one of the headers `X-Forwarded-For`, `Forwarded`, `X-Forwarded-Host`, `X-Forwarded-Proto` or `X-Real-IP`. A request with one of these headers never gets `/mcp` (HTTP 403), and it needs the pairing cookie, the same as a LAN device. Know these limits:

- The server has a pairing token when LAN serving is on (the default) or when `--host` is not a loopback address. If you turned LAN serving off (`server.lan: false`, or `--no-lan`) there is no token, so nothing can pair: GitTok refuses every request that has one of these headers with HTTP 403 (`proxy_needs_pairing`). Set `server.lan: true` again and restart before you use a proxy.
- A proxy that sends none of these headers still looks local, so it skips pairing and opens `/mcp` (which can read your configured repos). Tailscale Serve and Caddy send the headers by default. nginx sends them only when its config has `proxy_set_header X-Forwarded-For ...`. Do not remove these headers in the proxy config.
- Pair each device on the address that it uses. Open `https://<the proxy's name>/pair?t=<token>` on the device: the token is the last part of the pairing link (ask Claude for the pairing link, or read it on the pairing page). A cookie from the plain `http://<LAN address>:8008` address does not count for the proxy's name.

Also limit who can reach the proxy.

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

Put `<machine>.<tailnet>.ts.net` in `server.allowed_hosts`. Tailscale connects to `127.0.0.1` and adds `X-Forwarded-For`, so GitTok refuses `/mcp` for these requests (warning 1). If you turned `server.lan` off, GitTok refuses every request from the tailnet (HTTP 403, `proxy_needs_pairing`). Keep `server.lan` on (the server also answers paired devices on your LAN) and open `https://<machine>.<tailnet>.ts.net/pair?t=<token>` once on each device. Do not use `tailscale funnel`: it opens the server to the internet.

### Recipe B: mkcert and a local reverse proxy

For devices on the same Wi-Fi. [mkcert](https://github.com/FiloSottile/mkcert) makes a private certificate authority and a certificate for a name of your choice. Each phone must then trust that authority, which is the hard part.

```bash
mkcert -install
mkcert mymac.local               # writes mymac.local.pem and mymac.local-key.pem
mkcert -CAROOT                   # the folder with rootCA.pem: install this file on each phone
```

On iOS, open `rootCA.pem` to install the profile, then turn it on in Settings, General, About, Certificate Trust Settings. On Android, install it as a CA certificate in the security settings. Never share `rootCA-key.pem`.

A [Caddy](https://caddyserver.com) config that forwards to GitTok. Caddy adds `X-Forwarded-For`, so GitTok refuses `/mcp` itself; the config blocks it a second time:

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
- HTTP 403 `proxy_needs_pairing`: LAN serving was turned off, so there is no pairing token. Set `server.lan: true`, restart, and pair the device.
- HTTP 401 `pair this device`: open `https://<the proxy's name>/pair?t=<token>` on the device.
- HTTP 403 `cross-origin request` on taps (like, save, answer): the same cause; the check uses the same list.
- The page loads but there is no install prompt or offline mode: the certificate is not trusted on that device. A page with a certificate warning does not register a service worker.

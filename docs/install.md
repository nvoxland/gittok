# Installing GitTok

## Install

You need macOS, `uv`, `git`, and a coding agent. GitTok supports Claude Code and Codex. You do not need a clone.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh        # if you do not have uv yet
uv tool install 'gittok[images]'
gittok --version
cd ~/gittok                   # a new or empty directory of your choice (make it first)
gittok init .
claude                        # approve the MCP server `gittok` when Claude Code asks
```

The wheel is also attached to each GitHub release of the repository: `uv tool install ./gittok-<version>-py3-none-any.whl` installs such a file. A git URL install (`uv tool install git+<url>`) does not work, because the web build is not committed. `DEV.md` says how to build the wheel in a clone.

The `images` extra adds mflux, which draws the illustration and comic cards and the persona avatars. It works on Apple silicon only, and it is large (torch and mlx, about 1 GB, plus the model it downloads later; see "Illustration renderer"). On a Mac that is not Apple silicon the extra adds nothing. For a smaller install without illustrated cards, leave the extra out:

```bash
uv tool install gittok
```

GitTok then does not ask for the illustration and comic formats. The tree-sitter structure layer and ast-grep rules come with every install.

The tool alone does nothing. GitTok works in a **GitTok directory**, and only while a Claude Code or Codex session is open in it. Nothing is installed outside the directory: no user-wide MCP entry, no files in your home folder, and no background service.

## The GitTok directory

`gittok init <dir>` needs the path. It makes the directory, and its parents, if they do not exist. If the directory exists, it must be empty (a `.DS_Store` file does not count). The command stops with an error and changes nothing when:

- the directory is not empty, or it is already a GitTok directory (use `gittok update` for that);
- the path is a file;
- the path is inside another GitTok directory, or inside a clone of the GitTok source.

It writes these files:

| File | What it is |
|---|---|
| `gittok.yaml` | The marker. It makes the directory a GitTok directory. It holds the version of the tool that wrote the files, and a checksum of each file, so `gittok update` can see which files you edited |
| `AGENTS.md` | Tells a coding agent what the directory is, how a first run goes, and how to make cards with the MCP tools |
| `local/repos.yaml` | Your repo list. It has only comments at the start |
| `.gitignore` | Ignores `data/`, `repos/` and `*.bak`, in case you put the directory under git |

And these files for Claude Code:

| File | What it is |
|---|---|
| `.mcp.json` | The MCP entry. Claude Code starts `gittok mcp --ui` (stdio) when a session starts here |
| `CLAUDE.md` | One line, `@AGENTS.md`. Claude Code reads `CLAUDE.md`, and this makes it read `AGENTS.md` |
| `.claude/skills/` | The skills `gittok-generate`, `gittok-steer` and `gittok-profile-repo` |
| `.claude/agents/` | The agents `gittok-writer` and `gittok-scout` |
| `.claude/settings.json` | The two session hooks and one permission ("Session hooks" below) |

And these files for Codex:

| File | What it is |
|---|---|
| `.codex/config.toml` | Starts the same stdio MCP server, `gittok mcp --ui` |
| `.codex/hooks.json` | The same SessionStart hints; review and trust them with `/hooks` |
| `.agents/skills/` | Thin adapters for the three shared workflows |
| `.agents/GITTOK.md` | Codex startup, delegation, model and process instructions |

Start `codex` in this directory and trust the project configuration. Use
`$gittok-generate`, `$gittok-profile-repo <repo>` and `$gittok-steer`, or ask in plain
language. Check `/mcp` if GitTok tools are missing. Restart Codex after MCP/server
changes. Existing directories gain support with `gittok update`.

The workflow bodies and worker instructions have one source, at the historical
`.claude/skills/` and `.claude/agents/` paths. Codex adapters read these files with
runtime adaptations; keep `.claude/` even if you only use Codex. Generation uses
Codex subagents and inherits the session model. Claude model names are cost hints
only. No Claude installation or Claude subprocess is needed.

Codex uses [project configuration](https://developers.openai.com/codex/config-reference/),
[local skills](https://developers.openai.com/codex/skills/), and
[trusted hooks](https://learn.chatgpt.com/docs/hooks).
Startup instructions provide a fallback when hooks do not run. Idle refill depends
on the client's background completion support; otherwise health is checked on the
next user turn. See [Keeping the feed full](scheduling.md).

GitTok makes the rest when it needs it:

- `local/`: `repos.yaml`, `mascots.yaml`, `profiles/`, and an optional override file for each shipped config file, such as `settings.yaml` or `scan_defaults.yaml` (`docs/config.md`).
- `data/`: the database, card images, and logs.
- `repos/`: the clones of repos you added by URL.

The package carries its own shared files: `config/`, the web app, and the originals of the skills and agents. You edit none of them.

### The session owns the server

When you start `claude` in the directory, Claude Code starts `gittok mcp --ui`. That process is the MCP server: Claude talks to it over stdio. It also starts the feed server (`gittok serve`) as a child process on port 7313. The feed server serves the feed and the web app, and does the background work (rendering, learning, notifications, clean-up). It has no MCP endpoint. When the session ends, the child stops. So the feed, on this computer and on a phone, works only while a session is open.

A `gittok` command (`gittok repos`, `gittok health`, ...) finds the GitTok directory by walking up from the current directory to `gittok.yaml`. Outside a GitTok directory, every command but `gittok init`, `gittok --version` and `gittok --help` stops with one line that says so. To use a directory from another place, set `GITTOK_ROOT=<dir>` for that command.

### More than one session, more than one directory

- **Two sessions in the same directory.** The first session owns the feed server. The second finds port 7313 in use and runs the MCP server only. Both sessions work, and both see the same cards. The feed stops when the first session ends; then run `/mcp`, gittok, Reconnect in the other session to start it again. Claude is told this when the session starts.
- **Two directories.** You can make as many GitTok directories as you like (for example `gittok init ~/gittok-work`). Each has its own repos, cards and settings. Two of them cannot serve the same port at the same time: the second session gets the MCP tools for its own directory, but the feed on port 7313 still shows the first directory. Claude is told which directory has the port. To use both at once, set another port in one of them, in `local/settings.yaml`:

  ```yaml
  server:
    port: 8009
  ```

### Move or copy the directory

The directory has no absolute path of its own inside it. To move it, end the session, move the directory, and start `claude` in the new place. Claude Code asks again to approve the MCP server, because the approval is per directory. A copy works the same way, and is a full backup: repo list, profiles, cards and what the feed learned. Paired devices stay paired, because the pairing token is in `data/`. A repo that you added by path is stored as an absolute path in `local/repos.yaml`, so it still points to the same place.

After the setup, you manage GitTok by asking Claude. The sections below say what to ask, and give the command for each step for people who prefer a terminal. Run the commands inside the GitTok directory.

## Add and remove repos

Ask Claude:

- "Add the repo at ~/src/myapp to GitTok."
- "Add https://example.com/acme/storefront.git to GitTok."
- "Which repos does GitTok have?"
- "Remove storefront from GitTok."

Claude calls the `add_repo`, `list_repos` and `remove_repo` MCP tools. Claude Code asks for your permission before each call.

Removing a repo removes all that GitTok made for it: its cards (also the saved ones) with their images, its analysis, its profile (`local/profiles/<name>.yaml`), the rules on the repo, and a mascot of the repo that you defined yourself and no other repo uses. A clone that GitTok made from a URL is deleted. A directory of your own is never touched, and what the feed learned about your taste stays. Claude tells you the counts. To keep the cards, the profile and the mascot, say so ("remove storefront but keep its cards"; the command is `gittok repos remove storefront --keep-data`): the feed does not show them until you add a repo with the same name again.

- A local path must be the root of a git repo that has a commit, and not a directory inside a repo that is already added. It may be anywhere on this computer. GitTok reads it and never changes it.
- A remote URL (`https://`, `ssh://`, `git://` or `git@host:org/repo.git`) is cloned into the GitTok directory, at `repos/<name>`. GitTok fetches this clone before each analysis.
- A URL must not hold a password or token. For a private repo, use an ssh URL or a git credential helper. The clone does not ask for a password; it fails.
- To limit where the `add_repo` tool may add a local repo, set `repos.allowed_roots` in `local/settings.yaml` (`docs/config.md`). The list is empty by default, which means no limit.
- Removing a repo takes it out of `local/repos.yaml`. GitTok deletes the directory only when it is a clone that GitTok made itself (a repo added by URL, at `repos/<name>`). It never touches a directory that you gave. Cards already made from the repo stay.

After a repo is added, Claude profiles it (`/gittok-profile-repo <name>`) and then makes the first cards (`/gittok-generate`). It does not ask first; it says in one line what it does. The profile holds the rules that find the code worth teaching. It takes a few minutes and some model quota, and Claude may ask permission to run a code analyzer or to download grammars. A repo added with the command below gets its profile the next time cards are made. Later, Claude only offers a new profile: when the manifests of the repo changed, or when several rules of the profile do badly.

The same steps as commands:

```bash
gittok repos add myapp ~/src/myapp
gittok repos add https://example.com/acme/storefront.git    # the name comes from the URL: storefront
gittok repos                                            # list
gittok repos remove storefront                          # also its cards, profile and mascot; --keep-data keeps them
```

`gittok repos add` in a terminal is your own act: `repos.allowed_roots` does not apply to it. You can also write `local/repos.yaml` yourself:

```yaml
repos:
  myapp:
    path: ~/src/myapp
```

## Phone access

GitTok is made for a phone, so LAN serving is on by default (`server.lan: true`). While a session is open, the feed server binds all interfaces, and a device that is not this computer must pair once.

A device pairs by code:

1. Get the feed address. Claude gives it at the start of each session (the SessionStart line `gittok url --hint`), and you can ask at any time: "What is the feed address?" Claude calls the `feed_address` tool. In a terminal, `gittok url` prints it.
2. On the device, open the address (both devices on the same network) and tap "Pair with a code". The device shows a code such as `K7QM-2D`.
3. Tell Claude: "pair code K7QM-2D" (or run `gittok pair K7QM-2D`). The device opens the feed a few seconds later. A code lasts 10 minutes and works once.

An app on the phone's home screen keeps its own cookies, apart from the browser: pair it inside the app the same way. A server that you start by hand with `gittok serve` prints the addresses (lines that begin with `lan:`).

What this means for your network:

- The feed goes over plain HTTP, not HTTPS.
- Any device on the same network can reach the port. It gets nothing until you tell Claude the code that it shows. A device can ask for codes, but only you can approve one, in your Claude Code session. The MCP server speaks stdio only; the feed server has no MCP endpoint.
- Someone who can watch traffic on that network could read the pairing cookie and the cards. Cards hold excerpts of your code.
- So use it on a network you trust, such as your home network. Take care on shared or public Wi-Fi.
- "HTTPS on a LAN" below has an optional recipe.

To turn it off, ask Claude: "Turn off phone access." Claude calls `set_lan(enabled=false)`, which writes `server.lan: false` to `local/settings.yaml`. You can also write that yourself, or start the server with `--no-lan`. The server then answers this computer only. The setting is read when the server starts, so restart it: run `/mcp`, pick gittok, and Reconnect, or start a new session. "Turn on phone access" does the reverse.

A paired device holds a cookie with the secret token from `<data_dir>/lan_token`. To make a new token (for example after you lost a phone), delete that file and restart the server; every device must then pair again.

## Upgrade

```bash
uv tool upgrade gittok
```

uv records the extras that a tool was installed with (in the tool's `uv-receipt.toml`), and the upgrade uses that record. So a tool installed as `gittok[images]` keeps mflux.

The tool is new now, but the skills, agents, settings and `AGENTS.md` in your GitTok directory are still the old copies. The next session in the directory prints one line about this, and Claude offers to update. Say yes, or run it yourself in the directory:

```bash
gittok update              # or: gittok update ~/gittok
```

`gittok update` writes again the files that `gittok init` made: `AGENTS.md`, `CLAUDE.md`, `.mcp.json`, the shared skills and agents, both clients’ configuration and adapters, and the version in `gittok.yaml`. It prints each file that it changed. It never touches `local/`, `data/`, `repos/` or `.gitignore`.

- A file that you did not edit is replaced.
- A file that you edited is replaced too, but your copy is saved next to it first as `<name>.bak` (for example `.claude/settings.json.bak`). The output names it. Copy your changes back by hand if you still want them.
- A file that you deleted is written again.

Start a new session after the update, so Claude Code loads the new files. Do the same in each GitTok directory you have.

## Uninstall

1. End the Claude Code session in the GitTok directory. The feed server stops with it.
2. Delete the GitTok directory. This deletes your repo list, profiles, cards, and the clones that GitTok made in `repos/`. It never touches a repo directory that you gave by path.
3. `uv tool uninstall gittok`.

Two things are outside the directory, and neither comes from `gittok init`:

- The grammar cache of the tree-sitter pack: `rm -rf ~/Library/Caches/tree-sitter-language-pack`.
- The optional illustration renderer: delete the folder that `mflux-save` wrote. (The meme templates are in `data/memes/`, inside the directory.) An older install may have a memegen Docker container: `docker rm -f memegen`, `docker rmi memegen`.

## A clone of the source

A clone of the GitTok source is its own GitTok directory, for development (`DEV.md`). It has its own `.mcp.json`, `local/`, `data/` and `repos/`, and it runs the code in the clone with `uv run gittok ...`.

How GitTok picks its folders:

1. `GITTOK_ROOT`, if set: that GitTok directory, or that clone.
2. Otherwise it walks up from the current directory. A directory with `gittok.yaml` is a GitTok directory: your files are there, and the shared files come from the package. A directory with `config/settings.yaml` is a clone: it holds everything.
3. If it finds neither, the command stops: "not inside a GitTok directory".

## Local config

Your own settings live in `local/` of the GitTok directory. `docs/config.md` describes each file and key. The shared product data (`config/`) is inside the package. All parts are optional; a missing `local/` means no repos.

- `local/repos.yaml`: the repos and groups to analyze.
- `local/profiles/<repo>.yaml`: the profile of each repo.
- `local/mascots.yaml`: the mascot of each repo. GitTok ships none; Claude makes one when you add a repo, if the image renderer works.
- `local/settings.yaml`: merged over `config/settings.yaml`, key by key inside each section.
- `local/personas.yaml`: merged over the shipped file, per name and field by field. The edit tools write only here.
- One optional file for each other shipped file (`local/scan_defaults.yaml`, `local/languages.yaml`, `local/queries/`, `local/file_types.yaml`, `local/secrets.yaml`, `local/claims.yaml`, `local/meme_templates.yaml`, `local/defaults.yaml`, `local/reward.yaml`): merged over the shipped one. Maps merge key by key and lists add. Ask Claude for the change, or write the file yourself; `gittok config check` validates it.
- `local/.edit.lock`: the lock file of the edit tools.

## Session hooks

Three SessionStart hints tell a Claude Code session when the feed wants cards (`docs/scheduling.md`). `gittok init` writes them to `.claude/settings.json` of the GitTok directory, so they run only for sessions in that directory:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          { "type": "command", "command": "gittok url --hint 2>/dev/null || true" },
          { "type": "command", "command": "gittok health --hint 2>/dev/null || true" },
          { "type": "command", "command": "gittok feed-watch --hint 2>/dev/null || true" }
        ]
      }
    ]
  },
  "permissions": {
    "allow": ["Bash(gittok feed-watch)"]
  }
}
```

- `gittok url --hint` prints one line with the addresses of the feed (this computer, and the LAN when phone access is on), from `server.port`. Claude gives them to you in its first reply. It prints nothing when another GitTok directory has the port. `gittok url` prints the addresses alone.
- `gittok health --hint` prints nothing when nothing is needed. It prints one line when the feed is low, when a repo has no profile (Claude then profiles it), when its manifests changed or several of its rules do badly (Claude then offers a new profile), when a grammar is missing, when analyzer facts are stale, when the directory has the files of another GitTok version, or when another GitTok directory has the port.
- `gittok feed-watch --hint` always prints one line. It tells the session to start `gittok feed-watch` in the background. The permission line lets that exact command run without a prompt.
- If you do not want sessions to start card generation by themselves, remove the `feed-watch` hook and the permission. Put such a change in `.claude/settings.local.json`, or expect `gittok update` to write the shipped file again (it keeps your copy as `settings.json.bak`).

A clone of the source has the same hooks with `uv run --quiet gittok ...` commands, and its hint names `uv run --quiet gittok feed-watch`.

## Structure layer (tree-sitter)

GitTok reads code structure (definitions, imports, comments) with tree-sitter. It is a normal dependency. A language whose grammar is not downloaded yet works on the regex patterns in `config/languages.yaml` and, for other file types, on plain text rules.

To get the grammars, ask Claude: "Download the GitTok grammars." Claude runs the second command below. Claude offers this itself when a grammar is missing.

```bash
gittok structure               # status: installed, grammars needed, grammars missing (JSON)
gittok structure --prefetch    # download the grammars for the repos in local/repos.yaml
```

In a clone, write `uv run gittok structure`. The package holds no grammars. They are a bundle of about 26 MB (12 languages) that the pack downloads from GitHub on first use into `~/Library/Caches/tree-sitter-language-pack/`. `--prefetch` does this once, on purpose, so a mining run never waits on the network. A grammar that is not in the cache is not used; `gittok health --hint` (the SessionStart hook) prints one line naming the missing grammars. Offline, run `--prefetch` on a machine with network and copy the cache dir. Shipped queries: python, typescript/tsx/javascript/svelte, clojure, go, ruby, java, rust. Another stack: let the profile skill write a `queries` entry (docs/learning.md, "The structure layer").

## Meme templates

GitTok draws meme posts itself, with Pillow. It needs the template images, the text layouts and the fonts of [memegen](https://github.com/jacebrowning/memegen) (MIT). Download them once (about 20 MB, needs network):

```bash
gittok memes --prefetch     # in a clone: uv run gittok memes --prefetch
gittok memes                # which templates are downloaded, and which are missing
```

Or ask Claude: the SessionStart hint offers the download while templates are missing. The files go to `data/memes/` of the GitTok directory. Only template files are downloaded; no card text leaves your computer. The template images belong to their owners, so GitTok does not ship them. `settings.render.meme_source` names where they come from (the memegen repo on GitHub). Until a template is downloaded, the brief does not offer it, and with none downloaded it makes no meme posts. A template you add in `local/meme_templates.yaml` must be a memegen template id; run `--prefetch` again to get it.

## Illustration renderer (mflux)

Without this renderer GitTok makes no illustration cards and no mascot; everything else works. When it works, Claude gives each new repo a mascot (`docs/config.md`, "Mascots").

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

With `mflux_path` set, a render loads about 7 GB (q4) or 14 GB (q8) and takes 10 to 20 s per image at 8 steps. Use `--quantize 6` or `8` if the flat-vector mascots look rough at 4. Restart the feed server (`/mcp` → gittok → Reconnect) after installing. Then ask Claude to draw the persona avatars, or run:

```bash
uv run gittok avatars      # draws the persona avatars; the first image also warms the Metal cache
```

Until mflux is importable, the brief skips `mascot_scene` and `comic` and those cards stay `pending_render`.

## The feed server by hand

`gittok serve`, run inside a GitTok directory, starts the feed server without a Claude Code session. It prints the feed addresses and how a device pairs, and it runs until you stop it. It is for a look at the feed when no session is open, and for development. It does not make cards: only a Claude Code session does. A session that starts while it runs finds the port in use and does not start a second server.

## Other MCP clients

The MCP server speaks stdio only. A client that can start a stdio MCP server can run `gittok mcp` with a GitTok directory as the working directory (`gittok mcp --ui` to also start the feed server). `gittok init` writes no config for such a client: you add the server to it yourself. `AGENTS.md` in the directory tells an agent how to manage GitTok and how to make cards with the tools alone. Claude Code and Codex have built-in adapters as described above. Other clients need their own configuration and runtime adaptation.

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

LAN serving is on by default (`server.lan: true`): the feed server (started by `gittok mcp --ui`, or by hand with `gittok serve`) binds all interfaces. "Phone access" above says what that means and how to pair a device. To turn it off, set `server.lan: false` in `local/settings.yaml`, or pass `--no-lan`; the server then binds `127.0.0.1`. An explicit `--host` is used as given, and `--lan` forces LAN serving. A bind to any non-loopback address is token-protected in the same way. The feed and `/api/*` need a pairing cookie from non-loopback peers: pair each device once by code ("Phone access" above). The token lives in `<data_dir>/lan_token` (mode 0600). The feed server has no MCP endpoint. PWA install and offline mode need HTTPS, because service workers do not register on plain-HTTP LAN origins. See `docs/social.md`.

## HTTPS on a LAN (optional, for PWA install)

You do not need this to use the feed. Plain HTTP on the LAN works in a browser tab. HTTPS is needed only for "Add to Home Screen" as an installed app with offline mode, because browsers register a service worker only on HTTPS or `localhost`.

**The project does not test these recipes.** GitTok itself serves plain HTTP only. The recipes use a second program on the same computer that holds the certificate and forwards to `http://127.0.0.1:7313`. Read the two warnings first.

**Warning 1: a proxy needs LAN serving on (the default), and each device must pair.** A proxy on the same computer connects from `127.0.0.1`. GitTok does not treat such a request as local when it has one of the headers `X-Forwarded-For`, `Forwarded`, `X-Forwarded-Host`, `X-Forwarded-Proto` or `X-Real-IP`. A request with one of these headers needs the pairing cookie, the same as a LAN device. Know these limits:

- The server has a pairing token when LAN serving is on (the default) or when `--host` is not a loopback address. If you turned LAN serving off (`server.lan: false`, or `--no-lan`) there is no token, so nothing can pair: GitTok refuses every request that has one of these headers with HTTP 403 (`proxy_needs_pairing`). Set `server.lan: true` again and restart before you use a proxy.
- A proxy that sends none of these headers still looks local, so it skips pairing. Tailscale Serve and Caddy send the headers by default. nginx sends them only when its config has `proxy_set_header X-Forwarded-For ...`. Do not remove these headers in the proxy config.
- Pair each device on the address that it uses: open `https://<the proxy's name>` on the device, tap "Pair with a code", and tell Claude the code. A cookie from the plain `http://<LAN address>:7313` address does not count for the proxy's name.

Also limit who can reach the proxy.

**Warning 2: the proxy's host name must be allowed.** GitTok answers only to `Host` names it knows (`127.0.0.1`, `localhost`, the LAN addresses, this computer's host name and `<short name>.local`). Any other name gets HTTP 421. Add the name that the phone uses to `server.allowed_hosts` in `local/settings.yaml`, then restart the feed server:

```yaml
server:
  allowed_hosts: [mymac.example-tailnet.ts.net]
```

### Recipe A: Tailscale Serve

For devices in your own tailnet. Tailscale gets a real certificate, so the phone needs no setup beyond Tailscale itself. HTTPS certificates must be on for the tailnet (Tailscale admin console, DNS page).

```bash
tailscale serve --bg 7313        # serves https://<machine>.<tailnet>.ts.net to the tailnet
tailscale serve status           # shows the URL
```

Put `<machine>.<tailnet>.ts.net` in `server.allowed_hosts`. Tailscale connects to `127.0.0.1` and adds `X-Forwarded-For`, so GitTok asks these requests to pair (warning 1). If you turned `server.lan` off, GitTok refuses every request from the tailnet (HTTP 403, `proxy_needs_pairing`). Keep `server.lan` on (the server also answers paired devices on your LAN), open `https://<machine>.<tailnet>.ts.net` once on each device, and pair it by code. Do not use `tailscale funnel`: it opens the server to the internet.

### Recipe B: mkcert and a local reverse proxy

For devices on the same Wi-Fi. [mkcert](https://github.com/FiloSottile/mkcert) makes a private certificate authority and a certificate for a name of your choice. Each phone must then trust that authority, which is the hard part.

```bash
mkcert -install
mkcert mymac.local               # writes mymac.local.pem and mymac.local-key.pem
mkcert -CAROOT                   # the folder with rootCA.pem: install this file on each phone
```

On iOS, open `rootCA.pem` to install the profile, then turn it on in Settings, General, About, Certificate Trust Settings. On Android, install it as a CA certificate in the security settings. Never share `rootCA-key.pem`.

A [Caddy](https://caddyserver.com) config that forwards to GitTok. Caddy adds `X-Forwarded-For`, so each device must pair (warning 1):

```
mymac.local:8443 {
	tls /path/to/mymac.local.pem /path/to/mymac.local-key.pem
	reverse_proxy 127.0.0.1:7313
}
```

Open `https://mymac.local:8443` on the phone. If the name is this computer's own `<short name>.local`, it is already allowed. For any other name, add it to `server.allowed_hosts`.

### If it does not work

- HTTP 421 `unknown Host`: the name in the address bar is not in `server.allowed_hosts`.
- HTTP 403 `proxy_needs_pairing`: LAN serving was turned off, so there is no pairing token. Set `server.lan: true`, restart, and pair the device.
- HTTP 401 `pair this device`: tap "Pair with a code" on the device and tell Claude the code.
- HTTP 403 `cross-origin request` on taps (like, save, answer): the same cause; the check uses the same list.
- The page loads but there is no install prompt or offline mode: the certificate is not trusted on that device. A page with a certificate warning does not register a service worker.

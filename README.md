# GitTok

GitTok is a personal feed of short cards about your own codebases. It reads the git history and the code of the repos you add. Claude Code writes the cards through the GitTok MCP server, and GitTok checks each card against git before it stores it. You scroll the cards on your phone or in a browser.

Everything runs on your own machine. GitTok never writes to your repos.

<!-- screenshot -->

## Requirements

- macOS. Other platforms are not supported yet.
- [uv](https://docs.astral.sh/uv/). uv downloads Python 3.13 for you.
- git.
- [Claude Code](https://claude.com/claude-code). It writes the cards, and you manage GitTok by asking it. GitTok does not call a model API itself.

## Install

```bash
uv tool install gittok
gittok install            # dry run: prints what it would set up, changes nothing
gittok install --apply    # does it
```

`gittok install --apply` sets up three things:

- **The MCP server entry.** It registers GitTok with Claude Code for your user, so every Claude Code session can use the GitTok tools.
- **The skills and agents.** It copies them to `~/.claude/`. They teach Claude how to make cards, profile a repo, and manage GitTok.
- **A LaunchAgent.** It keeps the GitTok server (`gittok serve`) running. The server starts at login. It serves the feed on port 8008 and does the background work.

The installer changes no Claude Code settings. Each part has an undo step, and the command prints them. [docs/install.md](docs/install.md) describes each part.

The wheel is also attached to each GitHub release of this repository.

### Optional: illustrated cards

Illustration and comic cards are drawn by mflux on Apple silicon. It is a large download (about 1 GB, and a model later). To get it, install with the extra:

```bash
uv tool install 'gittok[images]'
```

Meme cards need a local memegen server. Without these renderers GitTok does not ask for those formats. See [docs/install.md](docs/install.md).

## Use it

Start a new Claude Code session, in any directory. You manage GitTok by asking Claude in plain words. Claude Code asks for your permission before it runs a GitTok tool.

1. **Add a repo.** Give a directory or a git URL:
   - "Add the repo at ~/src/myapp to GitTok."
   - "Add https://example.com/org/storefront.git to GitTok."

   GitTok reads a directory in place and never changes it. It clones a URL into its own folder and fetches it before each analysis.
2. **Profile it.** "Profile myapp." (or `/gittok-profile-repo myapp`). Claude writes the rules that find the code worth teaching in that repo. The first time, also say "download the grammars": GitTok then reads the code structure better.
3. **Make cards.** "Make GitTok cards." (or `/gittok-generate`).
4. **Open the feed** on this computer: <http://127.0.0.1:8008>.
5. **Pair your phone.** "Pair my phone." Claude opens a page with a QR code. Scan it with the phone camera. Both devices must be on the same network. You do this once for each device.

Later:

- **Steer the feed.** "Less memes." "More of the sync engine this week." "What have you learned about me?"
- **Remove a repo.** "Remove myapp from GitTok." GitTok deletes a clone that it made itself. It never touches a directory of your own. Cards already made from the repo stay.
- **More cards.** Ask again, or add the optional session hooks ([docs/install.md](docs/install.md), "Session hooks"). With them, a Claude Code session makes cards when the feed runs low.

### Phone access and your network

GitTok is made for a phone, so the server serves the feed to your local network. Know what that means:

- The feed goes over plain HTTP, not HTTPS.
- Any device on the same network can reach the port. It gets nothing until it opens the pairing link or QR code once. The MCP endpoint is never served to the network.
- Someone who can watch traffic on that network could read the pairing token and the cards. Cards hold excerpts of your code.
- So use it on a network you trust, such as your home network. Take care on shared or public Wi-Fi.
- To turn it off, say "turn off phone access", or set `server.lan: false` in `~/.gittok/local/settings.yaml`. The server then answers this computer only.

[docs/install.md](docs/install.md) has an optional HTTPS recipe. [SECURITY.md](SECURITY.md) says what GitTok protects and what it does not.

### Commands

Each step also has a command, for example `gittok repos add <name> <path-or-url>`, `gittok repos remove <name>` and `gittok structure --prefetch`. `gittok --help` lists them.

## Where your files live

Your files are in `~/.gittok/`. Set `GITTOK_HOME` to use another folder.

- `local/`: your repo list, repo profiles and settings ([docs/config.md](docs/config.md)).
- `data/`: the database, card images and logs.
- `repos/`: the clones of repos that you added by URL.

## Upgrade and uninstall

```bash
uv tool upgrade gittok
gittok install --apply --force    # refreshes the skills and agents, and restarts the server
```

To remove GitTok, follow "Undo" in [docs/install.md](docs/install.md). Remove the LaunchAgent before you uninstall the tool.

## Documentation

- [docs/install.md](docs/install.md): the installer, undo steps, session hooks, renderers, HTTPS on a LAN.
- [docs/config.md](docs/config.md): every config file and key.
- [docs/formats.md](docs/formats.md): card formats and visual kinds.
- [docs/learning.md](docs/learning.md): events, reward, ranking, repo profiles, garbage collection.
- [docs/social.md](docs/social.md): stories, notifications, offline mode, LAN access.
- [docs/api.md](docs/api.md): the feed HTTP API.
- [docs/scheduling.md](docs/scheduling.md): how to keep the feed full.
- [SPEC.md](SPEC.md): the design. What a card is, and how the parts fit.
- [DEV.md](DEV.md): how to develop and test GitTok, and how to release it.
- [CHANGELOG.md](CHANGELOG.md), [SECURITY.md](SECURITY.md), [LICENSE](LICENSE) (Apache 2.0).

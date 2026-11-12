# GitTok

GitTok is a personal feed of short cards about your own codebases. It reads the git history and the code of the repos you add. Claude Code writes the cards through the GitTok MCP server, and GitTok checks each card against git before it stores it. You scroll the cards in a browser or on your phone.

Everything runs on your own machine. GitTok never writes to your repos.

<!-- screenshot -->

## Requirements

- macOS. Other platforms are not supported yet.
- [uv](https://docs.astral.sh/uv/). uv downloads Python 3.13 for you.
- git.
- [Claude Code](https://claude.com/claude-code). It writes the cards. GitTok does not call a model API itself.
- Node 22, only to build the web app (a clone, or building the wheel).

## Quickstart (from a clone)

```bash
git clone <this-repo-url> gittok
cd gittok
uv sync
npm --prefix web install && npm --prefix web run build
```

Add a repo. Give a local directory, or a remote URL:

```bash
uv run gittok repos add myapp ~/src/myapp
uv run gittok repos add storefront <git-url>     # https://, ssh://, git:// or git@host:org/repo.git
uv run gittok structure --prefetch     # download the tree-sitter grammars once (needs network)
```

A local directory is read in place. A remote URL is cloned into the managed `repos/` directory of the clone, and GitTok fetches it before analysis.

Then start Claude Code in the clone:

```bash
claude
```

The project `.mcp.json` makes Claude Code start `gittok mcp --ui`. Approve the `gittok` MCP server when Claude Code asks. That process is the MCP server, and it also serves the feed on port 8008 while the session runs. In the session:

1. `/gittok-profile-repo myapp` writes the profile of the repo: the rules that find the code worth teaching.
2. `/gittok-generate` writes cards.
3. Open <http://127.0.0.1:8008>.

To change what the feed shows, tell Claude in plain words ("less memes", "more of the sync engine this week"). The `gittok-steer` skill does that.

### Phone access (optional)

The feed is served on `127.0.0.1` only by default. To open it to your local network, put this in `local/settings.yaml` and start the Claude Code session again:

```yaml
server:
  lan: true
```

Each device must then open a pairing link once: `http://<LAN address of the Mac>:8008/pair?t=<token>`. The token is in `data/lan_token`. A server that you start by hand with `uv run gittok serve --lan` prints the full pairing links. See [docs/social.md](docs/social.md), "LAN access", and [SECURITY.md](SECURITY.md) before you turn this on.

### Optional renderers

Meme cards need a local memegen server. Illustration and comic cards need mflux (Apple silicon, large download). Without them GitTok does not ask for these formats. See [docs/install.md](docs/install.md).

## Install as a tool (no clone at run time)

There is no published package yet. Build the wheel from a clone (next section), then:

```bash
uv tool install dist/gittok-<version>-py3-none-any.whl
gittok install            # dry run: shows what it would set up
gittok install --apply    # MCP entry for Claude Code, skills and agents, LaunchAgent
gittok repos add myapp ~/src/myapp
gittok structure --prefetch
```

`gittok install --apply` registers the MCP server with Claude Code for your user, copies the skills and agents to `~/.claude/`, and adds a LaunchAgent that keeps `gittok serve` running. After that, `/gittok-profile-repo` and `/gittok-generate` work in a Claude Code session in any directory, and the feed is at <http://127.0.0.1:8008>.

Your files live in `~/.gittok/` (set `GITTOK_HOME` to change it): `local/` for repos, profiles and settings, `data/` for the database and images, `repos/` for clones that GitTok made. [docs/install.md](docs/install.md) describes each part of the installer, the optional session hooks, and how to undo each part.

## Build the wheel

From a clone, with Node 22 and uv:

```bash
npm --prefix web install
npm --prefix web run build      # the web build goes into the wheel
uv build --wheel                # writes dist/gittok-<version>-py3-none-any.whl
```

The build stops with an error if `web/build/index.html` is missing. The wheel bundles `config/`, the web build, and the Claude Code skills and agents.

## Develop

```bash
uv sync
uv run pytest
uv run ruff check
npm --prefix web test
```

Build, test and architecture notes are in [AGENTS.md](AGENTS.md).

## Documentation

- [SPEC.md](SPEC.md): the design. What a card is, and how the parts fit.
- [docs/install.md](docs/install.md): the installer, undo steps, session hooks, renderers, HTTPS on a LAN.
- [docs/config.md](docs/config.md): every config file and key.
- [docs/formats.md](docs/formats.md): card formats and visual kinds.
- [docs/learning.md](docs/learning.md): events, reward, ranking, repo profiles, garbage collection.
- [docs/social.md](docs/social.md): stories, notifications, offline mode, LAN access.
- [docs/api.md](docs/api.md): the feed HTTP API.
- [docs/scheduling.md](docs/scheduling.md): how to keep the feed full.
- [CHANGELOG.md](CHANGELOG.md), [SECURITY.md](SECURITY.md), [LICENSE](LICENSE) (Apache 2.0).

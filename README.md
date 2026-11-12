# GitTok

A personal TikTok-style feed of cards about your own codebases. GitTok reads the git history of your repos. Claude Code writes the cards. You scroll them on your phone or in a browser.

## Install (no clone)

You need `uv`, `git`, and Claude Code. uv downloads Python for you.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh          # if you do not have uv yet
uv tool install ./gittok-0.1.0-py3-none-any.whl     # from a wheel file
gittok install                                       # dry run: shows what it will set up
gittok install --apply                               # MCP server for Claude Code, skills, agents, LaunchAgent (macOS)
```

Then download the tree-sitter grammars once with `gittok structure --prefetch`.

One extra is optional, because it is large (torch and mlx, about 1 GB, plus models later):

```bash
uv tool install 'gittok[images] @ ./gittok-0.1.0-py3-none-any.whl'   # mflux art for illustrations, comics, avatars (Apple silicon only)
```

Your files live in `~/.gittok/` (set `GITTOK_HOME` to change it): `local/` for repos and profiles, `data/` for the database and images. Upgrade with `uv tool upgrade gittok`. Remove with `uv tool uninstall gittok`.

A git URL install (`uv tool install git+<url>`) does not work yet, because the web build is not committed.

## Build the wheel

From a clone, with Node 22 and uv:

```bash
npm --prefix web install
npm --prefix web run build      # the web build goes into the wheel
uv build --wheel                # writes dist/gittok-<version>-py3-none-any.whl
```

The build stops with an error if `web/build/index.html` is missing. The wheel bundles `config/`, the web build, and the Claude Code skills and agents. One wheel works on every platform.

## Develop

Build, test, and architecture notes are in [AGENTS.md](AGENTS.md). The product spec is [SPEC.md](SPEC.md). Install details, undo steps, and the optional renderers are in [docs/install.md](docs/install.md).

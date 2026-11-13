# Install

GitTok is a Python tool that you install once. It then works in a **GitTok directory**: one folder that holds everything GitTok needs and everything it makes.

## What you need

- **macOS.** Other platforms are not supported yet.
- **[uv](https://docs.astral.sh/uv/).** uv downloads Python 3.13 for you.
- **git.**
- **A coding agent.** GitTok is made for and tested with [Claude Code](https://claude.com/claude-code), and these docs use it. The agent writes the posts, and you manage GitTok by asking it. GitTok does not call a model API itself.

## Install GitTok

```bash
uv tool install 'gittok[images]'
```

The `images` extra adds [mflux](https://github.com/filipstrand/mflux), which draws the illustration and comic posts. It works on Apple silicon only, and it is a large download: about 1 GB now, and a model later (see [Advanced setup](../install.md#illustration-renderer-mflux)). On a Mac that is not Apple silicon, the extra adds nothing. Without it, all the other posts still work.

## Make a GitTok directory

```bash
mkdir ~/gittok
cd ~/gittok
gittok init .
```

`gittok init` writes:

- `AGENTS.md`: tells your coding agent what this directory is and how to work with GitTok.
- For Claude Code: `.mcp.json` (it starts the GitTok server when a session starts here), `.claude/` (the skills and agents that make posts and manage GitTok, and the session hooks that keep the feed full), and a `CLAUDE.md` that points to `AGENTS.md`.
- `local/repos.yaml`: your repo list, empty for now.

[Your GitTok directory](../guide/files.md) shows everything that goes in it later.

## Start Claude Code in it

```bash
claude
```

The first time, Claude Code asks you to approve the MCP server `gittok`. Approve it.

!!! info "GitTok runs only while a session is open"
    The Claude Code session starts the GitTok server, and the server serves the feed. When the session ends, the feed stops. Nothing is installed outside the directory, and nothing starts by itself.

At the start of each session, Claude gives you the address of the feed. You will read it on your phone: [your first feed](first-feed.md) shows how to pair it.

## Optional downloads

Claude offers these when they are useful. You can also run them yourself:

| What | Command | Size |
|---|---|---|
| Meme templates and fonts | `gittok memes --prefetch` | about 20 MB |
| Grammars, so GitTok reads code structure better | `gittok structure --prefetch` | about 26 MB |

Next: [your first feed](first-feed.md).

# Install

GitTok is a Python tool that you install once. It then works in a **GitTok directory**: one folder that holds everything GitTok needs and everything it makes.

## What you need

- **macOS.** Other platforms are not supported yet.
- **[uv](https://docs.astral.sh/uv/).** uv downloads Python 3.13 for you.
- **git.**
- **A coding agent.** Use [Claude Code](https://claude.com/claude-code) or [Codex](https://developers.openai.com/codex/). These docs use Claude in examples; the same requests work in Codex. The agent writes the posts, and you manage GitTok by asking it. GitTok does not call a model API itself.

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
- For Codex: `.codex/config.toml` (the same MCP server), `.codex/hooks.json` (startup hints), and `.agents/skills/` (adapters for the shared workflows).
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

## Use Codex instead

Run `codex` in your GitTok directory. Trust the project configuration so Codex
loads `.codex/config.toml`, then review and trust the startup hooks with `/hooks`.
If the tools are missing, check `/mcp`. Ask Codex to add your repo; it profiles it
and makes the first cards using the same workflows as Claude Code.

The explicit skills are `$gittok-steer`, `$gittok-profile-repo <repo>` and
`$gittok-generate`. Generation delegates scouts and writers to Codex subagents,
so use a client with subagent support. It inherits your Codex model; Claude model
names in the shared guidance do not select Codex models.

Existing GitTok directories get Codex support with `gittok update`. Restart the
session after updating or changing MCP/server settings. Startup hints also have
an instruction fallback when hooks are unavailable. Background feed watching
uses the Codex client's process tools; clients that do not wake on completion
check the feed on the next user turn. You can always ask for more cards.

## Optional downloads

Claude offers these when they are useful. You can also run them yourself:

| What | Command | Size |
|---|---|---|
| Meme templates and fonts | `gittok memes --prefetch` | about 20 MB |
| Grammars, so GitTok reads code structure better | `gittok structure --prefetch` | about 26 MB |

Next: [your first feed](first-feed.md).

# Install

GitTok is a Python tool that you install once. It then works in a **GitTok directory**: one folder that holds everything GitTok needs and everything it makes.

## What you need

- **macOS.** Other platforms are not supported yet.
- **[uv](https://docs.astral.sh/uv/).** GitTok needs Python 3.13. With `--python 3.13`, uv downloads it for you if you do not have it.
- **git.**
- **A coding agent.** Use [Claude Code](https://claude.com/claude-code) or [Codex](https://developers.openai.com/codex/). These docs use Claude in examples; the same requests work in Codex. The agent writes the posts, and you manage GitTok by asking it. GitTok does not call a model API itself.

## Install GitTok

```bash
uv tool install --python 3.13 gittok    # Claude Code: see "Better images" below
```

!!! tip "Better images in Claude Code"
    Claude Code has no image tool. Without extras, Claude draws the illustration and comic posts as simple flat SVG pictures. On Apple silicon, install with the `images` extra for real illustrations:

    ```bash
    uv tool install --python 3.13 'gittok[images]'
    ```

    It adds [mflux](https://github.com/filipstrand/mflux), about 1 GB, plus a 6 GB model that GitTok downloads by itself in the background (see [Advanced setup](../install.md#illustration-renderer-mflux)). If GitTok is already installed, add `--force`, then start a new session. On a Mac that is not Apple silicon, the extra adds nothing. Codex uses its own image tool by default. To use mflux in Codex instead, install with the extra and ask Codex: "Use local image generation." Or set it yourself in `local/settings.yaml` of your GitTok directory:

    ```yaml
    render:
      image_backend: local
    ```

Default meme templates and fonts are included and work offline. Every kind of post works with or without the extra.

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
| Additional custom meme templates | `gittok memes --prefetch` | varies; defaults are included |
| Grammars, so GitTok reads code structure better | `gittok structure --prefetch` | about 26 MB |
| The illustration model, now (GitTok downloads it by itself otherwise) | `gittok images --download` | about 6 GB |

Next: [your first feed](first-feed.md).

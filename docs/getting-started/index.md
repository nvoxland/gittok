# Get started

GitTok is a Python tool that you install once. It then works in a **GitTok directory**: one folder that holds everything GitTok needs and everything it makes. This page takes you from the install to your first posts on your phone.

## What you need

- **macOS.** Other platforms are not supported yet.
- **[uv](https://docs.astral.sh/uv/).** GitTok needs Python 3.13. With `--python 3.13`, uv downloads it for you if you do not have it.
- **git.**
- **A coding agent.** Use [Claude Code](https://claude.com/claude-code) or [Codex](https://developers.openai.com/codex/). These docs say "your agent" for either one; the same requests work in both. The agent writes the posts, and you manage GitTok by asking it. GitTok does not call a model API itself.

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
- For Codex: `.codex/config.toml` (the same MCP server), `.codex/hooks.json` (startup hints), `.agents/skills/` and `.agents/workers/` (the same skills and workers as Claude Code gets, made from one source), and `.agents/GITTOK.md` (notes for Codex sessions).
- `local/repos.yaml`: your repo list, empty for now.

[Your GitTok directory](../guide/files.md) shows everything that goes in it later.

## Start your agent

Start your coding agent in the GitTok directory. From then on, you manage GitTok by asking your agent in plain words. Claude Code asks for your permission before it runs a GitTok tool; Codex asks before the tools that pair a device, remove a repo or turn phone access on or off.

=== "Claude Code"

    ```bash
    claude
    ```

    The first time, Claude Code asks you to approve the MCP server `gittok`. Approve it. If the GitTok tools are missing later, check `/mcp`.

=== "Codex"

    ```bash
    codex
    ```

    Trust the project configuration, so that Codex loads `.codex/config.toml`. Then review and trust the startup hooks with `/hooks`. If the GitTok tools are missing, check `/mcp`.

    The skills are `$gittok-steer`, `$gittok-profile-repo <repo>` and `$gittok-generate`. Generation gives scouts and writers to Codex subagents, so use a client that supports subagents. They use your Codex session's model; to name smaller models for them, see `agent.models` in [Configuration](../config.md).

    Without hooks, the startup hints come from the instructions instead. Background feed watching uses the process tools of the Codex client; a client that does not wake when a process ends checks the feed on your next message.

Both agents use the same MCP server and the same workflows. Ask yours to add a repo; it profiles the repo and makes the first posts. You can always ask for more posts.

!!! info "GitTok runs only while a session is open"
    The agent session starts the GitTok server, and the server serves the feed. When the session ends, the feed stops. Nothing is installed outside the directory, and nothing starts by itself.

A GitTok directory made by an older version gets the files for both agents with `gittok update` (or ask your agent to update it). Start a new session after an update, or after you change an MCP or server setting.

## Add a repo

Give your agent a directory or a git URL:

> Add the repo at ~/src/myapp to GitTok.

> Add https://example.com/org/storefront.git to GitTok.

GitTok reads a directory in place and never changes it. It clones a URL into `repos/` of the GitTok directory, and fetches it before each analysis.

Then your agent does two things without asking:

1. **It profiles the repo.** It reads the repo and writes the rules that find the code worth teaching. This takes a few minutes and some of your model quota. The agent may ask your permission to run a code analyzer, and it may offer to download grammars.
2. **It makes the first posts.** A run of writers each take a small packet of leads, research them in your repo, and submit posts. GitTok checks each post against git before it stores it.

Your agent also gives the repo a **mascot**: a small character that the illustration and comic posts draw. It tells you which one it picked. Say "make the mascot a fox" to change it.

## Pair your phone

GitTok is made for your phone. Your phone must be on the same network as your computer, and each device pairs once.

1. **Open the feed address on your phone.** At the start of each session, your agent tells you where the feed is, for example *"The feed is at http://192.168.1.57:7313 on your phone"*. If you missed it, ask: "What is the feed address?"
2. **Tap Pair with a code.** A phone that is not paired yet gets this page instead of the feed. It shows a short code, such as `X6J2-QG`.
3. **Tell your agent the code:** "pair code X6J2-QG". A code lasts 10 minutes and works once.

A few seconds later, the feed opens on the phone. That's all: there is no other step to start pairing.

!!! tip "Add it to the home screen"
    In Safari, tap **Share**, then **Add to Home Screen**. The app opens full screen. It keeps its own storage, apart from the browser, so pair it once more inside the app: tap **Pair with a code** and tell your agent the new code.

The feed goes over plain HTTP on your network. Read [Privacy and your network](../guide/privacy.md) before you use it on a shared network. To turn phone access off, say "turn off phone access".

## Scroll your feed

- **Swipe up** for the next post.
- **Swipe sideways** to go deeper: the explanation, the real code, the real diff.
- **👍** when you liked a post, **👎** for "show less like this". The thumbs shape the posts that get made next.
- **Save** a post to find it again.
- Answer a **quiz**. A wrong answer comes back later.
- Read the **comments**: the cast argues about every post.

The feed is served while the agent session is open. New posts come by themselves while it stays open ([Keep the feed full](../guide/keeping-full.md)).

## What next

- [Steer the feed](../guide/steering.md): "less memes", "more of the sync engine this week".
- [How the feed learns](../guide/learning.md) from what you do.
- [Add more repos](../guide/repos.md), and put them in groups.

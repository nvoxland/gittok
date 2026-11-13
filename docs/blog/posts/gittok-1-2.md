---
date: 2026-11-13
authors:
  - nvoxland
categories:
  - Releases
---

# GitTok 1.2: Codex, and illustrations that set themselves up

GitTok 1.2 works with Codex as well as Claude Code, and the illustrated posts now set themselves up: no 25 GB download, no setup step, no waiting.

<!-- more -->

```bash
uv tool upgrade gittok
```

Then say "update this GitTok directory" in a session there (or run `gittok update`). That also adds the Codex files to an existing GitTok directory.

## Use Codex

Run `codex` in your GitTok directory instead of `claude`. Trust the project configuration, review the startup hooks with `/hooks`, and ask Codex to add a repo, just as you would ask Claude. Both agents use the same MCP server and the same workflows: profiling a repo, making posts, steering the feed. Generation hands each packet of posts to a Codex subagent.

In Codex, the few tools that change who can see your feed or what it holds (`pair_device`, `remove_repo`, `set_lan`) always ask you first. Text in a repo that GitTok analyzes can never pair a device or remove a repo on its own.

See [Install: use Codex instead](../../getting-started/install.md#use-codex-instead).

## Illustrations that set themselves up

Comics and mascot scenes need an image model. In 1.1, setting it up was a manual step: download 25 GB of weights and shrink them on your Mac with `mflux-save`, which also needed a lot of memory.

Now GitTok downloads a model that is already shrunk to 4 bits: about 6 GB, in the background, into your GitTok directory. The feed server starts it by itself when the image renderer is installed. A stopped download picks up where it left off. Your first posts do not wait for it: illustrated posts start once the model is there, and a new repo gets its mascot right away.

To see where it is, or to download it now with progress:

```bash
gittok images
gittok images --download
```

More in [Advanced setup](../../install.md#illustration-renderer-mflux).

## Smaller fixes

- **Faster images in a row.** The model stays loaded for a short batch of images (cards, comic panels, avatars) instead of loading for each one. The first image of a batch also gets time to load the model, so a slow first load no longer fails it.
- **Default memes ship with GitTok.** The meme templates and fonts are part of the install. `gittok memes --prefetch` only fetches extra templates you add.
- **The feed address when phone access is off.** Claude now gives you this computer's address in that case, the only place the feed opens.
- **The install command names Python 3.13**, so it works on a Mac whose default Python is older: `uv tool install --python 3.13 'gittok[images]'`.

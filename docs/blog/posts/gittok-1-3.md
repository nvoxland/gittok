---
date: 2026-11-16
authors:
  - nvoxland
categories:
  - Releases
---

# GitTok 1.3: illustrations without a model download

GitTok 1.3 can make comic and mascot posts with no image model on your Mac. Codex draws them with its own image tool. Claude Code draws them as simple vector pictures. The 6 GB local model is now optional.

<!-- more -->

```bash
uv tool upgrade gittok
```

Then say "update this GitTok directory" in a session there (or run `gittok update`), and start a new session. The update adds the new `gittok-illustrator` agent, and only a new session loads it.

## Images from your coding agent

Until now, comic and mascot posts needed mflux and a 6 GB model, on Apple silicon only. Without them, a repo got no mascot and no comics.

Now the coding agent can make these images. After the writers submit their posts, GitTok gives the scene of each panel to the agent:

- **Codex** makes each image with its own image tool.
- **Claude Code** has no image tool. So Claude starts a small `gittok-illustrator` subagent for each post. It draws each panel as an SVG picture, and GitTok turns it into an image. The pictures are flat and simple, but they need no download and they work on any Mac.

The new setting `render.image_backend` chooses. With `auto` (the default), Codex uses its image tool, and Claude uses mflux when it is installed, else SVG. To choose for yourself, ask your agent ("use agent images", "use local image generation"), or see [Agent images](../../install.md#agent-images).

Because the agent can always draw, **every new repo now gets a mascot**, also without mflux.

## The images extra is optional

The install command no longer includes the `images` extra:

```bash
uv tool install --python 3.13 gittok
```

If you use Claude Code on Apple silicon and want real illustrations instead of SVG drawings, install the extra: `uv tool install --force --python 3.13 'gittok[images]'`. If you installed with the extra before, the upgrade keeps it. In Codex, the extra is only for when you want local images instead of Codex's image tool. See [Get started](../../getting-started/index.md#install-gittok).

## Codex keeps the feed full

In Codex, the feed watch can now queue a refill prompt for your Codex thread when the feed runs low, also while the session is idle. A thread gets one prompt at a time, so a busy feed does not send duplicate prompts. See [Keeping the feed full: Codex sessions](../../scheduling.md#codex-sessions).

## Smaller fixes

- **Pairing tells you why.** When the server refuses a pairing code (for example, too many devices wait for one), the phone shows that reason instead of "Try again".
- **Back after pairing.** When the browser shows an old pairing page again with Back, it asks the server for that page again, so a device that is now paired goes to the feed.
- **No lost posts.** A post whose images failed, or whose session ended before the images were made, gets its images in the next run.
- **Clean-up.** Image files that an agent staged and never submitted are deleted after a day.

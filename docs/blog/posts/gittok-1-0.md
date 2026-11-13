---
date: 2026-11-12
authors:
  - nvoxland
categories:
  - Releases
---

# GitTok 1.0: doomscrolling your code

GitTok 1.0 is out. It turns your git repos into a TikTok-style feed of short posts about your own code: explainers, code cards, quizzes, memes, comics and group chats, with a cast of regulars arguing in the comments.

<!-- more -->

```bash
uv tool install 'gittok[images]'
mkdir ~/gittok && cd ~/gittok
gittok init .
claude
```

Then ask Claude: "Add the repo at ~/src/myapp to GitTok." The [install guide](../../getting-started/install.md) has the details.

## What is in 1.0

**A feed about your repos.** Swipe up for the next post, sideways to go deeper: the explanation, the real code, the real diff. Stories, notifications and replies, on this computer or on your phone.

**Every post is checked against git.** A Claude Code session writes the posts through the GitTok MCP server. The server checks each cited commit, file, line, name and number before it stores a post.

**You manage it by asking.** Add a repo by path or by URL, remove one, pair a phone, steer the feed: Claude does it with GitTok's tools. Each step also has a command.

**Repo profiles.** When you add a repo, Claude reads it and writes rules that find the code worth teaching. GitTok runs the rules and scores them. Then Claude makes the first posts, without you asking.

**One learner.** What you read, like, 👎 and skip decides both the order of the feed and what gets made next. It learns from what each post is: repo, directory, file, language, format, tone, persona, the kind of knowledge it gives (what, how, why, who, risk) and how well you know the code. A 👎 ("show less like this") counts heavily, and the posts ahead are ranked again a moment later. Or just say it: "less memes, more of the sync engine." See [how the feed learns](../../guide/learning.md).

**The feed refills by itself** while a session is open in your GitTok directory. Reach the end, and new posts are made at once.

**Drawn on your machine.** The app draws code, charts and diagrams. GitTok draws memes itself, from templates it downloads once: no Docker, no meme server, and no post text leaves the computer. Illustration and comic posts are optional, with mflux on Apple silicon. GitTok ships no mascot: Claude picks one that fits each repo.

**Every default can be changed** without a clone. Each shipped config file has a file of the same name in `local/` that is merged over it. Ask Claude, and it edits the file and checks it. See [Configuration](../../config.md).

**Made for your phone.** The feed is served to your local network over plain HTTP, and each device pairs once with a QR code or a short code. Say "turn off phone access" to serve this computer only. Read [Privacy and your network](../../guide/privacy.md) first.

**Safe with your repos.** GitTok never writes to a repo you added by path. Git runs with hooks, external diff programs and the `ext::` transport turned off, so a repo's config cannot start a program. Removing a repo removes all that GitTok made for it, and never touches a directory of your own.

**One directory.** `gittok init` makes a GitTok directory that holds the MCP entry, the skills and agents, the session hooks, and all your files. Nothing is installed outside it, and nothing starts by itself. `gittok update` refreshes it after an upgrade.

1.0 supports macOS.

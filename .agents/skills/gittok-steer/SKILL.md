---
description: Manage and steer GitTok by request. Use when the user asks to add a repo
  or remove a repo ("add the repo at ~/src/myapp", "add https://example.com/org/repo.git",
  "remove the storefront repo"), to set GitTok up, to pair a phone (pairing by code)
  or get the feed address, to turn phone access off or on, to give a repo a mascot,
  to change a default or a setting ("also scan .proto files", "support Kotlin", "never
  show keys that look like ACME-...", "change the reward for a like"), or to change
  the feed or explain it ("less memes", "no more roast cards", "more of the sync engine
  this week", "focus on billing", "what have you learned about me", "why am I seeing
  so many X", "reset my feed").
name: gittok-steer
---

# gittok-steer for Codex

Read `.agents/GITTOK.md` from this GitTok directory first, then read
`.claude/skills/gittok-steer/SKILL.md` and follow its workflow with those runtime
adaptations. Paths are relative to the GitTok directory, not this skill folder.
The workflow and its safety rules are shared with Claude Code; do not copy them
or start a Claude process. Ignore the shared file's Claude model frontmatter.

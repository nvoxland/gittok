---
description: Generate new GitTok feed cards from the configured repos. Use when the
  user asks to generate, make, or refresh GitTok cards or the feed. Optional args
  - repo name and card count, e.g. "storefront 10".
name: gittok-generate
---

# gittok-generate for Codex

Read `.agents/GITTOK.md` from this GitTok directory first, then read
`.claude/skills/gittok-generate/SKILL.md` and follow its workflow with those runtime
adaptations. Paths are relative to the GitTok directory, not this skill folder.
The workflow and its safety rules are shared with Claude Code; do not copy them
or start a Claude process. Ignore the shared file's Claude model frontmatter.

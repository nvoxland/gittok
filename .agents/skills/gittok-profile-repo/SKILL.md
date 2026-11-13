---
description: Write or revise the GitTok profile of one repo (rules that find the code
  worth teaching). For a repo with no profile, start at once and do not ask - right
  after add_repo, when the SessionStart hint says a repo has no profile, or from step
  0 of gittok-generate. For a repo that has a profile, revise it only when the user
  says "profile <repo>" or agrees to an offer (its manifests changed, or its rules
  do badly). Arg - the repo name.
name: gittok-profile-repo
---

# gittok-profile-repo for Codex

Read `.agents/GITTOK.md` from this GitTok directory first, then read
`.claude/skills/gittok-profile-repo/SKILL.md` and follow its workflow with those runtime
adaptations. Paths are relative to the GitTok directory, not this skill folder.
The workflow and its safety rules are shared with Claude Code; do not copy them
or start a Claude process. Ignore the shared file's Claude model frontmatter.

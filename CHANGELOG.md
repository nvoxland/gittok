# Changelog

## 1.0.0 (unreleased)

First public release.

- A feed of cards about your own git repos: vertical scroll, horizontal depth panels, stories, notifications, replies.
- Cards are written by a Claude Code session through the GitTok MCP server. The server checks each card against git before it stores it.
- You manage GitTok by asking Claude in a Claude Code session: add a repo by local path or by remote URL, remove a repo, pair a phone, steer the feed. MCP tools do the work (`add_repo`, `remove_repo`, `pairing_link`, `set_lan`, `add_rule` and others). Each step also has a command (`gittok repos add`, `gittok repos remove`, ...).
- GitTok clones a repo added by URL into its own directory and fetches it before analysis (at most once per `analysis.fetch_min_interval_s`).
- The `add_repo` tool accepts any git repo root; the permission prompt of Claude Code is the consent. `repos.allowed_roots` is an optional limit.
- Repo profiles: per-repo rules, kept as data, that find the code worth teaching.
- Learning: the feed order adapts to what you read, like, and skip. Rules steer it in plain words through the `gittok-steer` skill.
- The client draws code, charts, diagrams and template formats. Meme cards (memegen) and illustration cards (mflux) are optional and need their renderer.
- The feed is served to the local network by default (`server.lan: true`), over plain HTTP, because it is made for a phone. Each device pairs once: ask Claude to pair your phone, and scan the QR code on the pairing page (`/pairing`, this computer only). `server.lan: false` or `--no-lan` serves this computer only. The MCP server speaks stdio only; the feed server has no MCP endpoint. A request that comes through a reverse proxy is never treated as local.
- Git runs with hooks, external diff and textconv programs, fsmonitor, and the `ext::` transport turned off, so a repo's config cannot start a program.
- `uv tool install gittok`, then `gittok init <dir>`: it makes a GitTok directory that holds the MCP entry, the skills and agents, the session hooks, an `AGENTS.md`, and all your files. Start Claude Code in that directory. GitTok runs only while a session is open there: the session starts the MCP server and the feed server, and both stop with it. Nothing is installed outside the directory.
- `gittok update` rewrites the files of a GitTok directory after `uv tool upgrade gittok`, and keeps a file that you edited as `<name>.bak`. `gittok --version` prints the version.
- Supported platform: macOS.

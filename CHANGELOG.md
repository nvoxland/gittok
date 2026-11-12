# Changelog

## 1.0.0 (unreleased)

First public release.

- A feed of cards about your own git repos: vertical scroll, horizontal depth panels, stories, notifications, replies.
- Cards are written by a Claude Code session through the GitTok MCP server. The server checks each card against git before it stores it.
- Add a repo by local path or by remote URL (`gittok repos add`). GitTok clones a remote into its own directory and fetches it before analysis (at most once per `analysis.fetch_min_interval_s`).
- Repo profiles: per-repo rules, kept as data, that find the code worth teaching.
- Learning: the feed order adapts to what you read, like, and skip. Rules steer it in plain words through the `gittok-steer` skill.
- The client draws code, charts, diagrams and template formats. Meme cards (memegen) and illustration cards (mflux) are optional and need their renderer.
- The feed is served on `127.0.0.1` by default. LAN access is opt-in (`server.lan: true` or `--lan`) and needs a pairing link on each device. A request that comes through a reverse proxy is never treated as local.
- Git runs with hooks, external diff and textconv programs, fsmonitor, and the `ext::` transport turned off, so a repo's config cannot start a program.
- `gittok install` sets up the MCP entry, the skills and agents, and a LaunchAgent. `gittok --version` prints the version.
- Supported platform: macOS.

# Security

GitTok runs on your own machine. It reads the git history of the repos you add, and it serves a feed on a local port.

## Reporting a problem

Please report a security problem in private: use "Report a vulnerability" on the repository's Security tab (a GitHub private security advisory). Do not open a public issue for it. Include the steps to reproduce it and the version (`gittok --version`).

## What GitTok protects

- **Your repos are read-only.** GitTok reads git objects. It never writes to a working tree, an index, or a local branch. The one exception is `fetch: true` on a repo, which updates remote-tracking refs only.
- **Git cannot run programs from a repo's config.** GitTok starts git with external diff, textconv, hooks, and bare-repository discovery turned off.
- **The feed is local by default.** The server listens on `127.0.0.1`. It answers only requests whose `Host` header is a local name, so another web site cannot read it through DNS rebinding.
- **LAN access is opt-in and needs pairing.** With `server.lan: true` (or `--lan`), another device must first open the pairing link, which carries a random token. The MCP endpoint over HTTP stays loopback-only.
- **Secrets are redacted.** Text that leaves the server (cards, tool results, excerpts) passes a secret detector first (`config/secrets.yaml`).
- **Text from repos is data.** Agents are told to treat commit messages, code, and comments as data, never as instructions. Writer and scout agents get a narrow tool list with no config-editing tools.

## What it does not protect

- Anyone who can reach the port **and** has the pairing token can read your feed, which contains code excerpts.
- The feed is served over plain HTTP. On a network you do not trust, keep LAN access off.
- Card text is written by an AI model from your code. Check a claim against the cited commit before you rely on it.

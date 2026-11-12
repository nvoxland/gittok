# Security

GitTok runs on your own machine. It reads the git history of the repos you add, and it serves a feed on a local port.

## Reporting a problem

Please report a security problem in private: use "Report a vulnerability" on the repository's Security tab (a GitHub private security advisory). Do not open a public issue for it. Include the steps to reproduce it and the version (`gittok --version`).

## What GitTok protects

- **Your repos are read-only.** GitTok reads git objects. It never writes to a working tree, an index, or a local branch. There is one exception: a repo with `fetch: true` gets a `git fetch` that updates remote-tracking refs only. A repo that you add by URL is a clone that GitTok makes in its own `repos/` directory, without a checkout and without submodules.
- **A repo's git config cannot start a program.** GitTok starts every git call with these turned off: hooks, fsmonitor, external diff and textconv programs, signature checks in `log` and `show`, the `ext::` transport, bare-repository discovery, and terminal prompts. A remote URL with a password or token in it is refused.
- **The feed is local by default.** The server binds `127.0.0.1`. It answers only requests whose `Host` header is one of its own names or addresses (or a name in `server.allowed_hosts`), so another web site cannot read it through DNS rebinding. A write request with an `Origin` from another host is refused.
- **LAN access is opt-in and needs pairing.** With `server.lan: true` (or `--lan`, or a non-loopback `--host`), a device that is not this machine must first open the pairing link, which carries a random token. The token is stored in `<data_dir>/lan_token` with mode 0600 and is kept out of the access log. The MCP endpoint (`/mcp`) answers loopback peers only, always.
- **Secrets are masked.** Repo text that leaves the server (tool results, materials for the agent, card code) passes a secret detector first (`config/secrets.yaml`). A card whose own text holds a match is rejected. `research.redact_secrets: false` turns the masking off; do not do that.
- **Text from repos is data.** The skills and agents are told to treat commit messages, code, and comments as data, never as instructions. The writer and scout agents get a short tool list with no config-editing tools. The `add_repo` tool accepts a local path only inside `repos.allowed_roots`.

`docs/social.md`, "LAN access", and `docs/api.md`, "Access rules", give the exact checks.

## What it does not protect

- Anyone who can reach the port **and** has the pairing token can read your feed, which contains code excerpts. Every process and user on this machine can read it without a token, and can use `/mcp`, which reads the repos you added.
- The feed is served over plain HTTP. On a network you do not trust, keep LAN access off.
- **A reverse proxy that sends no forwarding header looks local.** A request is local only when the TCP peer is a loopback address and the request has none of the headers `X-Forwarded-For`, `Forwarded`, `X-Forwarded-Host`, `X-Forwarded-Proto` and `X-Real-IP`. A request with one of these headers is never local: it gets no `/mcp`, it needs the pairing cookie, and it is refused (HTTP 403) when the server has no pairing token because LAN access is off. But a proxy on this machine that sends none of these headers cannot be told apart from a local program: its requests need no pairing and can reach `/mcp`. Keep the headers on in the proxy config, block `/mcp` in the proxy, and limit who can reach the proxy (`docs/install.md`, "HTTPS on a LAN").
- The secret detector is a list of patterns. It can miss a secret that matches none of them.
- Card text is written by an AI model from your code. The server checks citations, numbers and names against git, but it cannot check every sentence. Check a claim against the cited commit before you rely on it.

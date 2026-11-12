# Security

GitTok runs on your own machine. It reads the git history of the repos you add, and it serves a feed on a local port.

## Reporting a problem

Please report a security problem in private: use "Report a vulnerability" on the repository's Security tab (a GitHub private security advisory). Do not open a public issue for it. Include the steps to reproduce it and the version (`gittok --version`).

## What GitTok protects

- **Your repos are read-only.** GitTok reads git objects. It never writes to a working tree, an index, or a local branch. There is one exception: a repo with `fetch: true` gets a `git fetch` that updates remote-tracking refs only. A repo that you add by URL is a clone that GitTok makes in its own `repos/` directory, without a checkout and without submodules.
- **A repo's git config cannot start a program.** GitTok starts every git call with these turned off: hooks, fsmonitor, external diff and textconv programs, signature checks in `log` and `show`, the `ext::` transport, bare-repository discovery, and terminal prompts. A remote URL with a password or token in it is refused.
- **The feed is served to your local network, and a device must pair first.** GitTok is made for a phone, so by default (`server.lan: true`) the server binds all interfaces. A device that is not this machine gets nothing until it opens the pairing link or scans the pairing QR code, which carry a random token. The token is stored in `<data_dir>/lan_token` with mode 0600 and is kept out of the access log. The page that shows the QR code (`/pairing`) answers this machine only, always, and never a request that came through a proxy.
- **The MCP server is not on the network.** It speaks stdio only, to the agent session that started it. The feed server has no MCP endpoint.
- **Nothing is installed outside the GitTok directory, and nothing starts by itself.** `gittok init <dir>` writes only inside the directory you name. The MCP server and the feed server run only while an agent session is open in that directory.
- **You can turn LAN serving off.** Ask Claude to turn off phone access, or set `server.lan: false` in `local/settings.yaml`, or start the server with `--no-lan`. The server then binds `127.0.0.1` and has no pairing token.
- **Other web sites cannot read the feed.** The server answers only requests whose `Host` header is one of its own names or addresses (or a name in `server.allowed_hosts`), so another web site cannot read it through DNS rebinding. A write request with an `Origin` from another host is refused.
- **Secrets are masked.** Repo text that leaves the server (tool results, materials for the agent, card code) passes a secret detector first (`config/secrets.yaml`). A card whose own text holds a match is rejected. `research.redact_secrets: false` turns the masking off; do not do that.
- **Text from repos is data.** The skills and agents are told to treat commit messages, code, and comments as data, never as instructions. The writer and scout agents get a short tool list with no config-editing tools, and the skills that generate cards and profile repos are told never to call one. The config tools (`add_repo`, `remove_repo`, `set_lan`, `pairing_link` and the others) are for requests that you make in the conversation.
- **Adding a repo needs your consent.** The `add_repo` tool accepts the root of any git repo on this machine: it must have its own `.git`, be the top directory of the checkout, have a commit, and not be inside a repo that is already added. Claude Code asks for your permission before it calls the tool; that prompt is the consent. To limit the tool to some directories, set `repos.allowed_roots`. The `remove_repo` tool deletes a directory only when it is a clone that GitTok made itself.

`docs/social.md`, "LAN access", and `docs/api.md`, "Access rules", give the exact checks.

## What it does not protect

- Anyone who can reach the port **and** has the pairing token can read your feed, which contains code excerpts. Every process and user on this machine can read it without a token and can open the pairing page.
- **The feed is served over plain HTTP, not HTTPS.** Someone who can watch traffic on your network could read the pairing token and the cards. Use GitTok on a network you trust, such as your home network. On shared or public Wi-Fi, turn LAN serving off. `docs/install.md`, "HTTPS on a LAN", has an optional recipe.
- A program that Claude Code runs with your permission can do what you can do. If you allow the GitTok tools without a prompt, a prompt injection that gets past the rules above could add a repo, remove one from the list, or ask for the pairing link.
- **A reverse proxy that sends no forwarding header looks local.** A request is local only when the TCP peer is a loopback address and the request has none of the headers `X-Forwarded-For`, `Forwarded`, `X-Forwarded-Host`, `X-Forwarded-Proto` and `X-Real-IP`. A request with one of these headers is never local: it gets no pairing page, it needs the pairing cookie, and it is refused (HTTP 403) when the server has no pairing token because you turned LAN serving off. But a proxy on this machine that sends none of these headers cannot be told apart from a local program: its requests need no pairing and can reach the pairing page. Keep the headers on in the proxy config, block `/pairing` in the proxy, and limit who can reach the proxy (`docs/install.md`, "HTTPS on a LAN").
- The secret detector is a list of patterns. It can miss a secret that matches none of them.
- Card text is written by an AI model from your code. The server checks citations, numbers and names against git, but it cannot check every sentence. Check a claim against the cited commit before you rely on it.

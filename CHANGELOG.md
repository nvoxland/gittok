# Changelog

## Unreleased

- `local/guidance.md`: your own words for the card writers (tone, style, what to explain, what to avoid). It is added to the end of every `get_guidance` reply. Ask Claude ("keep hooks short", "no pop-culture jokes") and it edits the file. See docs/config.md, "Writing guidance".

Fixes in how the feed learns (docs/learning.md):

- One short look after a long read no longer makes the card a skip. A window is a skip only when every visit was a skip, and an answer or an opened panel always counts.
- A beat card's watch time is no longer counted twice: each dwell sends the time of its own visit.
- A 👎 that you take back is unlearned, and its story can be told again.
- The familiarity of an impression is what you knew when the card was ranked, not after the impression was counted.
- An event at the same moment as the next impression counts in one window only.
- `gittok relearn` uses the cards' current features (after `gittok refeature`), keeps a reset, and keeps what a removed repo taught.
- Event ids are never used again after garbage collection, so no impression loses its reward.
- A meme template you disliked no longer goes before one you never saw.
- A learning pass reads only the new impressions.
- Quiz answers use the phone's clock, like the other events.
- `half_life_days` or a `prior_sd` of 0 is a config error, not a crash.
- Rejects of a lead count only inside the cooldown window.

## 1.0.0 (2026-11-12)

First public release.

- A feed of cards about your own git repos: vertical scroll, horizontal depth panels, stories, notifications, replies.
- Cards are written by a Claude Code session through the GitTok MCP server. The server checks each card against git before it stores it.
- You manage GitTok by asking Claude in a Claude Code session: add a repo by local path or by remote URL, remove a repo, pair a phone, steer the feed. MCP tools do the work (`add_repo`, `remove_repo`, `pairing_link`, `set_lan`, `add_rule` and others). Each step also has a command (`gittok repos add`, `gittok repos remove`, ...).
- Removing a repo also removes all that GitTok made for it: its cards with their images, its analysis, its profile, the rules on the repo, and a mascot of the repo that you defined. What the feed learned about your taste stays, and a directory of your own is never touched. `keep_data` (`gittok repos remove <name> --keep-data`) keeps the cards, the profile and the mascot. Garbage collection deletes the data of a repo that is no longer configured, and the feed never shows its cards.
- The agent answers questions about GitTok's state with MCP tools: `list_repos` (cards per repo), `feed_health` (backlog per repo), `recent_cards` (by repo), `recent_runs` and `status`.
- GitTok clones a repo added by URL into its own directory and fetches it before analysis (at most once per `analysis.fetch_min_interval_s`).
- The `add_repo` tool accepts any git repo root; the permission prompt of Claude Code is the consent. `repos.allowed_roots` is an optional limit.
- Repo profiles: per-repo rules, kept as data, that find the code worth teaching. The agent writes the profile by itself: right after a repo is added, and before it makes cards for a repo that has none. It then makes the first cards. For a repo that has a profile, it only offers a revision (the manifests changed, or several rules do badly).
- The feed refills by itself while a session is open in the GitTok directory. A reader who reaches the end of the feed gets new cards without the usual wait between two runs, and the end-of-feed card says whether cards are being made now.
- Every default can be changed without a clone. Each shipped config file has a file of the same name in `local/` that is merged over it: file sets, language patterns, tree-sitter queries, file types, secret patterns, claim phrases, meme templates, the starting mix, reward weights, settings. Maps merge key by key, lists add, and removal is explicit (`$remove`, `$replace`). Ask Claude for the change: it edits the local file, and the read-only tools `config_files`, `get_config` and `check_config` (`gittok config files|get|check`) show the values and validate the edit. `docs/config.md` has the rule and an example for each file.
- The shipped defaults cover the common languages: regex patterns for Go, Rust, Java, Ruby, Kotlin, C#, PHP and Swift next to Python, Clojure and TypeScript, a wider default file set, and wider file type tables.
- GitTok ships no mascot. When you add a repo, Claude picks a mascot that fits it, if the image renderer works. A repo with no mascot gets no mascot cards; nothing is rejected for it.
- Learning: one learner decides both what the feed shows and what gets made. It learns from what you read, like, 👎 and skip, and from what each card is: repo, dir, file, language, file kind, detector tag, story type, format, tone, persona, angle (what, how, why, who, risk: the kind of knowledge a card gives) and how well you know the code. A 👎 ("show less like this") counts heavily, whatever the reason, and the cards ahead are ranked again a moment later. It replaces the "Knew it" and "More" buttons. `gittok relearn` rebuilds the model from the rewards. Rules steer it in plain words through the `gittok-steer` skill.
- The client draws code, charts, diagrams and template formats. GitTok draws meme cards itself with Pillow, from memegen's templates that `gittok memes --prefetch` downloads once (no Docker, no meme server; no card text leaves the computer). Illustration cards (mflux) are optional and need their renderer.
- The pairing pages of a device match the app (light and dark), and the code page has a Copy button for what to tell Claude.
- The feed is served to the local network by default (`server.lan: true`), over plain HTTP, because it is made for a phone. Each device pairs once: ask Claude to pair your phone, and scan the QR code on the pairing page (`/pairing`, this computer only). Or tap "Pair with a code" on the device and tell Claude the code it shows (`pair_device`, `gittok pair <code>`): this works for an app on the home screen too. `server.lan: false` or `--no-lan` serves this computer only. The MCP server speaks stdio only; the feed server has no MCP endpoint. A request that comes through a reverse proxy is never treated as local.
- Git runs with hooks, external diff and textconv programs, fsmonitor, and the `ext::` transport turned off, so a repo's config cannot start a program.
- `uv tool install gittok`, then `gittok init <dir>`: it makes a GitTok directory that holds the MCP entry, the skills and agents, the session hooks, an `AGENTS.md`, and all your files. Start Claude Code in that directory. GitTok runs only while a session is open there: the session starts the MCP server and the feed server, and both stop with it. Nothing is installed outside the directory.
- `gittok update` rewrites the files of a GitTok directory after `uv tool upgrade gittok`, and keeps a file that you edited as `<name>.bak`. `gittok --version` prints the version.
- Supported platform: macOS.

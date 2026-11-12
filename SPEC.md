# GitTok — Spec

A personal, TikTok/Instagram-style feed for understanding the codebases you work in every day. A local server on your Mac generates cards from your repos and their git history, and you scroll them on your phone as an installed web app. The feed learns what you engage with, and you can ask the coding agent what it has learned and tell it how to adjust.


---

## 1. Goals

- Make understanding your own codebases (structure, behavior, history, people, change) feel like scrolling social media.
- Feel like a real social feed: varied formats, recurring characters, comments, humor, series — not blocks of text.
- Run entirely on a Mac plus existing **Claude (Pro/Max) or ChatGPT subscriptions**. No pay-per-use API keys.
- Learn the user's tastes from behavior, and keep that learning **transparent and steerable** through the agent.
- Support **multiple repos**, grouped into projects or standalone.

## 2. Non-goals (v1)

- Multi-user or hosted service. This is one person's tool on their own machine.
- Real-time generation per swipe. Cards are generated in batches.
- Short video (planned as a later milestone, see §17).
- Replacing documentation or code review.

---

## 3. Architecture

```
            ┌──────────────────────── Mac ────────────────────────┐
 repos ───► │ Git analysis ─► Brief builder ─► MCP get_brief ──►  │
            │                     ▲      Claude Code TUI + skill     │
            │                     │                 │ card specs  │
            │   weights + rules + coverage          ▼             │
            │                     │           Validator           │
            │                     │                 ▼             │
            │                     │   Renderers (memegen, mflux,  │
            │                     │   HTML templates, Shiki)      │
            │                     │                 ▼             │
            │   Ranker/Slotter ◄── SQLite ◄── cards + assets      │
            │         │              ▲                            │
            │      FastAPI ──────────┘ events                     │
            │         │                                           │
            │   MCP server + CLI ◄── submit_cards / steering tools│
            └─────────┼───────────────────────────────────────────┘
                      │ LAN (Tailscale later)
                   Phone (PWA)
```

## 4. Stack

| Concern | Choice |
|---|---|
| Language / tooling | Python 3.13, managed with **uv** |
| Server | **FastAPI** (serves feed API, static frontend, assets, event ingest) |
| Database | **SQLite** (single file; easy for the agent to inspect) |
| Git analysis | Shell out to `git` (log, blame, diff, shortlog, show). Add pygit2 only if needed |
| Content agent | An interactive **Claude Code** session (or Codex) running the `gittok-generate` skill against the GitTok MCP server. No `claude -p`: headless use is not allowed on a subscription |
| Memes | Self-hosted **memegen** (jacebrowning/memegen) |
| Illustrations | **mflux** (MLX, Apple Silicon). Default model Z-Image Turbo; FLUX.2 Klein 4B as faster option |
| Code rendering | **Shiki** (syntax highlighting), Mermaid only for occasional diagram cards |
| Frontend | **Svelte / SvelteKit (static adapter)**, CSS scroll-snap, IntersectionObserver |
| App install | PWA (manifest + service worker) |
| Phone access | Local network in v1; **Tailscale** (`tailscale serve`) later (M6) |
| Learning | Hand-rolled numpy Thompson sampling (§12). River/MABWiser as later options |
| Agent interface | **MCP server** (official Python SDK) + a CLI over the same functions |
| Scheduling | launchd (nightly) + optional git post-commit hook (queue incremental run) |

---

## 5. Repos and groups

Configured in `local/repos.yaml`:

```yaml
groups:
  the-app:
    repos: [api-server, web-client, mobile]
  side-projects:
    standalone: true

repos:
  api-server:
    path: ~/code/api-server
    mascot: otter          # see §8
  web-client:
    path: ~/code/web-client
    mascot: raccoon
  mobile:
    path: ~/code/mobile
    mascot: hedgehog
  dotfiles:
    path: ~/code/dotfiles
    group: side-projects
    mascot: crow
```

- Groups are ranking features (learn "cares about the-app, skims side projects").
- Within a group, the agent may produce **cross-repo** stories (§6.6).
- A newly added repo starts at the default mix (§13) and blends toward learned taste.
- Analysis is read-only. The tool never writes to user repos.

---

## 6. Content model

The core idea: **what the story is** is separate from **how it is presented**.

A **card** = Story × Format × Persona × Tone (+ the repo's Mascot when illustrated).

One story ("billing/ has had 4 reverts this month") can become a meme, a thread, an iceberg layer, a news bulletin, or a persona's hot take. This gives variety without needing more facts, and lets the ranker learn format, persona and tone preferences independently of topic.

### 6.1 Story types — Git drama & history

| Story | Source signals |
|---|---|
| **Commit Drama** | Revert chains, "fix"/"fix again" sequences, late-night commits, huge diffs, force-push evidence |
| **Hot Spot** | Highest churn files/dirs over a window |
| **Archaeology** | Oldest surviving lines (blame), what changed around them |
| **RIP** | Deleted files/functions: born, lived, died, cause of death (commit message) |
| **Ancient TODO** | Oldest open TODO/FIXME/HACK with age |
| **Secret Couples** | Files with high co-change frequency that aren't obviously related |
| **Whose Code Is This** | Author share of a file/module over time |

### 6.2 Story types — Understanding the code

| Story | Source |
|---|---|
| **What It Does** | A module/function's purpose and role |
| **Journey** | Flow of a request / job / piece of data through the system |
| **Analogy** | A concept explained through a familiar comparison |
| **Snippet + Callouts** | 8–15 lines with 2–3 annotated points |
| **Cursed / Clever Line** | One remarkable line |
| **Before / After** | A recent diff explained |
| **New Arrival** | A newly introduced file/module and its purpose |

### 6.3 Story types — Interactive

| Story | Source |
|---|---|
| **Spot the Bug** | Real bug-fix commits: show pre-fix code, ask what's wrong; reveal the fix. Flagship type |
| **Quiz** | What does this return / which file handles X / what calls this |
| **Guess Who / Guess When** | Guess author or year from a snippet |
| **This or That** | Choose between two approaches; see persona picks and reasoning |

Wrong answers re-enter the feed later (spaced repetition, §12.5).

### 6.4 Story types — Cross-repo & recency

| Story | Source |
|---|---|
| **Weekly Recap** | Changes across a group since last recap |
| **Drift Alert** | Contract mismatch between repos (endpoint, shared type, config key) |
| **Ripple** | One feature landing across several repos |
| **Wrapped** | Monthly/yearly recap per repo, per group, or for the user's own commits |

### 6.5 Presentation formats

Each format has a renderer template (§10). The agent picks a format that fits the story, guided by the brief.

| Format | Visual |
|---|---|
| **Meme** | memegen template + top/bottom text |
| **Text meme** | POV, "nobody: / me:", starter pack (HTML template) |
| **Mascot scene** | mflux illustration + overlaid caption |
| **Comic** | 2–4 illustrated panels, horizontal swipe |
| **Thread 🧵** | 4–8 swipeable text/visual panels with a strong hook |
| **Iceberg** | Layered chart: surface facts → deep lore |
| **Tier list** | Ranked rows of modules/functions/deps with justification |
| **Red flags / green flags** | Flag list for a function or module |
| **Hot take** | Persona's opinion + comment pushback |
| **Day in the life** | Sequence of timestamped steps (request, job, data) |
| **Glow-up** | Before/after split |
| **Dating profile** | Module as a profile: bio, likes, dealbreakers |
| **Group chat** | Two+ files/modules texting each other |
| **Breaking news** | News-bulletin styling for big merges/reverts |
| **Horoscope** | Playful forecast for a repo/module based on recent churn |
| **ELI5** | One simple-explanation card |
| **Listicle / Top 5** | Numbered list |
| **Fun fact** | Single surprising fact |
| **Heatmap / chart** | Data visual (churn, authorship, timeline) |
| **Code card** | Shiki-highlighted code with callouts |
| **Quiz / poll** | Interactive choices with reveal |
| **Diagram** | Mermaid, used sparingly |

### 6.6 Depth: swipe sideways

- **Vertical scroll = the feed. Horizontal swipe = depth.**
- Every card has at least one depth panel: plain-language explanation, and the actual code/commit with links (file path, line range, commit hash).
- Fun formats must always have a "real explanation" panel so jokes never stand in for accuracy.

---

## 7. The social layer

### 7.1 Personas (invented creator accounts)

A cast of fictional posters, each with a handle, avatar (generated once, stored), and voice. Persona is a ranking feature.

| Persona | Handle | Voice |
|---|---|---|
| Greybeard | @greybeard | Grumpy senior, has seen it all, dry |
| Penny | @penny_learns | Enthusiastic junior, asks naive-but-good questions |
| The Archivist | @archivist | Codebase historian, loves lore and dates |
| Meme Compiler | @meme_compiler | Pure memes, chaotic |
| Paranoid Sec | @paranoid_sec | Security and failure-mode worrier |
| Ship-It Sam | @shipit_sam | Hype, celebrates merges and speed |

Personas live in `config/personas.yaml` and can be added/edited by the agent.

### 7.2 Code as accounts

Files, modules and repos can post as themselves ("@payments.py: refactored again, nobody asked 🙃"). Each repo has a profile page: mascot, stats, recent posts.

### 7.3 Comments

Cards may include 0–5 persona comments: replies, corrections, debates, jokes. Comments are part of the card spec. Debates are encouraged for trade-off topics.

### 7.4 Stories row

Circles at the top of the feed for today's new commits per repo, tapped through like Instagram stories.

### 7.5 Notifications

In-app notification list: "auth.py was in 3 commits today", "a new Spot the Bug from billing/", "Part 2 is up".

### 7.6 Series

Stories may be serialized ("Part 1/3"). The slotter keeps parts in order and spaced a few cards apart.

### 7.7 Real people rule

Git data about teammates (names, commit messages, timestamps, authorship) is fair game. **Personas may comment on real commits, but the system never fabricates quotes or opinions attributed to a real person.** Real people appear only through real data.

---

## 8. Mascots

- **One mascot per repo**, configured in `local/repos.yaml` or proposed by the agent when a repo is added.
- Each mascot has a fixed **style prompt** (species, look, palette, art style) and seed set in `config/mascots.yaml`, reused in every illustration for consistency.
- Cross-repo cards can feature multiple mascots together.
- Later: train a small LoRA per mascot if prompt-only consistency isn't good enough.

```yaml
otter:
  repo: api-server
  style: "a small round otter with a teal scarf, flat vector illustration, soft pastel palette, thick outlines"
  seed: 4242
```

---

## 9. Tones

Every card has one tone. Tone is a ranking feature, so the feed learns the mix the user enjoys.

`wholesome-nerdy` · `dry-deadpan` · `roast` · `hype` · `chaotic-absurd` · `earnest-teacher`

Default tone mix is in §13. Rules can force or exclude tones.

---

## 10. Generation pipeline

### 10.1 Trigger

- Nightly full run (launchd).
- Optional git post-commit hook that queues an incremental run for that repo.
- Manual: `gittok generate [--repo X] [--count N]`.

### 10.2 Git analysis (no LLM)

Precompute signals per repo into SQLite: churn by file/dir, co-change pairs, reverts, fix-chains, commit times, author shares, oldest blame lines, deleted paths, TODO ages, new files, commits since last run. This gives the agent leads and keeps agent work small.

### 10.3 Brief builder

Turns state into a brief for the agent:

- **Count** for this run (budget-limited, default 40).
- **Quotas** by story category, format, persona and tone, from learned weights blended with the default mix.
- **Active rules** (boosts, bans, focus areas).
- **Coverage gaps**: directories/modules the user has seen little of (learning boost).
- **Fresh material**: commits since last run, precomputed leads from §10.2.
- **Recently used** stories/formats to avoid repeats.

Example brief excerpt:

```
Make 40 cards.
Categories: git-drama 10, memes 8, explainers 8, code 6, interactive 4, cross-repo 4.
Rule: boost dir=api-server/sync/ x2 (expires 2026-11-06).
New: 3 commits in api-server since last run; 1 revert in web-client.
Unseen: billing/ (0 views) — include 3 intro cards.
Tones: lean dry-deadpan and roast; at least 4 other tones for exploration.
```

### 10.4 Agent run (MCP + skill)

`claude -p` is not allowed on a subscription, so generation runs inside an interactive agent session:

- The user (or a `/loop` later) runs the `gittok-generate` skill in Claude Code. The MCP server is part of the same process as the feed. The project's `.mcp.json` starts `gittok mcp --ui`: MCP over stdio, plus the feed API and PWA on loopback for as long as the session runs (on the LAN too with `--lan` or `server.lan: true`). `gittok serve` runs the feed and MCP (streamable HTTP at `/mcp`) without a session.
- The skill calls `get_brief`, which runs analysis, builds the brief, opens a `runs` row, and returns a short summary and a list of **work packets** (1–5 cards each, 2 by default, with a suggested model). Leads and guidance stay on the server.
- **Cost control:** the session model only hands out packet ids. Each packet goes to a `gittok-writer` subagent (`.claude/agents/`, only GitTok tools) on the packet's model (haiku for concrete-lead stories, sonnet for explanatory ones). The writer calls `get_packet` for its leads, attached materials (commit stat and diff, or numbered file lines and blame), and guidance. It researches with read-only MCP tools (`git_log`, `git_show`, `git_blame`, `git_grep`, `read_file`, `list_dir`) scoped to configured repos, only for what the materials lack, and calls `submit_cards(packet_id)` itself. It does not dry-run: `submit_cards` validates and returns the same rejects (`check_cards` stays for tools and tests). The server validates (§10.6), stores accepted cards, and returns reject reasons. One fix round, then rejected cards are dropped. The writer replies with one line, so card JSON never passes through the driver.
- `finish_run` closes the run and records models used, MCP call counts, and per-packet results.
- Per-run card count and per-day run caps are enforced by the server in `get_brief`.
- Card-writing guidance lives in `prompts/generate.md` and is returned by `get_packet`: schema, persona and tone definitions, mascot styles, and the real-people rule.

### 10.5 Card spec (agent output)

```json
{
  "story_type": "spot_the_bug",
  "format": "quiz",
  "persona": "paranoid_sec",
  "tone": "dry-deadpan",
  "repos": ["api-server"],
  "dirs": ["api-server/billing"],
  "difficulty": 2,
  "hook": "This shipped. It took 3 days to notice.",
  "visual": {
    "kind": "code",
    "code": { "repo": "api-server", "path": "billing/invoice.py", "commit": "a1b2c3d", "lines": [40, 54] }
  },
  "interaction": {
    "question": "What's wrong with this rounding?",
    "choices": ["...", "...", "...", "..."],
    "answer_index": 1
  },
  "depth": [
    { "kind": "explain", "text": "..." },
    { "kind": "code_diff", "repo": "api-server", "commit": "d4e5f6a", "path": "billing/invoice.py" }
  ],
  "comments": [
    { "persona": "greybeard", "text": "..." },
    { "persona": "penny_learns", "text": "..." }
  ],
  "series": null,
  "sources": [
    { "repo": "api-server", "commit": "d4e5f6a" },
    { "repo": "api-server", "path": "billing/invoice.py", "lines": [40, 54] }
  ]
}
```

`visual.kind` options: `text` (title, body, bullets), `meme` (template id + lines), `illustration` (prompt; mascot style auto-prepended), `comic` (panel prompts + captions), `code`, `diff`, `chart` (type + data), `template` (format-specific fields: iceberg layers, tier rows, chat messages, etc.), `diagram` (mermaid).

Full JSON Schema lives in `schema/card.schema.json` and is validated strictly.

### 10.6 Validation (no LLM)

- Schema validation.
- Every cited repo/path/line range/commit must exist (`git cat-file`, file reads).
- Quiz answer index valid; code excerpts match the cited lines at the cited commit.
- Real-people rule: comments/quotes only from personas or code accounts.
- Reject or drop invalid cards; log reasons for prompt tuning.

### 10.7 Rendering

- **Meme** → memegen (local instance) → PNG.
- **Illustration / comic / mascot scene / persona avatars** → mflux with mascot style prompt + seed → PNG. Captions are overlaid by the frontend, **never baked into images**.
- **Code / diff** → Shiki HTML at render time.
- **Charts / template formats** → Svelte components fed by structured data.
- **Diagram** → Mermaid in the client.
- Assets stored under `data/assets/`, referenced by card id.

### 10.8 Budget

- Per-run card count and per-day run limit in `config/settings.yaml` to stay within subscription limits.
- Illustration count per run capped (rendering time ~5–20s/image on a recent Mac).

---

## 11. Feed app (PWA)

- Full-screen vertical snap-scroll; horizontal swipe for depth panels.
- Stories row, notifications, repo profile pages, saved cards.
- Actions per card: like, save, "explain more", answer (interactive).
- Offline cache of the current feed batch.
- Event capture:

| Event | Captured |
|---|---|
| `impression` | card id, timestamp |
| `dwell` | visible ms (IntersectionObserver, ≥60% visible) |
| `skip` | left in under ~1s |
| `scroll_back` | returned to a previous card |
| `depth_open` | horizontal swipe, panel index |
| `like` / `save` / `explain_more` | — |
| `answer` | choice, correct/incorrect |
| `source_tap` | tapped file/commit link |

Events batch to `POST /events`.

---

## 12. Learning and ranking

### 12.1 Reward

Per impression, compute a reward in [0, 1]:

- Skip under ~1s → strong negative (0).
- Dwell normalized by **expected read time** for the card's format/length (a thread should take longer than a meme).
- Positive boosts: depth_open, explain_more, like, save, source_tap; **scroll_back** is the strongest signal.
- Interactive: answering counts as engagement regardless of correctness.

Reward weights live in `config/reward.yaml` and are expected to be tuned.

### 12.2 Features

Each card is described by feature values: story_type, format, persona, tone, repo, group, dir, author(s), recency bucket, difficulty, mascot, has_comments, is_series.

### 12.3 Model

- **Thompson sampling with a Beta(α, β) per feature value**, updated from rewards.
- Card score = combination of sampled values across its features (start with a weighted mean; keep it simple and explainable).
- **Time decay** on α/β so interests can shift (half-life configurable, default ~3 weeks).
- Default mix (§13) seeds the priors.

### 12.4 Slotting (builds the actual feed)

Applied after scoring, in order:

1. **Rules** (§14): bans remove, boosts multiply, focus reserves slots.
2. **Exploration share** (~15–20%): cards picked outside learned taste.
3. **Learning boost**: unseen or under-seen code areas get reserved slots.
4. **Rhythm**: no more than 2 of the same format in a row; alternate fast cards (memes) and slow cards (threads, quizzes).
5. **Series ordering** and spacing.
6. **Repeat limits**: no repeated story within N days unless spaced repetition.

### 12.5 Spaced repetition

Wrong answers on interactive cards re-enter after increasing intervals (1d → 3d → 7d → mastered).

### 12.6 Driving generation

Aggregated weights feed the brief's quotas (§10.3): make more of what scores well, a little of everything else. The ranker reorders what exists; the brief decides what gets made.

---

## 13. Default mix (shipped prior)

`config/defaults.yaml`:

```yaml
categories:
  git_drama: 0.25
  memes: 0.20
  illustrated_explainers: 0.20
  code: 0.15
  interactive: 0.10
  cross_repo_and_recent: 0.10

tones:
  wholesome-nerdy: 0.20
  dry-deadpan: 0.20
  roast: 0.15
  hype: 0.15
  chaotic-absurd: 0.15
  earnest-teacher: 0.15

visual_mix:
  image_min_share: 0.5   # least share of cards in an image format (meme, illustration, comic, chart, diagram)
personas: uniform
topics: uniform across repos and dirs, tilted toward recent commits
exploration_share: 0.18
prior_strength: 10   # pseudo-observations; behavior outweighs it within ~1–2 weeks
```

"Reset to defaults" restores this file's priors.

---

## 14. Rules

Stored in SQLite as plain records; always override learned weights.

```
boost   dir=api-server/sync   x2.0   until 2026-11-06
ban     format=horoscope
focus   repo=billing          slots=5 per batch   until 2026-11-13
limit   tone=roast            max=0.10
prefer  persona=greybeard     x1.5
```

Types: `boost`, `ban`, `focus`, `limit`, `prefer`. Optional expiry. Each rule records who created it and why (the user's phrasing).

---

## 15. Agent interface (MCP + CLI)

MCP server `gittok` exposing:

| Tool | Purpose |
|---|---|
| `get_profile` | Plain-English summary of learned taste with evidence |
| `explain_weights` | Per-feature numbers (e.g. "memes: 72% hit rate over 140 views, trending down") |
| `list_rules` / `add_rule` / `remove_rule` | Manage rules |
| `reset_defaults` | Reset priors (all, or one feature group) |
| `list_repos` / `add_repo` / `set_group` | Repo management |
| `set_mascot` / `edit_persona` | Cast management |
| `generate` | Trigger a run with optional overrides |
| `recent_cards` / `card_stats` | What was shown and how it did |
| `coverage` | What parts of each repo the user has seen |

A nightly job writes `data/profile.md`, a plain-English profile summary. The CLI (`gittok …`) exposes the same functions.

Example: user tells Claude Code "less memes, more of the sync engine this week" → agent calls `add_rule` twice and confirms.

---

## 16. Data model (SQLite)

- `repos`, `groups`, `repo_groups`
- `git_signals` (precomputed per repo/run)
- `runs` (brief, agent backend, counts, rejects, duration)
- `cards` (spec JSON, status, created_at, run_id). Unique on `(story_key, format)`: one story may be told again in another format (docs/learning.md section 13).
- `card_features` (card_id, feature, value)
- `assets` (card_id, kind, path)
- `events`
- `rewards` (impression-level)
- `weights` (feature, value, alpha, beta, updated_at)
- `rules`
- `personas`, `mascots`
- `srs` (spaced repetition state per card)
- `notifications`
- `stories` (one row per story ever made: `story_key`, repo, type, sources, first and last card time, `cards_made`, `best_reward`, `liked`, `formats`: the JSON list of formats already used). Gc never deletes it, so duplicate checks survive card deletion.
- `saved_cards` (`card_id`, `saved_at`, `saved_ts`: cards the user saved; updated by `save` events, so it survives event pruning). Gc never deletes a saved card.
- `leads` (the lead ledger: one row per commit lead, or per path and blob sha, with `story_type`, `strength`, `head_sha`, first and last seen time, `times_covered`, `last_covered_at`, `mean_reward`). `cards.lead_id` points at the lead a card used (no foreign key). Gc deletes only leads that are old and never covered.

---

## 17. Milestones

**M1 — Skeleton feed**
Repo config, git analysis for one repo, brief builder (static default mix), MCP server (brief, read-only research tools, submit_cards) + `gittok-generate` skill, validator, code/text cards only, FastAPI + Svelte snap-scroll feed on the Mac.

**M2 — Renderers and formats**
memegen, mflux with mascots, template formats (iceberg, tier list, group chat, etc.), depth panels, personas and comments.

**M3 — Learning**
Event capture, reward scoring, Thompson sampling, slotting, spaced repetition, quotas driven by weights.

**M4 — Agent control**
Steering tools on the same MCP server + CLI, rules, profile summary.

**M5 — Multi-repo and phone**
Groups, cross-repo stories (Drift, Ripple, Recap), stories row, notifications, PWA install over the local network, scheduling (`/loop` or routines; launchd for analysis), post-commit hook.

**M6 — Later**
Tailscale for private HTTPS off the LAN. Narrated short "reels" (local TTS + generated images, assembled with ffmpeg), Wrapped, per-mascot LoRAs.

## 18. Open questions

- Exact reward weights and expected read times per format (tune with real use).
- How many personas feel right before the cast gets noisy.
- Whether Codex backend output quality matches Claude for card specs.
- Prompt-only mascot consistency vs. needing LoRAs.

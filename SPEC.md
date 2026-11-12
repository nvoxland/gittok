# GitTok design

GitTok is a personal feed for understanding the codebases you work in. A local server on your Mac holds cards about your repos and their git history. A Claude Code session writes the cards. You scroll them in a browser or on your phone. The feed learns what you read, and you can ask the agent what it learned and tell it what to change.

This document describes the design. The exact contracts are in `docs/`: card formats in `docs/formats.md`, learning and ranking in `docs/learning.md`, the HTTP API in `docs/api.md`, stories, notifications and LAN access in `docs/social.md`, config in `docs/config.md`.

---

## 1. Goals

- Make understanding your own codebases (structure, behavior, history, people, change) feel like scrolling a social feed.
- Feel like a real feed: varied formats, recurring characters, comments, humor, series. Not blocks of text.
- Run on one Mac with a Claude Code subscription. GitTok holds no API keys and calls no model API itself.
- Learn the reader's tastes from behavior, and keep that learning visible and steerable through the agent.
- Support several repos, grouped or standalone.
- Keep every card honest: each card cites git, and the server checks the citations.

## 2. Non-goals

- A multi-user or hosted service. This is one person's tool on their own machine.
- Generation per swipe. Cards are made in batches.
- Video.
- A replacement for documentation or code review.

---

## 3. Architecture

```
            ┌──────────────────────── Mac ────────────────────────┐
 repos ───► │ Git analysis ─► Brief builder ─► MCP get_brief ──►  │
            │                     ▲      Claude Code session + skill │
            │                     │                 │ card specs  │
            │   weights + rules + coverage          ▼             │
            │                     │           Validator           │
            │                     │                 ▼             │
            │                     │   Render worker (memegen,     │
            │                     │   mflux)                      │
            │                     │                 ▼             │
            │   Ranker/Slotter ◄── SQLite ◄── cards + assets      │
            │         │              ▲                            │
            │      FastAPI ──────────┘ events                     │
            │         │                                           │
            │   MCP server + CLI ◄── submit_cards / steering tools│
            └─────────┼───────────────────────────────────────────┘
                      │ loopback, and the LAN with pairing
                   Browser or phone (web app)
```

GitTok lives in one directory, the GitTok directory, that `gittok init <dir>` makes. It holds the MCP entry, the skills and agents, the session hooks, and all the user's files. Nothing is installed outside it, and nothing starts by itself.

There are two processes, and a Claude Code session owns both:

- **The MCP server.** The `.mcp.json` of the directory starts `gittok mcp --ui` when a session starts there. It speaks MCP over stdio. This is the only MCP transport.
- **The feed server.** The MCP server starts it as a child (`gittok serve`). It serves the feed API and the web app and runs the background workers (render, learning, notifications, garbage collection). It has no MCP endpoint. It stops when the session ends.

`gittok serve` can also be started by hand, for a look at the feed without a session.

## 4. Stack

| Concern | Choice |
|---|---|
| Language and tooling | Python 3.13, managed with uv |
| Server | FastAPI (feed API, static web app, assets, events) |
| Database | SQLite, one file |
| Git analysis | The `git` program (log, blame, diff, show). `gitq.py` is the only module that starts it |
| Code structure | tree-sitter (definitions, references, imports), with regex patterns as the fallback; ast-grep for profile rules |
| Content agent | A Claude Code session that runs the `gittok-generate` skill against the GitTok MCP server |
| Memes | A local memegen server (optional) |
| Illustrations | mflux on Apple silicon (optional) |
| Code and diagrams in the client | Shiki for syntax highlighting, Mermaid for diagram cards |
| Web app | SvelteKit with the static adapter, CSS scroll-snap |
| Phone access | The local network, on by default, with a pairing token for each device. The server speaks plain HTTP |
| Learning | Thompson sampling, written by hand (section 12) |
| Agent interface | An MCP server (the official Python SDK) and a CLI over the same functions |

---

## 5. Repos and groups

Repos are configured in `local/repos.yaml` (see `docs/config.md`):

```yaml
groups:
  the-app:
    repos: [api-server, web-client]

repos:
  api-server:
    path: ~/code/api-server
    mascot: otter
  web-client:
    path: ~/code/web-client
  dotfiles:
    path: ~/code/dotfiles
```

- A repo is a local directory, or a remote URL that GitTok clones into its own `repos/` directory and fetches before each analysis.
- Groups are ranking features: the feed can learn "cares about the-app, skims the rest".
- Within a group, the agent may write cross-repo stories (section 6.4).
- Analysis is read-only. GitTok never writes to a working tree, an index, or a local branch of your repos. A repo with `fetch: true` gets a fetch that updates remote-tracking refs only.
- Each repo has a **profile** (`local/profiles/<repo>.yaml`): rules, kept as data, that find the code worth teaching. The `gittok-profile-repo` skill writes it. The agent runs that skill by itself for a repo with no profile: right after the repo is added, and before it makes cards. For a repo that has a profile, the agent only offers a revision. See `docs/learning.md`, "Candidate score and repo profiles".

---

## 6. Content model

The core idea: **what the story is** is separate from **how it is presented**.

A **card** = Story × Format × Persona × Tone (plus the repo's mascot when illustrated).

One story ("billing/ has had 4 reverts this month") can become a meme, a thread, an iceberg layer, a news bulletin, or a persona's hot take. This gives variety without more facts. It also lets the ranker learn format, persona and tone preferences apart from the topic.

The story types and formats below are the values of `story_type` and `format` in the card schema (`src/gittok/schema/card.schema.json`).

### 6.1 Story types: git drama and history

| Story | Source signals |
|---|---|
| `commit_drama` | Revert chains, "fix" then "fix again" sequences, late-night commits, very large diffs |
| `hot_spot` | Files and dirs with the highest churn in a window |
| `archaeology` | The oldest surviving lines (blame) and what changed around them |
| `rip` | Deleted files: when they were added, when they were removed, and the commit message that removed them |
| `ancient_todo` | The oldest open TODO, FIXME or HACK, with its age |
| `secret_couples` | Files that change together often |
| `whose_code` | Author share of a file or module |

### 6.2 Story types: understanding the code

| Story | Source |
|---|---|
| `what_it_does` | The purpose and role of a module or function |
| `journey` | How a request, a job or a piece of data moves through the system |
| `analogy` | A concept explained through a familiar comparison |
| `snippet_callouts` | A short piece of code with annotated points |
| `cursed_clever_line` | One remarkable line |
| `before_after` | A recent diff explained |
| `new_arrival` | A newly added file or module and its purpose |

### 6.3 Story types: interactive

| Story | Source |
|---|---|
| `spot_the_bug` | A real bug-fix commit: show the code before the fix, ask what is wrong, reveal the fix |
| `quiz` | What does this return, which file handles X, what calls this |
| `guess_who` / `guess_when` | Guess the author or the year from a snippet |
| `this_or_that` | Choose between two approaches |

A wrong answer brings the card back later (spaced repetition, section 12.5).

### 6.4 Story types: cross-repo and recency

| Story | Source |
|---|---|
| `weekly_recap` | Changes across a group in the last week |
| `drift_alert` | A contract that does not match between repos |
| `ripple` | One feature that lands in several repos |

### 6.5 Presentation formats

The agent picks a format that fits the story, guided by the brief. `docs/formats.md` gives the visual kinds each format allows and the exact fields.

| Format | Visual |
|---|---|
| `meme` | A memegen template with text lines |
| `text_meme` | POV, "nobody: / me:", starter pack, expectation and reality (drawn by the client) |
| `mascot_scene` | An mflux illustration with a caption |
| `comic` | Illustrated panels |
| `thread` | Swipeable text panels with a strong hook |
| `iceberg` | Layers: surface facts down to deep lore |
| `tier_list` | Ranked rows of modules, functions or dependencies |
| `flags` | Red flags and green flags for a function or module |
| `hot_take` | A persona's opinion, with pushback in the comments |
| `day_in_life` | Timestamped steps of a request, a job or a piece of data |
| `glow_up` | Before and after |
| `dating_profile` | A module as a profile: bio, likes, dealbreakers |
| `group_chat` | Files or modules that text each other |
| `breaking_news` | News-bulletin styling for big merges and reverts |
| `horoscope` | A playful forecast for a repo or module |
| `eli5` | One simple explanation |
| `listicle` | A numbered list |
| `fun_fact` | One surprising fact |
| `text_post` | A plain post |
| `chart` | A data visual (churn, commit hours, author shares, co-change). The data comes from the server, never from the agent |
| `code_card` | Highlighted code |
| `quiz` | Choices with a reveal |
| `diagram` | A Mermaid diagram |

### 6.6 Depth: swipe sideways

- **Vertical scroll is the feed. Horizontal swipe is depth.**
- Every card has at least one depth panel: a plain explanation, and the real code or commit.
- Every card has a `learn` line: the one concrete fact the reader takes away.
- A fun format always has a real explanation panel, so a joke never stands in for accuracy.

---

## 7. The social layer

### 7.1 Personas (invented creator accounts)

A cast of fictional posters. Each has a handle, an avatar, and a voice. Persona is a ranking feature.

| Persona | Handle | Voice |
|---|---|---|
| Greybeard | `greybeard` | Grumpy senior engineer who has seen it all. Dry |
| Penny | `penny_learns` | Enthusiastic junior. Asks naive but good questions |
| The Archivist | `archivist` | Codebase historian. Loves lore and dates |
| Meme Compiler | `meme_compiler` | Pure memes, chaotic |
| Paranoid Sec | `paranoid_sec` | Worries about security and failure modes |
| Ship-It Sam | `shipit_sam` | Hype. Celebrates merges and speed |

The handles are fixed by the card schema. Names, voices and bios live in `config/personas.yaml`; your changes go to `local/personas.yaml`.

### 7.2 Code as accounts

A file or directory can post as itself (the `account` field, `repo:path`). Each repo, persona and file has a page in the web app.

### 7.3 Comments

A card may have up to 5 persona comments: replies, corrections, debates, jokes. Comments are part of the card spec.

### 7.4 Stories row

Circles at the top of the feed, one per repo with commits in the last 24 hours. Tap through them one commit at a time.

### 7.5 Notifications

A list in the app: new cards from a run, quiz cards that are due again, a file that was in many commits today, a new Spot the Bug.

### 7.6 Series

A story may have parts ("Part 1/3"). The slotter keeps parts in order and a few cards apart.

### 7.7 Real people rule

Git data about teammates (names, commit messages, timestamps, authorship) is fair game. **Personas may comment on real commits, but the system never invents quotes or opinions and attributes them to a real person.** Real people appear only through real data. A real person is never an account.

---

## 8. Mascots

- One mascot per repo, named in `local/repos.yaml`.
- Each mascot has a fixed **style** text and a **seed** (`local/mascots.yaml`). GitTok puts the style before every illustration prompt and reuses the seed, so a mascot looks the same on every card.
- GitTok ships no mascot: a mascot belongs to the user's repo. When a repo is added, the agent profiles it and then picks a small character and a style that fit it (`set_mascot`), and tells the user. It does this only when the illustration renderer can run (`status`: `renderers.illustration`).
- A repo with no mascot gets no `mascot_scene` and no `comic` cards. No card is rejected for a missing mascot.
- A cross-repo card can show several mascots.

```yaml
mascots:
  otter:
    repo: api-server
    style: "a small round otter with a teal scarf, flat vector illustration, soft pastel palette, thick outlines"
    seed: 4242
```

---

## 9. Tones

Every card has one tone. Tone is a ranking feature, so the feed learns the mix the reader likes.

`wholesome-nerdy` · `dry-deadpan` · `roast` · `hype` · `chaotic-absurd` · `earnest-teacher`

The default tone mix is in section 13. Rules can limit or ban a tone.

---

## 10. Generation pipeline

### 10.1 Trigger

GitTok does not start a model by itself. A person, or a hook in a Claude Code session, runs the `gittok-generate` skill:

- On demand: `/gittok-generate`.
- From a session hint. `gittok health --hint` prints a line when the unseen cards will not last `agent.target_runway_days`. `gittok feed-watch` waits until the feed server says the feed wants cards, then exits, and the session runs the skill. See `docs/scheduling.md`.
- After a repo is added: the agent profiles it and then runs the skill for the first cards, without a question.

### 10.2 Git analysis (no model)

GitTok computes signals per repo and stores them in SQLite, cached by the head commit: churn by file and dir, co-change pairs, reverts, fix chains, commit times, author shares, oldest blame lines, deleted paths, TODO ages, new files. It also mines candidate code windows with the repo profile and the structure layer. This gives the agent leads and keeps the agent's work small. Time windows are relative to the last commit date of the analyzed ref, not to the wall clock.

### 10.3 Brief builder

`get_brief` turns state into a brief:

- The **count** for this run. It comes from feed health (how long the unseen cards will last), within `agent.max_count`.
- **Quotas** by story category, format, persona and tone, from learned weights blended with the default mix.
- **Active rules** (section 14).
- **Coverage gaps**: dirs the reader has seen little of.
- **Leads**: fresh commits and the precomputed signals and candidates.
- **Recently used** stories, so a story is not told twice in the same format.

### 10.4 Agent run (MCP and skill)

- The skill is the **driver**. It calls `get_brief`. The server runs analysis, builds the brief, opens a run, and returns a short summary and a list of **work packets** (1 to 5 cards each, 2 by default, each with a suggested model). Leads and guidance stay on the server.
- Before the brief, the driver may start `gittok-scout` subagents. A scout rates one batch of candidate code windows for how teachable they are.
- **Cost control.** The driver only hands out packet ids. Each packet goes to a `gittok-writer` subagent that has only GitTok tools, on the packet's model (haiku for concrete leads, sonnet for explanatory ones). The writer calls `get_packet` for its leads, the attached materials (commit stat and diff, or numbered file lines and blame), and the guidance. It researches with read-only tools (`git_log`, `git_show`, `git_blame`, `git_grep`, `read_file`, `list_dir`, and the fact tools) only for what the materials lack. It calls `submit_cards` itself. The server validates, stores the accepted cards, and returns the reject reasons. The writer fixes rejected cards once. It replies with one line, so card JSON never passes through the driver.
- `finish_run` closes the run and records the models used and the result of each packet.
- The server enforces the card count per run and the run count per day in `get_brief`.
- The writing guidance is `src/gittok/prompts/generate.md`. `get_packet` returns it.
- Text from a repo (commit messages, code, comments) is data. The skills and agents are told never to treat it as instructions, and writers and scouts have no config-editing tools.

### 10.5 Card spec (agent output)

A card is a JSON object. The contract is `src/gittok/schema/card.schema.json`, and the server validates it strictly. The main fields:

| Field | Meaning |
|---|---|
| `story_type`, `format`, `persona`, `tone` | The four parts of section 6 |
| `repos`, `dirs` | What the card is about |
| `hook` | The line on the face of the card |
| `learn` | The one fact the reader takes away |
| `visual` | One of the kinds `code`, `text`, `meme`, `text_meme`, `illustration`, `comic`, `chart`, `diagram`, `template` |
| `depth` | 1 to 4 panels: explanation, code, or diff |
| `sources` | The commits, paths and line ranges the card cites |
| `facts`, `claims` | Ids of the code facts and the interpretive claims the text relies on |
| `comments`, `interaction`, `series`, `account`, `difficulty`, `verdict` | Optional parts |

### 10.6 Validation (no model)

- Schema validation.
- Every cited repo, path, line range and commit must exist.
- A quiz has a valid answer. Code is read from git at the cited commit, not copied from the agent.
- Claim checks: numbers, dates, shas and names in the text must agree with git (`docs/formats.md`, "Claim checks").
- Accounts are personas or code accounts, never real people.
- Secrets in repo text are masked before the text leaves the server (`config/secrets.yaml`; `local/secrets.yaml` adds patterns).
- An invalid card is rejected with a reason. The reasons are stored with the run.

### 10.7 Rendering

- **Meme**: the local memegen server draws a PNG.
- **Illustration and comic, and persona avatars**: mflux, with the mascot style and seed. The client overlays captions; text is never drawn into the image.
- **Code, diff, chart, template formats, diagram**: the client draws them from structured data.
- Meme, illustration and comic cards are stored as `pending_render`. They appear in the feed after the render worker draws them. When a renderer is not installed, the brief does not ask for its formats.

### 10.8 Budget

- The card count per run and the run count per day are limited in `config/settings.yaml` (`agent.max_count`, `agent.per_day_runs`).
- The illustration count per run is limited (`render.max_illustrations_per_run`).

---

## 11. Feed app

- Full-screen vertical snap scroll. Horizontal swipe for depth panels.
- Stories row, notifications, repo pages, persona pages, file pages, saved cards.
- Actions per card: like, save, comments, answer (interactive cards), reply to a comment.
- An installable web app with an offline copy of the last batch. This part needs HTTPS or `localhost` (`docs/install.md`, "HTTPS on a LAN").
- The client records events and sends them in batches to `POST /api/events`: impression, dwell, skip, scroll back, depth open, like, save, answer, source tap, and the play events of cards that play piece by piece. `docs/learning.md` section 1 has the list.

---

## 12. Learning and ranking

`docs/learning.md` is the contract. In short:

### 12.1 Reward

Each impression gets a reward in [0, 1]:

- A skip in under about 1 s gives 0.
- Dwell is compared with the **expected read time** of the card's format and length. A thread takes longer than a meme.
- Depth open, like, save, source tap and scroll back add to it.
- On an interactive card, an answer counts as engagement, right or wrong.

The weights are in `config/reward.yaml`.

### 12.2 Features

Each card has feature values: story type, format, persona, tone, repo, group, dir, visual kind, recency, difficulty, and more (`importance` in `config/reward.yaml` lists them).

### 12.3 Model

- **Thompson sampling with a Beta(α, β) per feature value**, updated from rewards.
- A card's score is the importance-weighted mean of the sampled values of its features. This is simple, and it can be explained.
- α and β decay with time, so interests can shift (`half_life_days`).
- The default mix (section 13) seeds the priors.

### 12.4 Slotting (builds the feed)

After scoring, in order:

1. **Rules** (section 14): bans remove, boosts multiply, focus reserves slots, limits cap a share.
2. **Exploration**: a share of the slots goes to cards outside the learned taste.
3. **Learning boost**: code areas the reader has seen little get reserved slots.
4. **Rhythm**: no more than 2 cards of the same format in a row; fast cards and slow cards alternate.
5. **One story, one slot**, and **series** parts in order and spaced.
6. **Repeat limit**: a card comes back within the repeat window only through spaced repetition.

### 12.5 Spaced repetition

A wrong answer on an interactive card brings the card back after growing intervals (1 day, 3 days, 7 days, then mastered).

### 12.6 Driving generation

The weights also feed the quotas of the brief (section 10.3): make more of what scores well, and a little of everything else. The ranker orders what exists. The brief decides what gets made.

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
  image_min_share: 0.5   # least share of cards in an image format
exploration_share: 0.18
prior_strength: 10       # pseudo-observations behind each prior
```

A reset (`reset_defaults`, or `gittok reset-weights`) deletes the learned weights, so the feed starts from this mix again. `local/defaults.yaml` changes the mix for one GitTok directory; like every shipped file, it has a local file that is merged over it (`docs/config.md`, "The merge rule").

---

## 14. Rules

Rules are plain records in SQLite. They always override learned weights.

```
boost   dir=api-server/sync   x2.0   until 2026-11-06
ban     format=horoscope
focus   repo=billing          slots=3   until 2026-11-13
limit   tone=roast            max_share=0.10
prefer  persona=greybeard     x1.5
```

Types: `boost`, `ban`, `focus`, `limit`, `prefer`. A rule may expire. Each rule records who made it and why (the user's own words). `docs/learning.md` section 10 says which rules change generation and which only change the order.

---

## 15. Agent interface (MCP and CLI)

The MCP server is named `gittok`. Its tools fall into these groups:

| Group | Tools |
|---|---|
| Generation | `get_brief`, `get_packet`, `submit_cards`, `check_cards`, `finish_run`, `get_card_schema` |
| Scouting | `scout_status`, `get_candidates`, `rate_candidates` |
| Read-only research | `git_log`, `git_show`, `git_blame`, `git_grep`, `read_file`, `list_dir`, `defined_where`, `who_calls`, `what_calls`, `symbol_history`, `facts_for` |
| Repo profiles | `survey_repo`, `test_detector`, `save_profile`, `rule_stats`, `submit_facts` |
| What the feed learned | `get_taste_profile`, `explain_weights`, `feed_health`, `coverage`, `recent_cards`, `card_stats` |
| State | `status`, `recent_runs` (with `list_repos`, `feed_health` and `recent_cards`, these answer questions about GitTok's state, so the agent does not read the database or run the CLI) |
| Steering | `list_rules`, `add_rule`, `remove_rule`, `reset_defaults`, `set_playback_speed` |
| Config | `list_repos`, `add_repo`, `remove_repo`, `set_group`, `set_mascot`, `edit_persona` |
| Config files (read-only) | `config_files`, `get_config`, `check_config` |
| Phone access | `pairing_link`, `set_lan` |

Every repo tool takes a configured repo name, never a path. The one exception is `add_repo`, which takes the path or URL of the repo to add.

The user manages GitTok by asking the agent in plain words: the server's MCP instructions and the `gittok-steer` skill map such requests to the Config, Phone access and Steering tools. These tools change the user's setup, so they are only for a request the user made in the conversation. The writer and scout subagents do not have them, and the generation and profiling skills forbid them.

- `add_repo` accepts the root of any git repo on the machine (own `.git`, top of the checkout, has a commit, not inside a configured repo). The permission prompt of Claude Code is the consent. `repos.allowed_roots`, when the user set it, limits the tool to those directories.
- `remove_repo` removes the entry and all that GitTok made for the repo: its cards with every row and file that hangs off them, the rows keyed by the repo, its profile, the rules on the repo, and a mascot of the repo that the user defined and no other repo uses. The learned weights stay. A card of another repo that only cites the repo stays. `keep_data` removes only the entry. It deletes the directory only for a clone that GitTok made (`remote` set, path exactly `<home>/repos/<name>`, not a symlink). Garbage collection does the same for a repo that is no longer configured, and the feed never serves its cards (`docs/learning.md`, "Garbage collection").
- `list_repos` gives per repo `profiled`, `cards`, `unseen` and `last_card_at`. `feed_health` gives the backlog, also per repo (`by_repo`). `recent_cards(limit, repo)` names the repo and group of each card. `recent_runs(limit)` gives the last runs with counts and the top reject reasons. `status` gives the version, the directory and its files version, and the state of the feed server.
- Every shipped config file has a local file in `local/` that is merged over it. There is no tool that writes any setting: on the user's request the agent edits the local file with its own file tools. `config_files` lists the files with their merge rule, `get_config(file, key)` gives the shipped, local and effective value, and `check_config` loads everything again and returns errors and warnings. The writer and scout subagents do not have these tools, and generation and profiling never edit `local/` by hand.
- `status` also gives `renderers` (`illustration`, `meme`): whether each image renderer can run now.
- `pairing_link` returns the pairing links, opens the loopback-only QR page (`/pairing`) in the browser, and carries a `notice` about LAN serving that the agent relays to the user. `set_lan` writes only `server.lan` in `local/settings.yaml`; the change needs a server restart.

The server writes `<data_dir>/profile.md`, a plain-English summary of the learned taste, once a day. The CLI (`gittok --help`) gives the same functions without an agent.

Example: the user tells Claude Code "less memes, more of the sync engine this week". The `gittok-steer` skill calls `add_rule` twice and confirms.

---

## 16. Data model (SQLite)

One database file in the data directory. The schema is `src/gittok/migrations/`. The main tables:

- `repos`, `groups`, `repo_groups`, `personas`, `mascots`.
- `git_signals`: the analysis result per repo and head commit.
- `runs`: one row per generation run (brief, counts, reject reasons).
- `cards`: the spec as JSON, status, run id. Unique on `(story_key, format)`: one story may be told again in another format (`docs/learning.md` section 13).
- `card_features`, `assets`.
- `events`, `rewards`, `weights`, `rules`, `srs`, `prefs`.
- `notifications`, `story_views`, `replies`.
- `stories`: one row per story ever made. Garbage collection never deletes it, so duplicate checks survive card deletion. The exception is a removed repo: all its data goes.
- `saved_cards`: the cards the reader saved. Garbage collection never deletes a saved card.
- `leads`: the lead ledger, one row per commit lead or per path and blob. Garbage collection deletes only leads that are old and were never covered.
- `candidates`, `candidate_ratings`, `scout_batches`: mined code windows and their scout ratings.
- `knowledge`, `knowledge_events`, `knowledge_symbols`: what the reader has seen (`docs/learning.md` section 14).
- `fact_*`: code facts (definitions, calls, imports) from the structure layer and from analyzers.

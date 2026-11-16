# Configuration reference

GitTok reads two kinds of files:

- **Shipped files** in `config/`. They hold the defaults and ship with GitTok. Do not edit them: an upgrade replaces them, and in an installed tool they are inside the package.
- **Your files** in `local/` of your GitTok directory. GitTok never ships these. All of them are optional. Each shipped file has a local file of the same name, and GitTok merges yours over the shipped one. So you can change every default, and an upgrade keeps your changes.

You do not have to edit a file. Ask your agent in a session in your GitTok directory ("also scan .proto files", "change the reward for a like"): it uses a tool where one exists and edits the local file where none does (see "Change the config by asking").

## The two roots

GitTok works with two folders: the **shared root** (holds `config/`) and the **home** (holds `local/`, the data directory, and `repos/`). The home is your GitTok directory, the one that `gittok init <dir>` made. GitTok picks the two in this order:

1. `GITTOK_ROOT`, if set: that GitTok directory (or that clone of the source).
2. Otherwise it walks up from the current directory. A folder with `gittok.yaml` is a GitTok directory: it is the home, and the shared root is inside the package. A folder with `config/settings.yaml` is a clone of the source: it is both roots.
3. With neither, the command stops with an error: not inside a GitTok directory.

So your files are `<gittok dir>/local/...`, and in a clone they are `<clone>/local/...`. The paths below are relative to the home. `gittok.yaml` itself is not a config file: `gittok init` and `gittok update` write it, and you do not edit it. `gittok init` makes `local/repos.yaml` only; you (or your agent) make another local file when you first need it.

## Every file

| File | What it holds | Shipped default | Your file | Who edits your file |
|---|---|---|---|---|
| repos | The repos and groups | none | `local/repos.yaml` | The `add_repo`, `remove_repo`, `set_group`, `set_mascot` tools, `gittok repos ...`, or you |
| mascots | The mascot of each repo | none | `local/mascots.yaml` | The `set_mascot` tool, `gittok mascot set`, or you |
| profiles | The profile of one repo | none | `local/profiles/<repo>.yaml` | The `gittok-profile-repo` skill, through `save_profile` |
| guidance | Your own words for the card writers: tone, style, subjects | none | `local/guidance.md` | You, or your agent by a file edit |
| settings | Server, agent, analysis, render and clean-up settings | `config/settings.yaml` | `local/settings.yaml` | You, or your agent by a file edit. The `set_lan` tool writes `server.lan` |
| personas | Names, voices and bios of the cast | `config/personas.yaml` | `local/personas.yaml` | The `edit_persona` tool, `gittok persona edit`, or you |
| defaults | The starting mix of categories and tones | `config/defaults.yaml` | `local/defaults.yaml` | You, or your agent by a file edit |
| reward | Reward weights, read times, decay, lead score | `config/reward.yaml` | `local/reward.yaml` | You, or your agent by a file edit |
| scan_defaults | The file set of a repo with no profile | `config/scan_defaults.yaml` | `local/scan_defaults.yaml` | You, or your agent by a file edit |
| file_types | Extension tables, manifest names | `config/file_types.yaml` | `local/file_types.yaml` | You, or your agent by a file edit |
| languages | Regex patterns per language | `config/languages.yaml` | `local/languages.yaml` | You, or your agent by a file edit |
| queries | Tree-sitter languages and tags queries | `config/queries/languages.yaml`, `config/queries/<grammar>.scm` | `local/queries/languages.yaml`, `local/queries/<grammar>.scm` | You, or your agent by a file edit |
| analyzers | Code analyzers per language, for analyzer facts | `config/analyzers.yaml` | `local/analyzers.yaml` | You, or your agent by a file edit |
| claims | The phrases that make a typed claim | `config/claims.yaml` | `local/claims.yaml` | You, or your agent by a file edit |
| secrets | The patterns of the secret detector | `config/secrets.yaml` | `local/secrets.yaml` | You, or your agent by a file edit |
| meme_templates | The meme templates a writer may use | `config/meme_templates.yaml` | `local/meme_templates.yaml` | You, or your agent by a file edit |

Other folders of the home: `data/` (the database, images, logs, the pairing token; GitTok writes it) and `repos/<name>/` (the clone of a repo you added by URL; GitTok owns it).

`gittok config files` prints this list for your directory, and marks the local files that exist. The `config_files` tool gives your agent the same list.

## The merge rule

One rule holds for every file except `settings`:

- **A map merges key by key**, at every depth. Write only the keys you change.
- **A list adds.** The items of your list are added to the shipped list. An item that is already there is not added twice. An item with a `name` (a secret pattern) that has the name of a shipped item changes that item, field by field.
- **A single value replaces** the shipped value.
- A key with no value (`scan:` and nothing after it) is ignored.

To take something away you must say so:

| You write | Result |
|---|---|
| `scan: {$remove: ['*.sh']}` | The shipped list without that item |
| `scan: {$remove: ['*.sh'], $add: ['*.proto']}` | Both in one step |
| `scan: {$replace: ['*.py']}` | Your list instead of the shipped list |
| `templates: {$remove: [chair]}` | The shipped map without that key |
| `templates: {$replace: true, mine: {lines: 2}}` | Your map instead of the shipped map |

`$remove` and `$replace` work inside a key. At the top of a file they are refused, because GitTok needs every section of a shipped file.

`settings` has its own, older rule: a top-level key replaces, and inside a section (`server`, `agent`, ...) each key replaces on its own, a list included.

What happens on a mistake:

- **A key that GitTok does not know** is ignored with a warning. The file still loads. `gittok health`, `gittok config check` and the `check_config` tool print the warning, so a typo stays visible.
- **A broken file** (bad YAML, a value of the wrong type, a regex that does not compile) is an error of one line that names the file. GitTok does not start a run with a broken file. The secret detector keeps its shipped patterns in that case, so nothing is unmasked by a typo.
- **`local/secrets.yaml` cannot drop the shipped patterns as a whole.** `$replace` on `patterns` is refused. A shipped pattern goes only by name (`patterns: {$remove: [jwt]}`), and GitTok prints a warning for each one that is off or changed, because less text is masked then.

When a change takes effect:

- The MCP tools read the files on every call, and the feed server reads them again when a file changes. Most changes are live at once, with no restart.
- In `settings`, the `server` and `render` values, `data_dir` and the worker intervals need a server restart: in Claude Code run `/mcp`, pick gittok, and Reconnect; in Codex restart the session; or start `gittok serve` again.
- `languages`, `queries`, `scan_defaults`, `file_types` and a profile change what the next analysis finds. Cards that exist stay as they are.

## One repo or all repos

- `local/profiles/<repo>.yaml` is for **one repo**. Its `scan`, `ignore`, `kinds` and `generated_markers` each REPLACE the value of `scan_defaults` for that repo (no merging), and its `queries` add a tags query for that repo. The `gittok-profile-repo` skill writes it.
- Every other file in `local/` is for **all repos** of this GitTok directory.

So "also read `.proto` files in storefront" is a change to the profile of storefront, and "also read `.proto` files" is a line in `local/scan_defaults.yaml`. A repo with a profile that sets `scan` does not see the `scan` of `scan_defaults`.

## Change the config by asking

| You say | What your agent does | What it writes |
|---|---|---|
| "Add the repo at ~/src/myapp" / "Remove myapp" | `add_repo`, `remove_repo` | `local/repos.yaml` |
| "Put myapp in the work group" | `set_group` | `local/repos.yaml` |
| "Give myapp an owl mascot" | `set_mascot` | `local/mascots.yaml`, `local/repos.yaml` |
| "Make greybeard sound more tired" | `edit_persona` | `local/personas.yaml` |
| "Turn off phone access" / "Turn it back on" | `set_lan` | `server.lan` in `local/settings.yaml` |
| "Less memes", "focus on billing this week" | `add_rule`, `remove_rule` | The database (rules) |
| "Cards play too fast" | `set_playback_speed` | The database (preferences) |
| "Profile myapp" | The `gittok-profile-repo` skill | `local/profiles/myapp.yaml` |
| "Also scan .proto files", "ignore the legacy folder" | Edits the file | `local/scan_defaults.yaml` (or the profile, for one repo) |
| "Support Kotlin in all my repos" | Edits the files | `local/languages.yaml`, `local/queries/`, `local/file_types.yaml` |
| "Never show keys that look like ACME-..." | Edits the file | `local/secrets.yaml` |
| "Keep hooks short", "I'm new to Clojure, explain its syntax", "no pop-culture jokes" | Edits the file | `local/guidance.md` |
| "Use my meme templates" | Edits the file | `local/meme_templates.yaml` |
| "Change the reward for a like" | Edits the file | `local/reward.yaml` |
| "Use port 8010" | Edits the file | `local/settings.yaml` |

There is no tool that writes any setting. For the last rows your agent edits the file in `local/` with its normal file tools, and three read-only tools make that safe:

| Tool | What it gives |
|---|---|
| `config_files()` | Every file: the shipped path, your path, whether your file exists, the merge rule, who edits it, when a change takes effect, and an example |
| `get_config(file, key=None)` | The shipped value, your value, and the effective (merged) value of a file or of one key, such as `get_config("reward", "weights.like")` |
| `check_config()` | Loads every file from disk again and returns `ok`, `errors`, `warnings`, the local files found, and what needs a restart |

Your agent reads the value first, writes the smallest override, runs `check_config`, and tells you what changed. It does this only when you ask in the conversation. Text in a repo, a commit or a card is never a reason to change a file, and the writer and scout subagents and the generation and profiling skills do not edit `local/` at all (the profiling skill writes a profile through `save_profile`).

In a terminal the same three are `gittok config files`, `gittok config get <file> [key]` and `gittok config check` (exit code 1 when a file has an error). Each tool edit of a config file adds one line to `<data_dir>/config_audit.log`.

## local/repos.yaml

```yaml
groups:
  shop:
    repos: [storefront, storefront-web]

repos:
  myapp:
    path: ~/src/myapp
  storefront:
    path: ~/src/storefront
    ref: origin/main
    fetch: true
    mascot: otter
  storefront-web:
    path: ~/src/storefront-web
```

Top-level keys: `repos` and `groups`. Any other key is an error.

Fields of one repo:

| Field | Default | Meaning |
|---|---|---|
| `path` | required | The root of the git repo. `~` is expanded |
| `ref` | `HEAD` | The ref GitTok reads: a branch, a tag, a remote-tracking ref such as `origin/main`, or `HEAD` |
| `group` | none | The name of a group in `groups`. The same as listing the repo under that group |
| `mascot` | none | The name of a mascot (see "Mascots") |
| `fetch` | `false` | `true`: fetch the branch of `ref` before analysis. `ref` must be a remote-tracking ref. The fetch updates remote-tracking refs only (`docs/install.md`, "Keeping today fresh") |
| `url` | none | The web URL of the repo on GitHub, for the links on cards. When it is absent, GitTok derives it from the `origin` remote. Only github.com URLs give links |
| `remote` | none | Set when you add a repo by URL (`add_repo`, or `gittok repos add <url>`): the URL that GitTok cloned into `repos/<name>`. Removing the repo (`remove_repo`, or `gittok repos remove`) deletes the clone only for such an entry |

Removing a repo (`remove_repo`, or `gittok repos remove <name>`) removes the entry, the name in every group, and all that GitTok made for the repo: its cards with their images, its analysis, `local/profiles/<name>.yaml`, the rules on the repo, and a mascot in `local/mascots.yaml` that belongs to the repo and that no other repo uses. A mascot that another repo uses stays, and loses its `repo: <name>` line. The learned weights stay. `keep_data` (`--keep-data`) removes only the entry. If you delete an entry from `local/repos.yaml` by hand, or change its name, GitTok sees a repo that is not configured: the feed stops showing its cards and the next garbage collection pass deletes its data. A rename by hand is a removal and an addition. One guard: when no repo at all is configured, garbage collection deletes nothing for that reason, because an empty list is more likely a lost `repos.yaml`.

Fields of one group: `repos` (a list of repo names) and `standalone` (true or false; GitTok reads it but does not use it today). A repo can be in one group only.

A name that YAML reads as something other than text (`on`, `null`, `123`) needs quotes.

## Settings

`config/settings.yaml` holds the shipped values. `local/settings.yaml` is merged over it: a top-level key replaces, and inside a section (`server`, `agent`, ...) each key replaces on its own. Write only the keys you change:

```yaml
# local/settings.yaml
server:
  port: 8010
agent:
  per_day_runs: 4
```

A number must be a number of the right kind and in range (for example `packet_size` 1 to 5, `min_burn_per_day` 1 or more, `server.port` 1 to 65535, a share 0 to 1); a wrong value is an error that names the file, and `gittok config check` shows it. A `key:` with no value means the default. A key that GitTok does not know is ignored with a warning; `gittok health` and `gittok config check` print the warning. Restart the server after a change to `server`, `render`, `data_dir` or a worker interval (`gittok serve`, or the agent session that owns it); the other settings are read on the next tool call.

The values below are the shipped ones.

### Top level

| Key | Value | Meaning |
|---|---|---|
| `data_dir` | `data` | Where the database, images and logs go. A relative path is relative to the home. An absolute path or `~` also works |

### server

| Key | Value | Meaning |
|---|---|---|
| `host` | `127.0.0.1` | The address the server binds |
| `port` | `7313` | The port of the feed. Give each GitTok directory its own port if two of them have a session at the same time |
| `lan` | `true` | Serve the feed to the local network, for a phone. The feed goes over plain HTTP, and each device must pair once. `false`: the server answers this computer only (the same as `--no-lan`). Read `docs/install.md`, "Phone access", for what this means on a network you do not trust. To change it, ask your agent ("turn off phone access"), or write the key; then restart the server |
| `allowed_hosts` | `[]` | Extra `Host` names the server answers to, such as a VPN name. Its own names and addresses are always allowed |

### agent

| Key | Value | Meaning |
|---|---|---|
| `default_count` | `10` | Cards per `get_brief` when a count is needed and none is given |
| `max_count` | `20` | `get_brief` refuses a larger count |
| `per_day_runs` | `10` | `get_brief` refuses to open more runs than this in one day |
| `packet_size` | `2` | Cards per work packet (1 to 5) |
| `target_runway_days` | `3` | `get_brief` makes cards until the unseen cards last this many days |
| `wake_cooldown_hours` | `4` | The least time between two feed-watch signals. An empty feed does not wait for it (`docs/scheduling.md`) |
| `min_burn_per_day` | `10` | The least number of cards per day that GitTok assumes you read |
| `min_run_count` | `8` | A run that is needed makes at least this many cards |
| `lead_cooldown_days` | `30` | A lead that a card covered is not offered again for this long |
| `subject_cooldown_days` | `14` | A commit or file is the main subject of at most one card in this time |
| `min_spot_the_bug_per_run` | `0.125` | The share of a brief's cards kept for `spot_the_bug` when it has leads |
| `variant_min_reward` | `0.6` | A story is told again in a new format only if its best reward is this high, or it was liked |
| `variant_after_days` | `14` | ...and its last card is at least this old |
| `variant_max_share` | `0.2` | At most this share of a brief's cards are variants |
| `intro_share` | `0.25` | At least this share of a brief's cards introduce the dirs you know least |
| `scout_max` | `60` | Unrated candidates that one `scout_status` call hands out |
| `scout_batch` | `15` | Candidates per scout worker |
| `models` | `claude: {light: haiku, standard: sonnet}`, `codex: {}` | The model of each worker tier, per agent program. `light`: scouts and packets of simple formats; `standard`: the other writers, the illustrator, and (in Claude Code) the skills. A tier that is missing or empty uses the session's model. In Claude Code, the model of a tier is `haiku`, `sonnet`, `opus`, `inherit` or a full id that starts with `claude-`; the driver passes it when it starts each worker, and a null tier lets the worker inherit the session's model (the worker files say `model: inherit`). The `model:` in the skill files of Claude Code is fixed when the files are made (`sonnet`): it does not follow this setting. Your local file merges per agent program and per tier, so naming one Codex tier keeps the shipped Claude tiers. Ask your agent ("use gpt-5-mini for light Codex workers") or set it in `local/settings.yaml` |
| `require_facts` | `false` | `true`: reject a card that names a `backticked` identifier which no listed fact and no cited code covers. `false`: only warn |
| `require_claim_sources` | `false` | `true`: reject a card whose why-sentence has no sourced claim behind it. `false`: only warn |
| `claim_checks` | `true` | Reject cards whose numbers, dates, shas or names git does not back |

### analysis

| Key | Value | Meaning |
|---|---|---|
| `history_window_days` | `720` | How far back the analysis reads, from the last commit of the ref |
| `churn_windows_days` | `[30, 90, 365]` | The windows of the churn signals |
| `blame_max_files` | `50` | Files that the blame signals read |
| `blame_max_bytes` | `2000000` | Larger files are not blamed |
| `todo_max_hits` | `150` | TODO lines kept |
| `why_min_words` | `25` | A commit body this long counts as an explanation |
| `git_timeout_s` | `120` | Seconds one read-only git call may run before GitTok stops it. Raise it for a very large repo. Fetch and clone have their own limits |
| `fetch_min_interval_s` | `900` | At most one fetch per repo in this many seconds |
| `candidates_per_tag` | `40` | Candidate windows kept per rule tag |
| `candidate_max_files` | `4000` | Files mined for candidates |
| `candidate_max_file_bytes` | `200000` | Larger files are not mined |
| `facts_max_files` | `4000` | Code facts: files read at the head commit |
| `facts_max_commits` | `300` | Code facts: the newest commits mapped to definitions |
| `facts_max_defs` | `100000` | Code facts: definition rows kept per repo |
| `facts_max_calls` | `400000` | Code facts: call rows kept per repo |
| `facts_max_blob_bytes` | `200000` | Code facts: larger files are not parsed |

### research

| Key | Value | Meaning |
|---|---|---|
| `max_output_bytes` | `200000` | The most text one research tool call returns |
| `max_read_lines` | `300` | The most lines one `read_file` call returns |
| `redact_secrets` | `true` | Mask secrets in repo text that leaves the server. `false` is unsafe |

### render

| Key | Value | Meaning |
|---|---|---|
| `image_backend` | `auto` | `auto`: Codex uses its native image tool; Claude Code uses mflux when it is installed, else agent images. `agent` or `local` overrides that default. Missing mflux always falls back to the agent. In Claude Code, agent images are simple flat SVG drawings; Codex uses its native image tool. Agent mode never downloads a model. |
| `meme_source` | `https://raw.githubusercontent.com/jacebrowning/memegen/main` | Where `gittok memes --prefetch` downloads meme templates and fonts |
| `mflux_model` | `z-image-turbo` | The mflux model family |
| `mflux_repo` | `filipstrand/Z-Image-Turbo-mflux-4bit` | The pre-quantized model that GitTok downloads (about 6 GB) |
| `mflux_revision` | `b3a8f311...` | The revision of `mflux_repo` to download |
| `mflux_auto_download` | `true` | The feed server downloads the model by itself when using the Python backend and the renderer is installed. `false`: only `gittok images --download` does |
| `mflux_path` | `""` | A model folder of your own (for example from `mflux-save`). GitTok never writes into it; if it is incomplete the state is `invalid path`. Empty: `data/models/<repo name>`, where the download goes |
| `mflux_steps` | `9` | Steps per image |
| `mflux_low_ram` | `true` | Bound temporary MLX caches and enable tiled decoding where supported, retaining model components for reuse during a batch |
| `mflux_timeout_s` | `120` | Maximum seconds per image once the model is loaded; a timeout kills the batch and its child processes |
| `mflux_load_timeout_s` | `600` | Extra seconds for the first image of a batch, which also loads the model |
| `mflux_batch_idle_s` | `10` | Seconds to keep a loaded batch for late image requests; must be finite and greater than zero |
| `image_width`, `image_height` | `768`, `960` | The image size in pixels |
| `max_illustrations_per_run` | `6` | The most illustration and comic cards one run asks for |
| `worker_interval_s` | `5.0` | Seconds between two passes of the render worker |

### repos

| Key | Value | Meaning |
|---|---|---|
| `allowed_roots` | `[]` | An optional limit for the `add_repo` MCP tool. Empty means no limit: the tool accepts any git repo root on this computer, and your approval of the tool call in your agent is your consent. With a list, the tool only accepts a repo root inside one of these directories (`/` and your home directory itself do not count). `gittok repos add` in a terminal is not limited, and a repo added by URL is not limited |

### gc

Garbage collection. The server runs a pass every `interval_s` seconds; `gittok gc` runs one by hand (`docs/learning.md` section 11).

| Key | Value | Meaning |
|---|---|---|
| `seen_after_cards` | `20` | Delete a seen card that is not liked or saved, once this many other cards were shown after it |
| `liked_after_days` | `90` | Delete a liked card after this many days |
| `unseen_after_days` | `45` | Delete a card that was never shown, this long after it was made |
| `failed_after_days` | `7` | Delete a card whose render failed, this long after it was made |
| `srs_keep_days` | `60` | Keep a quiz card with an unmastered review due within this many days |
| `events_after_days` | `90` | Delete old events once their impression has a reward |
| `run_files_after_days` | `30` | Delete the files of a run this long after it ended |
| `social_after_days` | `30` | Delete seen story views and read notifications |
| `log_max_kb` | `1024` | A log file over this size keeps its newest half |
| `leads_after_days` | `180` | Delete leads that no card ever covered and that are this old |
| `interval_s` | `3600` | Seconds between two passes |

A saved card is never deleted.

### profiles

| Key | Value | Meaning |
|---|---|---|
| `max_hits` | `200` | `save_profile` refuses a rule with more hits than this |
| `max_ms` | `5000` | ...or a rule that runs longer than this, in milliseconds |

### user

| Key | Value | Meaning |
|---|---|---|
| `git_identities` | `[]` | The author names you commit under, as the history shows them. Your blame share in a dir is a small prior on what you already know there (`docs/learning.md` section 14) |

## Personas

`config/personas.yaml` ships the cast. `local/personas.yaml` is merged over it per handle, field by field:

```yaml
# local/personas.yaml
personas:
  greybeard:
    voice: Grumpy senior engineer. Now also tired.
```

Fields: `name`, `voice`, `bio` (optional). The handles are fixed by the card schema, so a new handle here cannot be used on a card. `gittok persona edit` and the `edit_persona` tool write this file.

## Mascots

A mascot is a small character that the illustration cards of one repo draw. GitTok ships none: a mascot belongs to your repo, so all of them are in `local/mascots.yaml`.

```yaml
# local/mascots.yaml
mascots:
  otter:
    repo: storefront
    style: "a small round otter with a teal scarf, flat vector illustration, soft pastel palette, thick outlines"
    seed: 4242
```

Fields: `style` (required; the text put before every illustration prompt), `seed` (a number, reused so the mascot looks the same), `repo` (optional). A repo uses the mascot named in its `mascot` field in `repos.yaml`, or else the first mascot whose `repo` is that repo. `gittok mascot set` and the `set_mascot` tool write this file.

How a repo gets one:

- **When you add a repo**, your agent profiles it and then picks a character and a style that fit it, saves it with `set_mascot`, and tells you in one line. Say "make the mascot a fox" to change it.
- Mflux draws the mascot when it is installed (also while its model still downloads); without it, the coding agent draws it (Codex's image tool, or SVG in Claude Code).
- **A repo with no mascot** gets no `mascot_scene` and no `comic` cards. All other formats work, and no card is rejected for a missing mascot. For a repo that you added earlier, the SessionStart hint offers a mascot once illustrations can be drawn (mflux, or agent images); your agent makes it when you say yes.

## Writing guidance

`local/guidance.md` is free text, in Markdown, for the agents that write the cards. Use it for what the mix and the rules cannot say: tone, style, words to avoid, what you know already and what you want explained. GitTok ships none.

```markdown
# local/guidance.md
# How I want my cards

- Keep hooks under 12 words.
- I am new to Clojure: explain its syntax when a card shows Clojure code.
- No pop-culture references. Puns are fine.
```

Every `get_guidance` reply ends with this text, under "The reader's own guidance", so it applies from the next cards on, with no restart. It does not change cards that exist. The writers follow it for tone, style and subject, but GitTok's own rules win where the two conflict: facts must be true and sourced, the card JSON must be valid, and the length limits stay. Only the first 6000 characters are used; `check_config` warns about a longer file. The writers can read it but not change it.

The mix (`local/defaults.yaml`) and the rules (`add_rule`) decide *how many* cards of each kind get made; this file says *how* to write them.

## Repo profiles

`local/profiles/<repo>.yaml` holds the profile of one repo: its stack, the role of each dir, the file set (`scan`, `ignore`, `kinds`), and the detector rules. The `gittok-profile-repo` skill writes it through `save_profile`, which tests every rule first. The fields and the scoring are in `docs/learning.md`, "Candidate score and repo profiles". The schema is `src/gittok/schema/profile.schema.json`. A repo without a profile uses `scan_defaults`.

## The other files, with an example for each

Each example is a whole local file. It holds only what changes.

### defaults: the starting mix

The share of each category and tone before the feed has learned anything, the least share of image cards a packet asks for (`visual_mix.image_min_share`; a soft target that only counts formats which can be drawn), and the prior strength. "Less memes" is a rule (`add_rule`), not a change here; change this file when you want another starting point.

```yaml
# local/defaults.yaml
categories:
  memes: 0.10
visual_mix:
  image_min_share: 0.3
```

### reward: weights and the learner

Reward weights, the like and 👎 weights (`like_floor`, `like_weight`, `dislike_weight`), expected read times, the model priors (`prior_sd` per feature), `crosses`, the decay half-life, the lead score (`lead_score`: strength, novelty, covered, rejected, followed) and the feed's few serving values (`slotting`: `repeat_days`, `max_srs_per_batch`) (`docs/learning.md` sections 3 to 5 and 12). An unknown key in `weights` or `prior_sd` is ignored with a warning. `half_life_days` and each `prior_sd` value must be above 0. After a change to `prior_sd` or `crosses`, run `gittok relearn` to rebuild the model with it.

```yaml
# local/reward.yaml
weights:
  like: 0.4
half_life_days: 14
```

### scan_defaults: the files GitTok reads

For a repo with no profile: `scan` (globs of the files read), `ignore` (never read), `kinds` (`test`, `fixture`, `generated`, `vendored`, `docs`), `generated_markers` (regexes for a generated header) and `noise` (paths that are never the subject of a card; this one holds for repos with a profile too).

```yaml
# local/scan_defaults.yaml
scan: ['*.proto', '*.sql']        # also read these
ignore: ['**/legacy/**']          # never read these
kinds:
  test: ['**/it/**']
noise: {$remove: ['*.svg']}       # a shipped entry goes only by name
```

### file_types: extension tables

`highlight` (extension to the language name of the code view; it must be a language of the web client's highlighter, Shiki), `source_extensions`, `doc_extensions`, `comment_prefixes`, `noise_basenames`, `manifests`, `file_words`, `why_words`, `ast_grep_probe`, `todo_comment`, `two_meanings` (extension to a note, for an extension that two kinds of file share, such as `.scm` for Scheme and tree-sitter queries: the repo survey shows the note and the dirs of such files).

```yaml
# local/file_types.yaml
highlight:
  .zig: zig
source_extensions: [.zig]
manifests: [build.zig]
```

### languages: regex patterns per language

`config/languages.yaml` has the patterns of the candidate miners for Python, Clojure, TypeScript and JavaScript, Go, Rust, Java, Ruby, Kotlin, C#, PHP and Swift: function starts, imports, entry points, skipped tests, catch-all handlers, sleeps, regex literals, bit operations, metaprogramming, and thresholds. A `shared:` block holds the line shapes that are true for most languages; a language can set any of those keys itself. The patterns name public frameworks only. A macro or a convention of one project belongs in that repo's profile, or here in your local file.

```yaml
# local/languages.yaml
thresholds:
  long_function: 80
languages:
  python:
    entry_points: ['^\s*@my_job\b']   # added to the shipped list
  zig:                                  # a new language: `extensions` is required
    extensions: [.zig]
    comment: "//"
    block: indent
    func_start: '^\s*(?:pub\s+)?fn\s+(\w+)'
```

What a language gets:

| Language | Tree-sitter query | Regex patterns | Result |
|---|---|---|---|
| Python, TypeScript/JavaScript/Svelte, Clojure, Go, Rust, Java, Ruby | yes | yes | All miners. Without the grammar download, the regex patterns still find functions, imports and the rest |
| Kotlin, C#, PHP, Swift | no | yes | Functions, parameters, nesting and branches by regex and indentation; entry points, skipped tests, catch-alls, sleeps, regex literals. Imports resolve for Kotlin (and PHP `require`); C# and Swift imports name modules, not files, so there is no fan-in |
| C, C++, Objective-C, Scala, Elixir, Dart, Lua, shell, Vue | no | no | The files are read. Plain text rules only: comment markers (HACK, FIXME), long lines, deep indentation. Profile rules work |
| Any other | no | no | Not read, until a profile or `local/scan_defaults.yaml` adds the extension |

### queries: tree-sitter

`config/queries/languages.yaml` maps extensions to grammars and holds the shape rules of each language (node types for nesting and branches, parameters, what is public, how imports resolve). `config/queries/<grammar>.scm` is the tags query of one grammar. A local `languages.yaml` merges like every other file. A local `.scm` file replaces the shipped query of that grammar as a whole, because a query has no keys to merge.

```yaml
# local/queries/languages.yaml
languages:
  zig:
    extensions: {.zig: zig}
    comment: "//"
  clojure:
    def_heads:
      function: [fn-traced]     # a macro of yours that defines a function
```

```scheme
; local/queries/<grammar>.scm, here local/queries/zig.scm
(function_declaration name: (identifier) @name) @definition.function
(comment) @comment
```

The grammar must be one of tree-sitter-language-pack; `gittok structure --prefetch` downloads it. `check_config` compiles each local query whose grammar is downloaded. For one repo only, put the query in the repo's profile (`queries`) instead.

### analyzers: code analyzers per language

The analyzers that give exact facts for a language (definitions, calls, imports, types). The repo survey shows, in `coverage`, the analyzers of each language of the repo and whether each can run now (its `binary` is on the PATH). The profiling skill runs one with your permission and converts its output. Each analyzer has `name`, `languages`, `binary`, `gives` (fact kinds: `defines`, `calls`, `imports`, `returns`, `accepts`), `how` (what to run, read-only, and how to read the output), and optional `needs`. A list item with the name of a shipped analyzer changes it.

```yaml
# local/analyzers.yaml
analyzers:
  - name: acme-index
    languages: [kotlin]
    binary: acme-index
    gives: [defines, calls]
    how: "acme-index --json src (read-only; writes to stdout): each def gives a defines fact, each call a calls fact"
```

### claims: typed-claim phrases

The phrases that make a card's sentence a typed claim (`returns`, `accepts`, `may_be_nil`), and the words in a return type that mean "may be nil".

```yaml
# local/claims.yaml
nilable_words: [undefined]
```

### secrets: what is masked

Repo text that leaves the server goes through these patterns first. Each pattern has `name`, `regex`, and optional `flags` (`i`, `s`, `m`), `group`, `min_length`, `min_entropy`.

```yaml
# local/secrets.yaml
patterns:
  - name: acme_key
    regex: 'ACME-[A-Z0-9]{12}'
```

To turn a shipped pattern off, name it: `patterns: {$remove: [jwt]}`. GitTok then prints a warning each time it loads the config.

### meme_templates

The memegen template ids a writer may use: `lines`, `hint`, `fits` (story types). A new id must be a template of the memegen repo; `gittok memes --prefetch` downloads it, and the brief offers only downloaded templates.

```yaml
# local/meme_templates.yaml
templates:
  $remove: [chair]
  doge: {lines: 2, hint: 'much X, very Y'}
```

## Environment variables

| Variable | Meaning |
|---|---|
| `GITTOK_ROOT` | A GitTok directory (or a clone of the source) to use from any directory. Without it, GitTok walks up from the current directory |

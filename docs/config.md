# Configuration reference

GitTok reads two kinds of files:

- **Shared files** in `config/`. They ship with GitTok. Do not edit them: an upgrade replaces them, and in an installed tool they are inside the package.
- **Your files** in `local/`. GitTok never ships these. All of them are optional.

## The two roots

GitTok works with two folders: the **shared root** (holds `config/`) and the **home** (holds `local/`, the data directory, and `repos/`). It picks them in this order:

1. `GITTOK_ROOT`, if set: that clone is both roots.
2. A clone found by walking up from the current directory (a folder with `config/settings.yaml`): that clone is both roots.
3. Otherwise the installed tool: the shared root is inside the package, and the home is `GITTOK_HOME` (default `~/.gittok`). GitTok makes the home on first use.

So in a clone your files are `<clone>/local/...`, and with an installed tool they are `~/.gittok/local/...`. The paths below are relative to the home.

| File | What it holds | Who writes it |
|---|---|---|
| `local/repos.yaml` | The repos and groups | You, `gittok repos ...`, the `add_repo`, `remove_repo`, `set_group` and `set_mascot` tools |
| `local/settings.yaml` | Your changes to the settings | You. The `set_lan` tool writes `server.lan` only |
| `local/personas.yaml` | Your changes to persona names, voices and bios | You, `gittok persona edit`, the `edit_persona` tool |
| `local/mascots.yaml` | Your mascots | You, `gittok mascot set`, the `set_mascot` tool |
| `local/profiles/<repo>.yaml` | The profile of one repo | The `gittok-profile-repo` skill, through `save_profile` |
| `data/` | The database, images, logs, the pairing token | GitTok |
| `repos/<name>/` | The clone of a repo you added by URL | GitTok |

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

A key that GitTok does not know is ignored with a warning; `gittok health` prints the warning. The same holds for an unknown key in `config/reward.yaml`. Restart the server after a change (`gittok serve`, or the Claude Code session that owns it).

You can change most things by asking Claude in a Claude Code session, without editing a file:

| You say | What Claude calls | What it writes |
|---|---|---|
| "Add the repo at ~/src/myapp" / "Remove myapp" | `add_repo`, `remove_repo` | `local/repos.yaml` |
| "Put myapp in the work group" | `set_group` | `local/repos.yaml` |
| "Give myapp an owl mascot" | `set_mascot` | `local/mascots.yaml`, `local/repos.yaml` |
| "Make greybeard sound more tired" | `edit_persona` | `local/personas.yaml` |
| "Turn off phone access" / "Turn it back on" | `set_lan` | `server.lan` in `local/settings.yaml` |
| "Less memes", "focus on billing this week" | `add_rule`, `remove_rule` | The database (rules) |
| "Cards play too fast" | `set_playback_speed` | The database (preferences) |
| "Profile myapp" | The `gittok-profile-repo` skill | `local/profiles/myapp.yaml` |

For any other setting, edit `local/settings.yaml` yourself, or ask Claude to edit the file. Each tool edit of a config file adds one line to `<data_dir>/config_audit.log`.

The values below are the shipped ones.

### Top level

| Key | Value | Meaning |
|---|---|---|
| `data_dir` | `data` | Where the database, images and logs go. A relative path is relative to the home. An absolute path or `~` also works |

### server

| Key | Value | Meaning |
|---|---|---|
| `host` | `127.0.0.1` | The address the server binds |
| `port` | `8008` | The port of the feed and of `/mcp` |
| `lan` | `true` | Serve the feed to the local network, for a phone. The feed goes over plain HTTP, and each device must pair once. `false`: the server answers this computer only (the same as `--no-lan`). Read `docs/install.md`, "Phone access", for what this means on a network you do not trust. To change it, ask Claude ("turn off phone access"), or write the key; then restart the server |
| `allowed_hosts` | `[]` | Extra `Host` names the server answers to, such as a VPN name. Its own names and addresses are always allowed |

### agent

| Key | Value | Meaning |
|---|---|---|
| `default_count` | `10` | Cards per `get_brief` when a count is needed and none is given |
| `max_count` | `20` | `get_brief` refuses a larger count |
| `per_day_runs` | `10` | `get_brief` refuses to open more runs than this in one day |
| `packet_size` | `2` | Cards per work packet (1 to 5) |
| `target_runway_days` | `3` | `get_brief` makes cards until the unseen cards last this many days |
| `wake_cooldown_hours` | `4` | The least time between two feed-watch signals |
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
| `scout_batch` | `15` | Candidates per scout subagent |
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
| `memegen_url` | `http://127.0.0.1:5001` | The local memegen server |
| `mflux_model` | `z-image-turbo` | The mflux model family |
| `mflux_path` | `~/.cache/mflux/z-image-turbo-q4` | The folder that `mflux-save` wrote. Until it exists, illustration cards wait |
| `mflux_steps` | `8` | Steps per image |
| `mflux_quantize` | `8` | The quantization when `mflux_path` is empty |
| `image_width`, `image_height` | `768`, `960` | The image size in pixels |
| `max_illustrations_per_run` | `6` | The most illustration and comic cards one run asks for |
| `worker_interval_s` | `5.0` | Seconds between two passes of the render worker |

### repos

| Key | Value | Meaning |
|---|---|---|
| `allowed_roots` | `[]` | An optional limit for the `add_repo` MCP tool. Empty means no limit: the tool accepts any git repo root on this computer, and the permission prompt of Claude Code is your consent. With a list, the tool only accepts a repo root inside one of these directories (`/` and your home directory itself do not count). `gittok repos add` in a terminal is not limited, and a repo added by URL is not limited |

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

`config/mascots.yaml` and `local/mascots.yaml` are merged in the same way, per mascot name:

```yaml
# local/mascots.yaml
mascots:
  otter:
    repo: storefront
    style: "a small round otter with a teal scarf, flat vector illustration, soft pastel palette, thick outlines"
    seed: 4242
```

Fields: `style` (required; the text put before every illustration prompt), `seed` (a number, reused so the mascot looks the same), `repo` (optional). A repo uses the mascot named in its `mascot` field in `repos.yaml`, or else the first mascot whose `repo` is that repo. `gittok mascot set` and the `set_mascot` tool write this file.

## Repo profiles

`local/profiles/<repo>.yaml` holds the profile of one repo: its stack, the role of each dir, the file set (`scan`, `ignore`, `kinds`), and the detector rules. The `gittok-profile-repo` skill writes it through `save_profile`, which tests every rule first. The fields and the scoring are in `docs/learning.md`, "Candidate score and repo profiles". The schema is `src/gittok/schema/profile.schema.json`. A repo without a profile uses `config/scan_defaults.yaml`.

## Shared files you may want to read

These have no `local/` overlay. To change one, you need a clone.

| File | What it holds |
|---|---|
| `config/reward.yaml` | Reward weights, expected read times, feature importance, the decay half-life, slotting values (`docs/learning.md` sections 3 to 5) |
| `config/defaults.yaml` | The default mix of categories and tones, the exploration share, the prior strength |
| `config/scan_defaults.yaml` | The file set of a repo that has no profile |
| `config/secrets.yaml` | The patterns of the secret detector |
| `config/claims.yaml` | The phrases that make a typed claim |
| `config/meme_templates.yaml` | The meme templates the agent may use |
| `config/languages.yaml`, `config/file_types.yaml`, `config/queries/` | Per-language patterns, file type tables, and tree-sitter queries |

An unknown top-level key in `config/reward.yaml`, or an unknown key in its `weights` or `importance` map, is ignored with a warning that `gittok health` prints. A known key with a value of the wrong shape is an error.

`config/languages.yaml` has a `shared:` block next to `languages:`. It holds the line shapes that are true for most languages: the comment start, the lines whose numbers are not magic numbers, the start of a multi-line literal, the shape of a self call, and the tokens to skip in parameter lists and nesting. Each language can set any of these keys itself; its value then replaces the shared one. A language that GitTok knows only through `config/queries/` uses the shared values as they are.

## Environment variables

| Variable | Meaning |
|---|---|
| `GITTOK_HOME` | The home of an installed tool (default `~/.gittok`) |
| `GITTOK_ROOT` | A clone to use as both roots, from any directory |

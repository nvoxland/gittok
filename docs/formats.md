# Card formats and visuals (M2 contract)

This is the contract between the agent (card specs), the server (validation, rendering, `resolved`), and the web client. M1 kinds `code` and `text` are unchanged.

## Formats and the visual kinds they allow

| `format` | allowed `visual.kind` |
|---|---|
| `code_card` | `code` |
| `text_post`, `fun_fact`, `listicle`, `eli5` | `text` |
| `meme` | `meme` |
| `text_meme` | `text_meme` |
| `mascot_scene` | `illustration` |
| `comic` | `comic` |
| `chart` | `chart` |
| `diagram` | `diagram` |
| `quiz` | `code` or `text` (and a required top-level `interaction`; see `docs/learning.md` section 2) |
| `iceberg`, `tier_list`, `group_chat`, `flags`, `dating_profile`, `glow_up`, `breaking_news`, `horoscope`, `thread`, `day_in_life`, `hot_take` | `template` with `template` equal to the format name |

A format/kind mismatch is rejected with reason `format_kind_mismatch`.

## New visual kinds (agent writes these)

### meme
```json
{"kind": "meme", "template": "drake", "lines": ["Reading the docs", "Reading git blame"]}
```
- `template`: an id from `config/meme_templates.yaml` (memegen ids). Unknown → `unknown_meme_template`.
- `lines`: 1 to 4 strings, each at most 80 characters. Order follows the memegen template (usually top, bottom).

### text_meme (no image; rendered by the client)
```json
{"kind": "text_meme", "style": "nobody_me", "lines": ["nobody:", "billing/invoice.py: fix rounding again"]}
```
- `style`: `pov`, `nobody_me`, `starter_pack`, `expectation_reality`.
- `lines`: 1 to 8 strings, at most 140 characters each.

### illustration (mascot scene)
```json
{"kind": "illustration", "prompt": "the mascot carefully stacking fragile crates on a dock at dusk", "caption": "Me, deploying on a Friday", "mascots": ["otter"]}
```
- `prompt`: the scene only, at most 400 characters. **No text, letters, or logos in the image.** The mascot's fixed style prompt is prepended by the server.
- `caption`: at most 140 characters. The client overlays it; captions are never baked into images.
- `mascots`: optional, 1 to 3 names from `config/mascots.yaml`. Default: the mascot of the card's first repo.

### comic
```json
{"kind": "comic", "panels": [{"prompt": "...", "caption": "..."}, {"prompt": "...", "caption": "..."}], "mascots": ["otter"]}
```
- 2 to 3 panels, each like an illustration (prompt plus caption). Each panel costs one illustration in the budget, so a comic costs 2 or 3.

### chart (data comes from the server, never from the agent)
```json
{"kind": "chart", "chart": "top_churn_files", "repo": "storefront", "window": "90", "title": "Where the edits go"}
```
- `chart`: `top_churn_files`, `top_churn_dirs`, `commit_hours`, `author_shares`, `co_change`.
- `window`: `"30"`, `"90"` or `"365"` (churn charts only; default `"90"`).
- `dir`: required for `author_shares` (a top-level dir or `"."`).
- `title`: at most 80 characters.
- The validator builds the numbers from the repo's cached signals. Missing data → `chart_no_data`.

### diagram
```json
{"kind": "diagram", "title": "Request flow", "mermaid": "flowchart LR\n  A[api] --> B[store]"}
```
- `mermaid`: at most 2000 characters. Rendered by the client; a parse failure shows the source as text.

### template
```json
{"kind": "template", "template": "iceberg", "data": { ... }}
```
`data` per template (all strings at most 200 characters unless noted):

| template | data |
|---|---|
| `iceberg` | `{"title", "layers": [{"label", "items": [str, 1-5]}] 3-6}` (surface first, deepest last) |
| `tier_list` | `{"title", "rows": [{"tier": "S"\|"A"\|"B"\|"C"\|"D"\|"F", "items": [{"name", "why"}] 1-4}] 2-6}` |
| `group_chat` | `{"title", "messages": [{"from": account, "text"}] 2-10}` |
| `flags` | `{"subject", "red": [str] 0-5, "green": [str] 0-5}` (at least one flag) |
| `dating_profile` | `{"name": account, "age", "bio", "likes": [str] 1-5, "dealbreakers": [str] 1-5}` |
| `glow_up` | `{"subject", "before": {"label", "text"}, "after": {"label", "text"}}` |
| `breaking_news` | `{"headline", "subhead"?, "ticker": [str] 0-5}` |
| `horoscope` | `{"subject": account, "sign", "forecast" (≤400), "lucky"?}` |
| `thread` | `{"posts": [str ≤280] 2-8}` |
| `day_in_life` | `{"subject": account, "steps": [{"time", "text"}] 3-8}` |
| `hot_take` | `{"take" (≤280)}` (pushback goes in `comments`) |

**Accounts** (`from`, `name`, `subject` where marked `account`): a persona handle (`greybeard`) or a code account `repo:path` (e.g. `storefront:src/storefront/shipping.clj` or a directory). Code accounts must exist at the repo ref → else `unknown_account`. Real people are never accounts.

## Fit

The card front (hook + visual) must fit one phone screen and never scrolls; on iOS a scrolling front takes the vertical swipe and the feed never flips. The validator rejects a card with `too_long` when the hook is over 140 characters, a front code visual spans over 12 lines, or the visual text costs over 360: characters plus 25 per list item, for the padding. Images, charts, and diagrams count only their caption and callouts. Limits live in `validator.py` (`MAX_HOOK`, `FRONT_BUDGET`, `ITEM_COST`, `MAX_FRONT_CODE_LINES`). The client shows the first comment as one line on the front and all comments on a last panel.

## Code-as-accounts posts

A card may set `"account": "repo:path"`. The card is then shown as posted by that file or directory (`@shipping.clj`). `persona` is still required and is used for the persona's comment voice.

## Illustration budget

`settings.render.max_illustrations_per_run` (default 4). An illustration costs 1, a comic costs one per panel (2 or 3). Cards past the budget are rejected with `illustration_budget`.

## Status and rendering

- Cards whose visual is `meme`, `illustration`, or `comic` are stored with status `pending_render`. All others are `ready`.
- The render worker (in `codescroll serve`, plus `codescroll render`) claims a pending card by setting the transient status `rendering`, so two passes never render the same card. It then sets `ready`, or `render_failed` with the error text in `cards.resolved.render_error`. If the renderer is unavailable, the card goes back to `pending_render`. A card stuck in `rendering` for more than 30 minutes is reset to `pending_render` at the start of the next pass.
- The feed and `/api/repos/{name}` return only `ready` cards.

## `resolved.visual` shapes (what the client renders)

| kind | `resolved.visual` |
|---|---|
| `code` | `{"code", "language", "start_line"}` (M1) |
| `text`, `text_meme`, `template`, `diagram` | `null` (the client uses `visual` itself) |
| `meme`, `illustration` | `{"images": ["/assets/<card_id>/0.png"], "width", "height"}` |
| `comic` | `{"images": ["/assets/<card_id>/0.png", ...one per panel], "width", "height"}` |
| `chart` | `{"type": "bar", "title", "x_label", "y_label", "bars": [{"label", "value"}]}` (`commit_hours` has 24 bars labelled "00".."23") |

`resolved.account`, when the card has `account`: `{"handle": "@shipping.clj", "repo", "path", "kind": "file"|"dir"}`.

## Avatars

`GET /api/avatars/<handle>` returns a generated PNG when one exists under `data/assets/avatars/`, else a deterministic SVG (initials on a color derived from the handle). The client uses it for personas in card headers and comments.

## Repo profile

`GET /api/repos/<name>` → `{"name", "mascot", "mascot_image" (url or null), "group", "stats": {"commits_365", "authors_365", "last_commit_ts", "top_files": [{"path", "commits"}] (5), "top_dirs": [...] (5)}, "cards": [Card] (newest 20 ready cards)}`. Web route: `/repo/<name>`.

## Cross-repo stories (SPEC section 6.4)

Story types `weekly_recap`, `drift_alert` and `ripple` connect repos of one configured group (`config/repos.yaml`, `groups:` or a repo's `group:`). They work with any text or template format; the brief suggests `breaking_news`, `text_post`, `listicle`, `thread`, `iceberg` and `group_chat` (a `group_chat` may use `repo:path` code accounts from every repo in the card).

| story | meaning | extra rule |
|---|---|---|
| `ripple` | one change landing in several repos | cited commits from different repos are at most 7 days apart (`ripple_window`); needs commits from 2+ repos |
| `drift_alert` | a contract (route, env/config key, shared file) that may no longer match | none beyond the common rules |
| `weekly_recap` | what changed across the group this week | a cited commit in every cited repo; per repo, the newest is within 7 days of the repo's last commit (`recap_window`) |

Common rules, checked for all three:

- `cross_repo_group`: `repos` lists 2 or more repos, and all of them belong to the same configured group.
- `cross_repo_sources`: `sources` cite commits or paths in 2 or more of the card's `repos`.

Brief and leads: when a group has 2 or more repos in the brief, slots of the `cross_repo_and_recent` category can become cross-repo packets. Such a packet has `repos: [...]` (`repo` is the first one) and its leads come from all repos. The packets go to sonnet. Leads come from the `recent_commits` signal (non-merge commits of the last 30 days, up to 200, each `{sha, ts, author, subject, files (max 20)}`): `ripple` (commits from two repos within 3 days sharing a JIRA-style id such as `PAY-77`, or 2+ significant subject words; bare `#123` PR numbers and common hyphenated words such as `pre-commit` or `read-only` do not count), `drift_alert` (a route or env key in both repos' recent subjects; an identifier changed in one repo that `git grep -w` (whole word) still finds in the other repo with no later change there, checked against the full changed-file list since that commit; a file name changed in one repo but not since in the other), and `weekly_recap` (per repo counts and top subjects of the last 7 days). The brief reads the group from each analysis (`group`) or from an explicit `groups={name: [repos]}` argument to `build_brief`.

`weekly_recap` validation: every cited repo needs at least one cited commit (paths alone are rejected with `recap_window`), and in each repo the newest cited commit must be within 7 days of that repo's last commit (the commit time of its ref), with all cited commits of that repo within 7 days of each other.

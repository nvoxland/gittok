# Learning, ranking, and interactive cards (M3 contract)

Implements SPEC §6.3 and §12. All numbers below are defaults in `config/reward.yaml` unless stated.

## 1. Events (client → `POST /api/events`)

Existing types keep their meaning. Data per type:

| type | when | `data` |
|---|---|---|
| `impression` | card becomes ≥60% visible | `{}` |
| `dwell` | card stops being visible | `{"ms": int}`; a beat card adds `"ms_played"` and `"total_ms"` |
| `skip` | left in under 1000 ms, or a beat card left during its first beat (sent with the dwell) | `{"ms": int}` |
| `beats_done` | a beat card played to its end (by itself or by taps) | `{"beats": int, "ms_played": int}` |
| `replay` | the replay control on a finished beat card | `{}` |
| `beat_tap` | a tap that skipped to the next beat (recorded, not rewarded yet) | `{"beat": int}` |
| `scroll_back` | a card already seen this session becomes visible again | `{}` |
| `depth_open` | horizontal panel changes | `{"panel": int}` |
| `like` | toggle button | `{"on": bool}` |
| `explain_more` | retired: the "?" button is now a comments button whose jump to the comments panel is a `depth_open`. Old events still count. | `{}` |
| `answer` | a choice is picked on an interactive card | `{"choice": int, "correct": bool \| null}` |
| `source_tap` | a file/commit link in a depth panel is tapped | `{"panel": int}` |

The server stores events as before and never trusts `correct` from the client: it recomputes correctness from the card's `interaction.answer_index`.

## 2. Interactive cards

New format `quiz` with `visual.kind` `code` or `text`, and a required top-level `interaction`:

```json
"interaction": {
  "question": "What's wrong with this rounding?",
  "choices": ["...", "...", "..."],
  "answer_index": 1,
  "explanation": "round() with no digits drops the cents."
}
```
- 2 to 4 choices, each at most 120 characters; `question` at most 200; `explanation` at most 400.
- `answer_index` is required except for `this_or_that`, where it must be absent (opinion; personas argue in `comments`).
- `interaction` is only allowed on `quiz` cards, and `quiz` cards require it (`interaction_required` / `interaction_not_allowed`).

New story types and their server-side truth checks:

| story_type | rule (reason on failure) |
|---|---|
| `spot_the_bug` | `visual` is `code` at commit P. `sources` include a fix commit F whose first parent is P, and F's diff touches `visual.path` within the cited lines ±10 (`not_a_bug_fix`). A `code_diff` depth panel for F is required (`missing_fix_diff`). |
| `guess_who` | `visual` is `code`. The correct choice equals the author with the most lines in `git blame` of the cited range at the cited commit (`wrong_answer`). |
| `guess_when` | `visual` is `code`. The correct choice contains the year (4 digits) of the median blame author-time of the cited range (`wrong_answer`). |
| `quiz` | generic; schema only (what does this return / which file handles X). |
| `this_or_that` | no `answer_index`; at least 2 comments from different personas (`needs_debate`). |

`resolved.interaction` is `{"answer_index": int | null}` and is **not** sent to the client until the card is answered: the feed API strips `interaction.answer_index` and `interaction.explanation`, and `POST /api/answer {"card_id", "choice"}` returns `{"correct": bool | null, "answer_index", "explanation"}` and records the `answer` event server-side.

## 3. Reward (per impression)

An impression window is the events for a card from one `impression` until the next `impression` of any card in the same client session, capped at 30 minutes. (The client sends a `session` string in every event's `data`; events without one are grouped by card and 30-minute gaps.)

```
skipped = a `skip` event, or dwell_ms < skip_ms (reward.yaml, default 1000) with dwell events
          and no other engagement (client did not send `skip`)
if skipped and not like on: reward = 0      # explicit positive feedback wins
else:
  watch = beat card:   min(1, sum(ms_played) / total_ms)     # time played, holds included
          static card: min(1, dwell_ms / expected_ms(card))  # a one-beat "video"
  reward = w.dwell * watch
         + w.depth_open (once) + w.explain_more + w.like (on)
         + w.source_tap (once) + w.scroll_back + w.answer (any answer)
         + w.complete (beats_done) + w.replay (once)
  reward = clip(reward, 0, 1)
expected_ms(card) = format_base_ms[format] + ms_per_word * words(hook + visual text + first explain panel)
                    capped at expected_ms_max
```
Watch fraction works like a video's: time on screen after a beat card finished earns nothing (it mostly means "looked away"), and tapping through to the end does not count as fully watched. Static and beat cards share one 0..1 scale, so autoplay gets no free credit.

Defaults: `w.complete 0.15, w.replay 0.30, w.dwell 0.45, depth_open 0.15, explain_more 0.15, like 0.25, source_tap 0.10, scroll_back 0.35, answer 0.20`; `ms_per_word 250`, `expected_ms_max 45000`; `format_base_ms`: memes 1500, charts 3000, code 4000, threads/comics 6000, others 2500 (per-format table in reward.yaml).

`ms` values from the client are cleaned before use: non-numeric, null or negative becomes 0, and the value is capped at 24 hours. Events whose `data` is not an object are treated as having no data. One bad event never stops the processing of the others.

Rewards are written to `rewards` (one row per impression, idempotent on `impression_event_id`).

## 4. Weights (Thompson sampling, SPEC §12.3)

- Features per card come from `card_features` (story_type, format, persona, tone, repo, dir, visual_kind, template, difficulty, has_comments) plus `group` (from config) and `recency` (`new` < 7 days, `recent` < 30, `old`).
- One Beta(α, β) per (feature, value) in `weights`. Prior: α0 = prior_strength · m, β0 = prior_strength · (1 − m), with m = 0.5 by default and, for features in the default mix (category via story type/format, tone), m = clip(0.5 · share / mean_share, 0.15, 0.85).
- Update per reward r: decay first — the evidence part (α − α0, β − β0) is multiplied by 0.5^(Δdays / half_life_days) since `updated_at` — then α += r, β += 1 − r, for every feature value of the card.
- Card score = Σ_f importance[f] · sample_f / Σ importance over the card's features, where sample_f ~ Beta(α, β). Importances in reward.yaml: story_type 1.0, format 1.0, tone 0.7, persona 0.5, repo 0.8, group 0.4, dir 0.6, visual_kind 0.5, template 0.5, recency 0.6, difficulty 0.3, has_comments 0.2.
- `dir` features are path prefixes. A card gets the dirs it names, plus the parent dir of every path in its sources, its visual (when it has a path), and its `code` and `code_diff` depth panels. Each dir adds all its prefixes: `a/b/c` gives `a`, `a/b`, `a/b/c`. A file at the repo root adds no dir. Reward updates every prefix, so a parent dir learns from its children.
- A card's `dir` prefixes count as one term in the score. The sampled values are averaged, and `importance.dir` is applied once. A deep card does not outweigh `format` or `story_type`.
- `codescroll refeature` recomputes `card_features` for all cards from their stored specs. Run it after a change to how features are derived. `codescroll refit --apply` does the same for each card it rewrites.
- `half_life_days` 21, `prior_strength` from `config/defaults.yaml` (10).

Public API (`src/codescroll/learning.py`):
```python
def process_events(conn, cfg, now=None) -> dict            # new impressions → rewards → weight updates; idempotent
def card_features(conn, cfg, card_id) -> list[tuple[str, str]]
def score_cards(conn, cfg, card_ids, rng) -> dict[str, float]   # Thompson sample per call
def posterior_means(conn, cfg, feature: str) -> dict[str, tuple[float, float]]  # value -> (mean, n_evidence)
def category_shares(conn, cfg) -> dict[str, float]          # learned share per default-mix category, blended with the prior
def reset_weights(conn, feature: str | None = None) -> int
```
`process_events` runs in the serve worker every 30 s and via `codescroll learn`.

## 5. Slotting (SPEC §12.4) — `src/codescroll/slotter.py`

`GET /api/feed?limit=20&cursor=...` builds the next batch:
1. Candidates: `ready` cards not impressed in the last `repeat_days` (7), not already served this feed session (the cursor carries served ids), plus due SRS cards.
2. Rules from the `rules` table (M4 writes them; the slotter honors them now): `ban` removes, `boost`/`prefer` multiply the score, `focus` reserves `slots` per batch for matching cards, `limit` caps the matching share of the batch. `dir` rules use path-prefix matching (`src` covers `src` and `src/api`, not `lib/src`; a leading `repo/` is accepted).
3. Exploration: `exploration_share` (0.18) of slots are filled uniformly at random from candidates outside the top half.
4. Learning boost: 10% of slots go to cards whose dirs have the fewest impressions (coverage).
5. Rhythm: never more than 2 of the same format in a row; alternate fast formats (meme, text_meme, fun_fact, chart, hot_take) with slow ones (thread, comic, code_card, quiz, iceberg, day_in_life) when both are available.
6. One story, one slot: variants of one story (same `story_key`, section 13) are never served within `repeat_days` of each other. A card is a candidate only if no card of its story had an impression in that window. A batch holds at most one card per `story_key`, the best scored.
7. Series: parts of a series stay in order and at least 3 cards apart (series is null until M5; keep the hook).
8. SRS: at most 2 due cards per batch, placed at positions ≥ 3.

The cursor is an opaque base64 of `{"served": [short ids], "seed": int}`; a malformed cursor is a 400. `seed` makes a batch reproducible for tests.

## 6. Spaced repetition (SPEC §12.5)

On a wrong answer (`POST /api/answer`), upsert `srs(card_id)` with interval 1 day. A correct answer on a due card advances 1 → 3 → 7 days; a correct answer at 7 days sets `mastered = 1`. A wrong answer resets to 1 day and streak 0. Due = `due_at <= now and mastered = 0`.

## 7. Brief quotas from weights (SPEC §12.6)

`brief.build_brief` takes optional `category_shares`. Quotas come from the shares instead of the raw default mix, with a floor: every renderable category gets at least 1 card when `count >= number of categories`. The `interactive` category is now renderable (story types `spot_the_bug`, `guess_who`, `guess_when`, `quiz`, `this_or_that`; format `quiz`; packets with interactive slots are sonnet).

How many cards a run makes (`src/codescroll/supply.py`): `get_brief` without `count` uses `want`.

- `backlog` = ready cards not shown in the last `repeat_days`.
- `burn` = max(distinct cards shown per day, 7-day mean; `agent.min_burn_per_day`).
- `short` = `ceil(agent.target_runway_days * burn) - backlog`.
- `want` = 0 when `short` is 0 or less. Otherwise `want` is `short`, but at least `agent.min_run_count` (8) and at most `agent.max_count`. A run has a fixed start-up cost, so a small shortfall still gets a full run.

When `want` is 0, `get_brief` returns `nothing_to_do` and opens no run. An explicit `count` skips this.

### Format factors

`learning.format_factors` turns format rewards into a factor per format. For a format with evidence (mean `m`, count `n`, priors removed), `ref` is the plain mean of `m` over formats with evidence (0.5 if none):

    factor = (prior_strength + n * m / ref) / (prior_strength + n)

A format without evidence has no factor (1). `mix_inputs` passes the factors to `build_brief` as `format_weights`. `_pick_format` multiplies the factor into the rule boost. Rules still win: bans, caps and boosts work as before. With no evidence the picks do not change.

### Image share target

`config/defaults.yaml` has `visual_mix.image_min_share` (default 0.5). Image formats are the formats whose visual kind is `meme`, `illustration`, `comic`, `chart` or `diagram`. After the brief gives out slots, it swaps text formats for image formats until the image share meets the target. A swap stays in the same category. It skips cross-repo slots and `quiz` slots. It never uses a banned or unavailable format, a format at its cap, or an illustration that goes over `settings.render.max_illustrations_per_run` (default 6). If no legal swap remains, the brief keeps the lower share. Without `visual_mix` the target is 0.

## 8. Saved cards

Removed. Like is the only reaction. Migration 0006 deleted the stored `save` events, and the API rejects new ones.

## 9. Reset

`codescroll reset-weights [--feature F]` and `learning.reset_weights`. M4's MCP `reset_defaults` calls the same function.

## 10. Which rules change generation (brief) and which only rank (slotter)

`brief.build_brief` and `slotter.build_batch` read the same rules. Boost and prefer use the stored `factor` as is (the steering layer stores the defaults, so `None` counts as 1.0). `dir` rules use path-prefix matching in both.

| (type, feature) | brief (generation) | slotter (ranking) |
|---|---|---|
| ban `format`, `story_type`, `tone`, `persona`, `repo` | never assigned | cards removed |
| ban `group` | repos of the group are left out | cards removed |
| ban `dir` | leads under the dir are dropped | cards removed |
| ban `visual_kind`, `template` | formats that can only produce them are not assigned (`meme` kind: `meme`; template `X`: format `X`) | cards removed |
| ban `interactive` (value = story type) | that story type is not assigned | cards removed |
| ban `difficulty` | all interactive story types are dropped | cards removed |
| limit `format`, `story_type`, `repo`, `tone` | share ceiling on matching slots (best effort when no alternative remains; share 0 acts as a ban) | share ceiling on the batch |
| limit on other features | no effect | share ceiling on the batch |
| boost, prefer `format`, `story_type`, `repo`, `group`, `tone` | slot weight times the factor | score times the factor |
| boost, prefer `dir` | matching leads come first | score times the factor |
| focus `repo`, `dir` | slot weight (1 + slots) / leads first, plus a focus line | reserved slots |
| focus `format`, `story_type`, `group`, `tone` | like boost with factor 1 + slots | reserved slots |
| any rule on `recency`, `has_comments`, `persona` (except ban), `template` or `visual_kind` (except ban) | no effect | ranking only |

## 11. Garbage collection

Nothing grows without bound. `src/codescroll/gc.py` deletes cards and files that have no further use. `GcWorker` runs a pass every `gc.interval_s` (1 hour) inside `codescroll serve`. `codescroll gc [--dry-run] [--vacuum]` runs one pass and prints the counts as JSON. A dry run changes nothing. `VACUUM` runs only from the CLI.

Settings (`gc:` in `config/settings.yaml`):

| rule | default | a card (or row) is deleted when |
|---|---|---|
| seen | `seen_after_days: 14` | it has at least one reward, its last impression is older than N days, and it is not liked |
| liked | `liked_after_days: 90` | the same, but the card is liked |
| unseen | `unseen_after_days: 45` | it never had an impression and `created_at` is older than N days |
| failed | `failed_after_days: 7` | `status` is `render_failed` and `created_at` is older than N days |
| SRS | `srs_keep_days: 60` | never, if it has an `srs` row that is not mastered and due within N days (overdue cards stay too) |
| events | `events_after_days: 90` | the event is older than N days and was recorded before the card's newest reward was computed |
| run files | `run_files_after_days: 30` | the run is not open and ended more than N days ago; the folder `data/runs/<id>/` goes, the `runs` row stays |
| social | `social_after_days: 30` | `story_views` seen, and notifications read, more than N days ago |
| leads | `leads_after_days: 180` | the lead was last seen at HEAD more than N days ago and no card ever used it (`times_covered = 0`) |

Liked means the latest `like` event has `on: true`. If gc already removed the like events, `stories.liked` gives the answer. `process_events` keeps `stories.liked` and `stories.best_reward` up to date.

Deleting a card removes its `card_features`, its `assets` rows, its files in `data/assets/<card_id>/`, and its `srs` row. `notifications.card_id` becomes NULL.

What stays, and why:

- `stories`: the duplicate check reads it, so a deleted story is not made again.
- `leads` that a card used: coverage history stays.
- `rewards` and `weights`: this is what the feed learned. A pass never changes the weights.
- `events` that are newer than the newest reward, and events of impressions with no reward yet: the learner has not used them.
- Fresh unseen cards: gc never lowers the backlog.

A phone with an offline batch can still send events or an answer for a deleted card. Events are stored. `POST /api/answer` returns 404, and the quiz shows "This card is gone."

`feed_health` shows the counts of the last real pass under `gc`. The server keeps them in `data/gc_last.json`.

## 12. Lead ledger

A lead is a place to look: a commit, or a file at one blob. Each time `signals.analyze` recomputes a repo (a new HEAD), `ledger.refresh` stores every commit and path lead of every story type in the `leads` table. Leads of kind `none` (a directory, a pair) are not stored.

What a row holds:

- Identity: repo, story type, kind, path, commit sha, blob sha. A path lead carries the blob sha of the file at the analyzed ref. A changed file has a new blob, so it is a new row. The old row stays, and its `times_covered` shows it was told before.
- `strength`: `1 / (1 + rank)` inside its story type, from the signal order.
- `first_seen_at`, `last_seen_at`, `head_sha`: set again on each refresh.
- `times_covered`, `last_covered_at`, `mean_reward`, `rewards_n`: see below.

`get_brief` draws leads from the ledger. A row is a candidate when it was seen in the latest refresh of its repo (it still exists at HEAD) and its `last_covered_at` is not within `agent.lead_cooldown_days` (30). Candidates are sorted by:

`score = interest x strength x 0.5 ^ times_covered`

`interest` is the mean of the `dir` posterior means (section 4) over the parent dir prefixes of the lead's path. An unknown prefix counts as 0.5. A lead with no path counts as 0.5. Ties go to the lower row id. `focus` and `ban` dir rules still filter the leads by text. If the repo has no ledger rows for a story type, the brief computes the leads from signals as before. If all rows of a type are in cooldown, the type has no leads.

Coverage marking: `submit_cards(packet_id)` finds the packet lead each accepted card used. The first lead whose commit is cited by the card (sources, visual, or depth panels) wins. Else the first lead whose path is cited. The card gets `cards.lead_id`. The lead gets `times_covered + 1` and `last_covered_at`. Cards submitted without a packet mark nothing.

Reward: when `process_events` writes a reward for a card with a `lead_id`, the lead's `mean_reward` becomes the running mean of those rewards (`rewards_n` counts them).

The `coverage` tool adds `leads` (current leads under each top dir, one per file) and `leads_covered` (of those, how many a card used).

## 13. Story variants

A story that did well can be told again in another format. The `story_key` stays the same (it comes from the story type and the sources, not the format). Uniqueness on `cards` is per `(story_key, format)`. `stories.formats` is a JSON list of the formats already used. It lives on the story row, so it survives gc.

`submit_cards` and `check_cards` accept a card of an existing story only when all of these hold. If one fails, the card is rejected as `duplicate_story` and the detail names the failed condition.

- Its format is not in `stories.formats`.
- The story's `best_reward` is at least `agent.variant_min_reward` (0.6), or the story is liked.
- The story's last card is at least `agent.variant_after_days` (14) old.

The decision is `store.variant_blocker`. Two cards of one story in the same submission are always a duplicate.

The brief offers variants. `ledger.variants` lists the stories that meet the reward and age conditions (liked first, then best reward). It adds the hook of the newest card; if gc deleted every card, the lead has the story type and sources only. `build_brief` uses a variant for a slot only when that slot has no fresh lead: its (repo, story type) has fewer leads than slots. The variant must be in the slot's repo and a story type of the slot's category. At most `floor(agent.variant_max_share x count)` slots (0.2) become variants. A variant slot keeps the story's story type and gets a format of the category that the story has not used. The packet lead reads `[variant] retell "<hook>" (<story type>, first told as <formats>) as a <format>; cite the same sources: <sources>`. Its `lead_refs` entry is `{"kind": "variant", "story_key", "sources"}`. A variant lead marks no ledger coverage.

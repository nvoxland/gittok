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
| `like` / `save` | toggle buttons | `{"on": bool}` |
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
if skipped and not (like on or save on): reward = 0      # explicit positive feedback wins
else:
  watch = beat card:   min(1, sum(ms_played) / total_ms)     # time played, holds included
          static card: min(1, dwell_ms / expected_ms(card))  # a one-beat "video"
  reward = w.dwell * watch
         + w.depth_open (once) + w.explain_more + w.like (on) + w.save (on)
         + w.source_tap (once) + w.scroll_back + w.answer (any answer)
         + w.complete (beats_done) + w.replay (once)
  reward = clip(reward, 0, 1)
expected_ms(card) = format_base_ms[format] + ms_per_word * words(hook + visual text + first explain panel)
                    capped at expected_ms_max
```
Watch fraction works like a video's: time on screen after a beat card finished earns nothing (it mostly means "looked away"), and tapping through to the end does not count as fully watched. Static and beat cards share one 0..1 scale, so autoplay gets no free credit.

Defaults: `w.complete 0.15, w.replay 0.30, w.dwell 0.45, depth_open 0.15, explain_more 0.15, like 0.25, save 0.30, source_tap 0.10, scroll_back 0.35, answer 0.20`; `ms_per_word 250`, `expected_ms_max 45000`; `format_base_ms`: memes 1500, charts 3000, code 4000, threads/comics 6000, others 2500 (per-format table in reward.yaml).

`ms` values from the client are cleaned before use: non-numeric, null or negative becomes 0, and the value is capped at 24 hours. Events whose `data` is not an object are treated as having no data. One bad event never stops the processing of the others.

Rewards are written to `rewards` (one row per impression, idempotent on `impression_event_id`).

## 4. Weights (Thompson sampling, SPEC §12.3)

- Features per card come from `card_features` (story_type, format, persona, tone, repo, dir, visual_kind, template, difficulty, has_comments) plus `group` (from config) and `recency` (`new` < 7 days, `recent` < 30, `old`).
- One Beta(α, β) per (feature, value) in `weights`. Prior: α0 = prior_strength · m, β0 = prior_strength · (1 − m), with m = 0.5 by default and, for features in the default mix (category via story type/format, tone), m = clip(0.5 · share / mean_share, 0.15, 0.85).
- Update per reward r: decay first — the evidence part (α − α0, β − β0) is multiplied by 0.5^(Δdays / half_life_days) since `updated_at` — then α += r, β += 1 − r, for every feature value of the card.
- Card score = Σ_f importance[f] · sample_f / Σ importance over the card's features, where sample_f ~ Beta(α, β). Importances in reward.yaml: story_type 1.0, format 1.0, tone 0.7, persona 0.5, repo 0.8, group 0.4, dir 0.6, visual_kind 0.5, template 0.5, meme_template 0.4, recency 0.6, difficulty 0.3, has_comments 0.2.
- `dir` features are path prefixes. A card gets the dirs it names, plus the parent dir of every path in its sources, its visual (when it has a path), and its `code` and `code_diff` depth panels. Each dir adds all its prefixes: `a/b/c` gives `a`, `a/b`, `a/b/c`. A file at the repo root adds no dir. Reward updates every prefix, so a parent dir learns from its children.
- A card's `dir` prefixes count as one term in the score. The sampled values are averaged, and `importance.dir` is applied once. A deep card does not outweigh `format` or `story_type`.
- `blamescroll refeature` recomputes `card_features` for all cards from their stored specs. Run it after a change to how features are derived. `blamescroll refit --apply` does the same for each card it rewrites.
- `half_life_days` 21, `prior_strength` from `config/defaults.yaml` (10).

Public API (`src/blamescroll/learning.py`):
```python
def process_events(conn, cfg, now=None) -> dict            # new impressions → rewards → weight updates; idempotent
def card_features(conn, cfg, card_id) -> list[tuple[str, str]]
def score_cards(conn, cfg, card_ids, rng) -> dict[str, float]   # Thompson sample per call
def posterior_means(conn, cfg, feature: str) -> dict[str, tuple[float, float]]  # value -> (mean, n_evidence)
def category_shares(conn, cfg) -> dict[str, float]          # learned share per default-mix category, blended with the prior
def reset_weights(conn, feature: str | None = None) -> int
```
`process_events` runs in the serve worker every 30 s and via `blamescroll learn`.

## 5. Slotting (SPEC §12.4) — `src/blamescroll/slotter.py`

`GET /api/feed?limit=20&cursor=...` builds the next batch. A first page (no cursor) starts with the card of the newest impression, if it is still `ready`, so a reload resumes there (`resume_card_id`); the slots below fill the rest.
1. Candidates: `ready` cards not impressed in the last `repeat_days` (7), not already served this feed session (the cursor carries served ids), plus due SRS cards.
2. Rules from the `rules` table (M4 writes them; the slotter honors them now): `ban` removes, `boost`/`prefer` multiply the score, `focus` reserves `slots` per batch for matching cards, `limit` caps the matching share of the batch. `dir` rules use path-prefix matching (`src` covers `src` and `src/api`, not `lib/src`; a leading `repo/` is accepted).
3. Exploration: `exploration_share` (0.18) of slots are filled uniformly at random from candidates outside the top half.
4. Learning boost: 10% of slots go to cards whose dirs have the fewest impressions (coverage).
5. Rhythm: never more than 2 of the same format in a row; alternate fast formats (meme, text_meme, fun_fact, chart, hot_take) with slow ones (thread, comic, code_card, quiz, iceberg, day_in_life) when both are available.
6. One story, one slot: variants of one story (same `story_key`, section 13) are never served within `repeat_days` of each other. A card is a candidate only if no card of its story had an impression in that window. A batch holds at most one card per `story_key`, the best scored.
7. Series: parts of a series stay in order and at least 3 cards apart (`series` is `{key, part, of}`; SERIES_GAP positions apart, and a part waits for unseen earlier parts).
8. SRS: at most 2 due cards per batch, placed at positions ≥ 3.

The cursor is an opaque base64 of `{"served": [short ids], "seed": int}`; a malformed cursor is a 400. `seed` makes a batch reproducible for tests.

## 6. Spaced repetition (SPEC §12.5)

On a wrong answer (`POST /api/answer`), upsert `srs(card_id)` with interval 1 day. A correct answer on a due card advances 1 → 3 → 7 days; a correct answer at 7 days sets `mastered = 1`. A wrong answer resets to 1 day and streak 0. Due = `due_at <= now and mastered = 0`.

## 7. Brief quotas from weights (SPEC §12.6)

`brief.build_brief` takes optional `category_shares`. Quotas come from the shares instead of the raw default mix, with a floor: every renderable category gets at least 1 card when `count >= number of categories`. The `interactive` category is now renderable (story types `spot_the_bug`, `guess_who`, `guess_when`, `quiz`, `this_or_that`; format `quiz`; packets with interactive slots are sonnet).

How many cards a run makes (`src/blamescroll/supply.py`): `get_brief` without `count` uses `want`.

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

`GET /api/saved` → `{"cards": [Card]}`, most recently saved first. Web route `/saved`.

Saved state lives in the `saved_cards` table (`card_id`, `saved_at`, `saved_ts`). Gc prunes old events, so events alone cannot hold it. `POST /api/events` updates the table in the same transaction as a `save` event. The newest `save` event by `ts` wins: an older event that arrives late changes nothing. A save for an unknown card is ignored. Migration `0010_saved_cards.sql` fills the table from the latest `save` event per card. Gc never deletes a saved card (see section 11).

## 9. Reset

`blamescroll reset-weights [--feature F]` and `learning.reset_weights`. M4's MCP `reset_defaults` calls the same function.

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

Nothing grows without bound. `src/blamescroll/gc.py` deletes cards and files that have no further use. `GcWorker` runs a pass every `gc.interval_s` (1 hour) inside `blamescroll serve`. `blamescroll gc [--dry-run] [--vacuum]` runs one pass and prints the counts as JSON. A dry run changes nothing. `VACUUM` runs only from the CLI.

Settings (`gc:` in `config/settings.yaml`):

| rule | default | a card (or row) is deleted when |
|---|---|---|
| seen | `seen_after_cards: 20` | it has at least one reward, it is not liked, and at least N other cards have an impression after its last impression |
| liked | `liked_after_days: 90` | the same, but the card is liked |
| unseen | `unseen_after_days: 45` | it never had an impression and `created_at` is older than N days |
| failed | `failed_after_days: 7` | `status` is `render_failed` and `created_at` is older than N days |
| saved | none | never: a card in `saved_cards` is kept, whatever its age or reward |
| SRS | `srs_keep_days: 60` | never, if it has an `srs` row that is not mastered and due within N days (overdue cards stay too) |
| events | `events_after_days: 90` | the event is older than N days and was recorded before the card's newest reward was computed |
| run files | `run_files_after_days: 30` | the run is not open and ended more than N days ago; the folder `data/runs/<id>/` goes, the `runs` row stays |
| social | `social_after_days: 30` | `story_views` seen, and notifications read, more than N days ago |
| leads | `leads_after_days: 180` | the lead was last seen at HEAD more than N days ago and no card ever used it (`times_covered = 0`) |
| log files | `log_max_kb: 1024` | a `data/logs/*.log` file (`api.log`, `rejected-events.log`) is bigger than N KB; it keeps its newest half, cut at a line start |

The seen rule counts cards, not days. A card is done when you have scrolled past 20 newer cards, so a slow week does not delete cards you never had time to see. Gc counts distinct cards with one query over the last impression of each card. A card with no reward yet is kept, because learning has not used it. A saved card is kept forever, because you asked to keep it.

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

A lead is a place to look: a commit, or a file. Each time `signals.analyze` recomputes a repo (a new HEAD), `ledger.refresh` stores every commit and path lead of every story type in the `leads` table. Leads of kind `none` (a directory, a pair) are not stored.

What a row holds:

- Identity: repo, story type, `lead_key`. A commit lead is keyed by sha and path (`c:<sha>:<path>`), a path lead by its path (`p:<path>`), a lead with no repo identity by a synthetic key (`dir:src`, `pair:a|b`). An edit to a file keeps its row, so the cooldown and `times_covered` stay. The row also stores the kind, path, commit sha, and the blob sha at the analyzed ref (for information only).
- `strength`: `1 / (1 + rank)` inside its story type, from the signal order.
- `first_seen_at`, `last_seen_at`, `head_sha`: set again on each refresh.
- `times_covered`, `last_covered_at`, `mean_reward`, `rewards_n`: see below.

`get_brief` draws leads from the ledger. A row is a candidate when it was seen in the latest refresh of its repo (it still exists at HEAD) and its `last_covered_at` is not within `agent.lead_cooldown_days` (30). Candidates are sorted by:

`score = interest x strength x 0.5 ^ times_covered`

`interest` is the mean of the `dir` posterior means (section 4) over the parent dir prefixes of the lead's path. An unknown prefix counts as 0.5. A lead with no path counts as 0.5. Ties go to the lower row id. `focus` and `ban` dir rules still filter the leads by text. If the repo has no ledger rows for a story type, the brief computes the leads from signals as before. If all rows of a type are in cooldown, the type has no leads.

Dedup (`ledger.ranked`, `ledger.offerable`):

- Subject cooldown: a card's subject is its visual's commit or path, else its first source's. A commit or path that was the subject of a ready (or `pending_render`) card made in the last `agent.subject_cooldown_days` (14) is not offered, in any story type. Server-made leads (`req:`, `notif:`) skip this filter.
- Rejects: when `submit_cards(packet_id)` rejects a card (not for `over_quota` or `illustration_budget`) that cites a packet lead, the lead gets `times_rejected + 1` and `last_rejected_at`. In `score` it is multiplied by `0.5 ^ times_rejected` while `last_rejected_at` is inside the subject cooldown window. After the window the penalty is gone.
- Packets: `build_brief` deals the leads of a (repo, story type) round robin over the packets that hold that type. An intro lead is only in its own packet. A commit or path is offered to one packet of a repo. So two packets of one repo never share a lead.
- Cross-repo leads (recap, drift, ripple) have no ledger row, so they have no cooldown. A card cannot be tied to one of them (it cites commits of several repos and carries no lead id), so coverage would be a guess.

Spot the Bug minimum: `agent.min_spot_the_bug_per_run` (0.125, one card per 8) of a brief's cards are `spot_the_bug` slots, reserved before the category quotas, when some repo has a lead for it. The interactive quota grows to hold them. The slotter places one unseen quiz card in each window of 8 cards of a batch, if one exists.

Coverage marking: `submit_cards(packet_id)` finds the packet lead each accepted card used. The first lead whose commit is cited by the card (sources, visual, or depth panels) wins. Else the first lead whose path is cited. The card gets `cards.lead_id`. The lead gets `times_covered + 1` and `last_covered_at`. Cards submitted without a packet mark nothing.

Reward: when `process_events` writes a reward for a card with a `lead_id`, the lead's `mean_reward` becomes the running mean of those rewards (`rewards_n` counts them).

The `coverage` tool adds `leads` (current leads under each top dir, one per file) and `leads_covered` (of those, how many a card used).

### Candidate leads (understanding and interactive story types)

Nine story types have no signal of their own: `what_it_does`, `journey`, `analogy`, `snippet_callouts`, `cursed_clever_line`, `quiz`, `this_or_that`, `guess_who`, `guess_when`. Their leads come from the miner candidates (`candidates.py`) and the scout ratings (`scout.py`), through `candidate_leads.py`. The churn fallback is gone. A type with no candidate has no leads, so `build_brief` skips it and gives its cards to the other categories (a category whose types all need candidates is dropped when no repo has one, and a repo without candidates gets no share of it).

| story type | tags | verdicts | min teachable | extra rule |
|---|---|---|---|---|
| `what_it_does` | core, entry_point, public_api, stable_core | core, good | 2 | |
| `journey` | entry_point, core | core, good | 2 | |
| `analogy` | core, god_file, entry_point | core | 2 | |
| `cursed_clever_line` | clever, smell, long_line, deep_nesting, catch_all, sleep, magic_number, big_literal | clever, cursed, bad | 2 | |
| `snippet_callouts` | any | any | 4 | |
| `quiz`, `this_or_that` | any | any | 4 | clever, core, smell, entry_point, god_file or a clever/cursed/bad/core verdict fits best |
| `guess_who` | any | any | 3 | top dir has two authors with 20% of the changed lines or more (`author_shares`) |
| `guess_when` | any | any | 3 | tag `stable_core`, or a file with lines older than 90 days (`oldest_lines`) |

A window is eligible when its tag or its verdict is in the row. `strength = teachable / 5 x fit`. Fit is 1.0 when tag and verdict both suit the type, 0.8 for the tag alone, 0.7 for the verdict alone (any-tag types: 1.0 for a preferred tag or verdict, else 0.8). `ledger.ranked` then multiplies by novelty (section 14), interest, and `0.5 ^ times_covered`. A file gives at most 2 windows per type. Test files and docs never count.

Unrated windows (no scout rating for the same window text) count only when no rated window fits the type. They have `strength` at most 0.1 and the lead text starts with `[unrated]`.

A candidate lead is a path lead with the window as its `lines`, key `cand:<path>:<line_start>:<tag>`, and text `[<verdict>] <miner why> (<path>:<line>). Scout: '<concept>' - <scout why> (teachable N)`. It gets the same materials as other path leads (the window, what it defines, callers, why-commits). Cooldown and story blocks apply as for any path lead. `ledger.refresh` stores the candidate leads; `ledger.for_brief(..., analyses=...)` redoes them first, because scouts rate windows after the analysis. Those rows keep the repo's latest `last_seen_at`.

### Candidate score and repo profiles

Every candidate, built-in or from a profile rule, gets its `score` from one formula (`candidates._rescore`):

`score = weight x strength x fanin x size x age x churn`

| Factor | Value |
|---|---|
| `weight` | 1 for built-in miners. A profile rule sets it (0.1 to 3). |
| `strength` | `log2(1 + raw)`, where `raw` is the miner's own count (lines, branches, hits). A profile hit has raw 1, so strength 1. This keeps the order inside one tag. |
| `fanin` | `1 + 0.25 x min(4, log2(1 + importers of the file))`. Range 1 to 2. |
| `size` | The file has fewer than 10 lines: 0.7. Fewer than 20: 0.85. Else 1. |
| `age` | The file changed in the 90 days before the analyzed commit: 1. Else 0.85. |
| `churn` | `1 + 0.5 x (file commits in 90 days / commits of the top file)`, from the churn signal (top 25 files). A file outside that list, or no churn signal: 1. |

The limits stay: `analysis.candidates_per_tag` per tag (a profile rule has its own limit, per tag and rule) and 3 per file. The stored key is still (repo, path, line start, tag). When a profile hit and a built-in hit share that key, the built-in hit stays.

A repo profile is a YAML file `local/profiles/<repo>.yaml` in Blamescroll (never in the repo it describes). Its format is `src/blamescroll/schema/profile.schema.json`. `profiles.py` loads it and rejects unknown keys, a bad tag, a weight outside 0.1 to 3, a rule with both or neither of `regex` and `ast_grep`, and a bad glob. Each error names the detector id. A repo with no file has an empty profile: built-in miners only. Rules are data. Blamescroll never runs code from a profile.

The profile also owns the file set. `scan` (globs of files read), `ignore` (globs never read) and `kinds` (`test`, `fixture`, `generated`, `docs`, `vendored` -> globs) come from the profile; `generated_markers` (regexes for generated headers) is optional. A file is read iff it matches `scan` and not `ignore`. `kinds` classify read files: `test` sets `is_test`; generated, vendored and fixture files are never mined but stay classified for the intro, `whose_code` and the repo map. `profiles.FileSet` is the one classifier (`reads`, `kind`, `is_test`, `is_code_dir`). The bootstrap values are in `config/scan_defaults.yaml` (scan from `languages.yaml` extensions, ignore, kinds, generated markers, noise). They apply per key: a key the profile sets replaces the default, a key it omits uses it. No merging, so the agent is in control. A scanned file with no known language gets the `text` language: only the plain text rules (see the structure layer below) and profile rules apply. `noise` (lockfiles, source maps, images) always keeps such paths out of story leads. No Python file may hold path or extension lists (a test greps for them).

`detectors.py` runs the rules over the files of the file set (same size caps). A `regex` rule uses the `regex` module with a 0.2 s limit for each file and rule. A timeout logs the rule and file, and skips them. Lines over 1000 characters are not matched. An `ast_grep` rule needs `ast-grep-py`, a normal dependency. If it is missing, these rules are skipped with one log line. ast-grep supports Python, TypeScript, JavaScript and others, but not Clojure. The profile `ignore` globs also remove built-in candidates. `candidates.rule_id` holds the rule id (NULL for built-ins), and `load_candidates` and `load_rated` return it. `Config.role_for(repo, path)` gives the role of the longest matching dir in `roles`.

Per-rule outcomes (`rule_stats.py`, MCP tool `rule_stats(repo)`, `rule_outcomes` in `get_profile`). Each rule id, and each built-in tag as `builtin:<tag>`, gets: candidates found, rated, mean teachable, cards made, mean reward of those cards, and their `knew_it` and `teach_more` counts. A card traces to its rule through `cards.lead_id -> leads.lead_key "cand:<path>:<start>:<tag>" -> candidates.rule_id`. The outcome factor is `clamp(0.5, 1.5, (5 + N x q) / (5 + N))`. N is rated windows plus rewarded cards. q is the N-weighted mean of `mean teachable / 3` and `mean card reward / mean reward of the repo`. A rule with no data has factor 1.0. `candidate_leads.leads_for` multiplies the lead strength by the factor; `rule_stats.effective_weight(weight, factors, rule)` gives the scaled profile weight. The stored candidate `score` is not changed.

Every lead built from git signals passes the repo's file set (`brief.lead_in_files`, applied at the end of `lead_refs_for`, so the ledger refresh and the no-ledger fallback are both clean). A path, or both files of a pair, must be read by the profile and not of kind generated, vendored or fixture; a dir lead must be a code dir; a commit lead with no path is dropped when every path it touched is outside the set (the `huge_diffs`, `late_night` and `recent_commits` signals carry them). `ledger._current` applies the same check to stored rows. Pinned server leads are exempt.

Intro slots use code dirs only (`brief.code_path`: no hidden, test, fixture, cassette, snapshot, vendored, generated or docs dirs), and prefer dirs that hold a `core` or `entry_point` candidate. `whose_code` never offers the root dir or hidden dirs.

### The structure layer

Shipping a regex set per language does not scale, so the miners read code through three layers. A file uses the first layer that can read it.

1. **Structure** (`structure.py`, tree-sitter, a normal dependency). Tree-sitter parses the file. Tags queries in `config/queries/<grammar>.scm` say what a definition, a reference, a comment and an import look like. `config/queries/languages.yaml` holds the rest as data: extensions, which node types nest and branch, how to count parameters, what is public, the head symbols of a Lisp (`def_heads`). Shipped: python, typescript (also tsx, javascript, jsx, svelte `<script>`), clojure, go, ruby, java, rust.
2. **Regex patterns** (`config/languages.yaml`: python, clojure, typescript). Used when the group or the grammar is missing, and for what is a pattern, not structure: entry points, catch-all, sleep, regex literals, bit operations, skipped tests, metaprogramming, commented-out code, long lines, big literals.
3. **Plain text**, for a file with neither (a scanned file type with no grammar, such as `.zig` in a profile `scan`). The miners find `smell` markers in comment-like lines (prefixes in `text_fallback.comment_prefixes`), `long_line`, and `deep_nesting` by indentation. Data and prose extensions (`text_fallback.skip_extensions`) and `docs` files are skipped.

The pack downloads a grammar bundle on first use. Mining never starts that download: a grammar counts only when it is already in the local cache (`structure.ready`). `blamescroll structure --prefetch` fetches the grammars for the languages in the configured repos, and `blamescroll health --hint` prints one line when the group is installed but a grammar is missing. Until then those files use layer 2 or 3.

What the structure layer changes in the miners:

- **Markers** (`smell`): found only inside comment nodes. A `TODO` or `HACK` in a string or docstring no longer counts.
- **Definitions** (`long_function`, `many_params`, `deep_nesting`, `many_branches`, `public_api`, recursion): from the definition nodes. A function ends at its real closing node.
- `many_params` counts **top-level parameters**. Destructuring (`{a, b}`, `{:keys [a b]}`) is one parameter; `self`/`cls`, Clojure `&`, and a Plumatic/Malli `x :- Schema` pair do not add extra ones; Go counts every name in `a, b int`; a multi-arity Clojure function counts its longest arity. The old regex counted every symbol in the parameter list.
- `deep_nesting` is the number of enclosing control-flow nodes (`if`, `for`, `while`, `try`, `switch`, `match`; in Clojure the heads in `nesting_heads`) plus one: the function body is level 1. An `else if` chain adds no depth. The threshold is `thresholds.deep_nesting` of the language in `config/queries/languages.yaml` (5 for all). The old value was indentation levels or paren depth.
- `many_branches` counts branch nodes (`branch`, `branch_heads`), not words.
- **Fan-in and fan-out** (`core`, `god_file`): imports come from import nodes, so an import inside a comment or string is ignored. Python and TypeScript keep import-based resolution. Clojure resolves namespace aliases: a file imports another when it requires the namespace AND uses it (`alias/name`, a referred name, or `ns/name`; a plain `(:require [x.y])` with no alias counts). Go, Ruby, Java and Rust resolve the module spec by the end of the path (`require_relative` is exact; a Go import names a directory and stands for its file named like the directory, else its longest file). A bare short name is never used for fan-in, because the same name is defined in many files.
- **"Called from"** in the materials: `git grep -w` finds the candidates, then the structure layer keeps only the hits that are real references on that line (not text in a comment or a string). Without it every hit stays.

#### The profile `queries` field

A stack we do not ship can still be read. A profile may carry `queries: {<grammar>: "<tags query>"}`, where the key is a tree-sitter-language-pack grammar name (`php`, `kotlin`, ...). It replaces the shipped query for that grammar, or adds one. It is data: a query text, never code. Captures: `@definition.<kind>` on the whole definition with `@name` on its name; `@reference`; `@comment`; `@import` on a statement with `@import.path` on the module spec (and `@import.relative` for a relative one); `@private`. Unknown capture names are rejected. For a grammar with no shape rules in `languages.yaml`, the `generic` block applies (nesting and branch node names by pattern, parameters from the `parameters` field).

`save_profile` checks each query: it must compile for the grammar, use only the captures above, read at least one file of the file set and find something in it. A failure comes back in `errors["queries.<grammar>"]`; a pass returns `queries: {<grammar>: {files, defs}}`. Without the `structure` group the query cannot be checked, so the save is refused. `survey_repo` returns a `structure` block: whether the layer is installed, what is shipped, and the file types in the repo that have a grammar in the pack but no query here (`uncovered`).

## 13. Story variants

A story that did well can be told again in another format. The `story_key` stays the same (it comes from the story type and the sources, not the format). Uniqueness on `cards` is per `(story_key, format)`. `stories.formats` is a JSON list of the formats already used. It lives on the story row, so it survives gc.

`submit_cards` and `check_cards` accept a card of an existing story only when all of these hold. If one fails, the card is rejected as `duplicate_story` and the detail names the failed condition.

- Its format is not in `stories.formats`.
- The story's `best_reward` is at least `agent.variant_min_reward` (0.6), or the story is liked.
- The story's last card is at least `agent.variant_after_days` (14) old.

The decision is `store.variant_blocker`. Two cards of one story in the same submission are always a duplicate.

The brief offers variants. `ledger.variants` lists the stories that meet the reward and age conditions (liked first, then best reward). It adds the hook of the newest card; if gc deleted every card, the lead has the story type and sources only. `build_brief` uses a variant for a slot only when that slot has no fresh lead: its (repo, story type) has fewer leads than slots. The variant must be in the slot's repo and a story type of the slot's category. At most `floor(agent.variant_max_share x count)` slots (0.2) become variants. A variant slot keeps the story's story type and gets a format of the category that the story has not used. The packet lead reads `[variant] retell "<hook>" (<story type>, first told as <formats>) as a <format>; cite the same sources: <sources>`. Its `lead_refs` entry is `{"kind": "variant", "story_key", "sources"}`. A variant lead marks no ledger coverage.

## 14. What the reader knows (knowledge model) — `src/blamescroll/knowledge.py`

The `knowledge` table (migration 0012) holds counts per `(repo, dir)`: `cards_seen`, `explains_opened`, `quiz_right`, `quiz_wrong`, `knew_it`, `teach_more`, `last_seen_ts`. `process_events` calls `knowledge.update_in_tx` after the rewards, in the same transaction.

Events counted:

| count | event |
|---|---|
| `cards_seen` | `impression`, once per card |
| `explains_opened` | `depth_open` whose `panel` is the explain panel, once per card. Panel 0 is the visual; depth panel `i` is panel `i + 1`. The explain panel is the first depth panel of kind `explain`. |
| `quiz_right`, `quiz_wrong` | `answer` with `correct` true or false (the server sets it). `null` counts nothing. |
| `knew_it`, `teach_more` | events of the same name (the buttons come later; the API accepts them now) |

Idempotent: each counted event is written to `knowledge_events(event_id, ts)`. An event already there is skipped, so reprocessing changes nothing. This is the same idea as `rewards.impression_event_id`.

A card counts toward each repo in its `repo` features and each of its `dir` features, cut to the first 2 path levels: `a/b/c` counts toward `a` and `a/b`. A deeper dir is not tracked, because the reader learns an area, not a file. Cards with no dir count nothing.

Novelty (0 = known, 1 = new), `knowledge.novelty(conn, repo, dir)`:

```
pos      = cards_seen + 2 explains_opened + 2 quiz_right + 4 knew_it
struggle = quiz_wrong + teach_more
n = 1 / (1 + pos / 4)                          # never seen: 1
n = n + (1 - n) * struggle / (struggle + 2)    # wrong answers and "teach more" lift it
n = n + (1 - n) * 0.3 * min(1, commits_30d / 10)   # others changed it lately (signals churn, 30 days)
n = n * (1 - 0.25 * own_share)                 # only when settings.user.git_identities is set
```

A dir with no row has novelty 1. `commits_30d` comes from the stored churn signal (top 25 dirs per window; others count 0). `own_share` is the reader's share of changed lines in the top-level dir (signal `author_shares`, matched by name, case-insensitive). It lowers novelty by at most 25%, because the reader often studies code that other people wrote. `settings.user.git_identities` defaults to empty.

`knowledge.novelty_map(conn, repo)` gives `{dir: novelty}` for every dir with counts or with a card. The `coverage` tool adds `novelty` to each top-level dir (1.0 when unknown). `get_profile` adds `knowledge`: the 10 most novel dirs.

### Knowledge per symbol

The `knowledge_symbols` table (migration 0023) holds the same counts per `(repo, symbol)`: `seen`, `explains_opened`, `quiz_right`, `quiz_wrong`, `knew_it`, `teach_more`, `last_seen`. The symbol is `fact_defines.symbol` from the syntax facts. It is updated in the same pass as the dir counts (same events, same once-per-card rule, same `knowledge_events` guard, so reprocessing changes nothing).

A card's symbols (`knowledge.card_symbols`): the symbols named by `resolved["facts"]` when the card has them; else the innermost definitions that overlap the lines of its code visual and code panels, plus backticked names (`` `name` `` or `` `name()` ``) that match at most 3 definitions in the card's repos.

`knowledge.symbol_novelty` uses the dir formula without churn and authorship. Lead ranking multiplies the dir novelty by a symbol factor (`knowledge.SymbolContext.factor`), from the innermost definitions in the lead's window:

```
f = 0.5 + 0.5 * max(novelty(symbol))       # all symbols seen: down to 0.5
f = f * 1.3                                # the window defines an unseen symbol that calls or is called by a seen one
```

A window with no known definitions, or a repo with no symbol knowledge, has factor 1. The repo map API adds `files`: for the 15 files with most functions, methods and classes, `symbols_defined` and `symbols_seen`. The UI shows "4 of 12 functions seen".

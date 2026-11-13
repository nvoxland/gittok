# Learning, ranking, and interactive cards

Implements SPEC §6.3 and §12. All numbers below are defaults in `config/reward.yaml` unless stated.

## 1. Events (client → `POST /api/events`)

Existing types keep their meaning. Data per type:

| type | when | `data` |
|---|---|---|
| `impression` | card becomes ≥60% visible | `{}`; the server adds `"familiarity"` (section 4) |
| `dwell` | card stops being visible (one per visit) | `{"ms": int}`; a beat card adds `"ms_played"` (the time its beats played in this visit) and `"total_ms"` |
| `skip` | left in under 1000 ms, or a beat card left during its first beat (sent with the dwell) | `{"ms": int}` |
| `beats_done` | a beat card played to its end (by itself or by taps) | `{"beats": int, "ms_played": int}` |
| `replay` | the replay control on a finished beat card | `{}` |
| `beat_tap` | a tap that skipped to the next beat (recorded, not rewarded yet) | `{"beat": int}` |
| `scroll_back` | a card already seen this session becomes visible again | `{}` |
| `depth_open` | horizontal panel changes | `{"panel": int}` |
| `like` / `save` | toggle buttons | `{"on": bool}` |
| `dislike` | the 👎 button ("Show less like this"), a toggle; turning it on turns `like` off and back | `{"on": bool}` |
| `knew_it`, `teach_more` | retired with the "Knew it" and "More" buttons. `POST /api/events` still accepts them (a phone may send an old queued batch) and drops them. | |
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

An impression window is the events for a card from one `impression` until the next `impression` of any card in the same client session, capped at 30 minutes. (The client sends a `session` string in every event's `data`; events without one are grouped by card and 30-minute gaps.) An event at the same ms as the next impression belongs to the window with the lower event id. A 👎 closes its window like any other event: it teaches the learner what to make next (sections 7 and 12) and does not change the cards the reader already has.

A 👎 that the reader takes back is unlearned: on the next pass its reward is deleted, the story's `disliked` mark is cleared, the model is rebuilt from the other rewards (`relearn`), and the impression is scored again with its 👎 events left out. The `dislike` events of a card whose last toggle is off never count.

```
if dislike on (last toggle):  reward = 0, weight = dislike_weight (4), signal = dislike
visits  = one per dwell; a `skip` right after a dwell marks that visit a skip
engaged = depth_open, lightbox_open, explain_more, source_tap, beats_done, replay or answer
skipped = not engaged and (every visit was a skip
                           or dwell_ms < skip_ms (reward.yaml, default 1000) over all the visits)
if skipped and not (like on or save on): reward = 0      # explicit positive feedback wins
else:
  watch = beat card:   min(1, sum(ms_played) / total_ms)     # time played, holds included
          static card: min(1, dwell_ms / expected_ms(card))  # a one-beat "video"
  reward = w.dwell * watch
         + w.depth_open (once) + w.explain_more + w.like (on) + w.save (on)
         + w.source_tap (once) + w.scroll_back + w.answer (any answer)
         + w.complete (beats_done) + w.replay (once)
  reward = clip(reward, 0, 1)
if like on: reward = max(reward, like_floor (0.9)), weight = like_weight (2), signal = like
else: weight = 1
expected_ms(card) = format_base_ms[format] + ms_per_word * words(hook + visual text + first explain panel)
                    capped at expected_ms_max
```
The weight is how many times the impression counts in the model (section 4). A 👎 means "show less like this", whatever the reason (known already, boring, not my kind of card): the learner works out what it was from all the 👎 and 👍 over many cards. Feeds that published their ranking weights count a "show less" far more than a like; GitTok keeps the ratio small, because one reader gives few signals. A 👎 also marks the card's story (`stories.disliked`): it is never told again in another format.

Watch fraction works like a video's: time on screen after a beat card finished earns nothing (it mostly means "looked away"), and tapping through to the end does not count as fully watched. Static and beat cards share one 0..1 scale, so autoplay gets no free credit.

Defaults: `w.complete 0.15, w.replay 0.30, w.dwell 0.45, depth_open 0.15, explain_more 0.15, like 0.25, save 0.30, source_tap 0.10, scroll_back 0.35, answer 0.20`; `like_floor 0.9`, `like_weight 2`, `dislike_weight 4`; `ms_per_word 250`, `expected_ms_max 45000`; `format_base_ms`: memes 1500, charts 3000, code 4000, threads/comics 6000, others 2500 (per-format table in reward.yaml).

`ms` values from the client are cleaned before use: non-numeric, null or negative becomes 0, and the value is capped at 24 hours. Events whose `data` is not an object are treated as having no data. One bad event never stops the processing of the others.

One short look after a long read is not a skip: the client sends dwell and skip for each visit, and a window is a skip only when all its visits were. A scroll back is not engagement here: a quick pass on the way back is still a skip.

Rewards are written to `rewards` (one row per impression, idempotent on `impression_event_id`), with the `weight`, the `signal` (`like`, `dislike` or none) and `features`: the features of the impression (section 4) at that time. An impression that cannot be scored gets a row with weight 0: it teaches nothing and is not read again. Event ids are never used again (`AUTOINCREMENT`), so a reward always names its own impression. Each pass reads only the impressions of existing cards that have no reward yet.

## 4. The learner: one additive model (Thompson sampling, SPEC §12.3)

One model decides what to make (sections 7 and 12). It never orders the cards that exist: the feed serves them oldest first (section 5). It is a Bayesian logistic regression with one Gaussian weight per (feature, value) in `model_weights` (`mean`, `precision`, decayed evidence `n`), updated online one reward at a time (Chapelle and Li 2011, "An Empirical Evaluation of Thompson Sampling"). The log-odds of the reward is the sum of the weights of the active features. So the weights are learned together: when memes get 👎 in many dirs, the `format meme` weight takes the blame and the dirs stay near neutral.

Features of a card (`card_features`, written by `store`):

| feature | value |
|---|---|
| `story_type`, `format`, `persona`, `tone`, `repo` | from the card |
| `angle` | what kind of knowledge the card gives: `what` (what it is, where it lives), `how` (how it works, what calls what), `why` (why it is like this, how it got here), `who` (who wrote it, who owns it), `risk` (bugs, smells, edge cases). The brief proposes it from the story type (`brief.ANGLE_OF`); the writer keeps it or sets the angle the card really has. It groups the story types, so a like on one `why` story type teaches the model about the others, and it describes the open story types (quiz, this_or_that) that can be about anything. |
| `dir` | path prefixes: the dirs the card names, plus the parent dir of every path in its sources, its visual and its `code` and `code_diff` panels; `a/b/c` gives `a`, `a/b`, `a/b/c`. A file at the repo root adds no dir. |
| `file` | the main path: the visual's path, else the first cited path |
| `language` | from the extension of each cited path (`languages.yaml`, then the tags-query languages) |
| `kind` | the main file's kind in the repo's file set: `test`, `fixture`, `generated`, `docs`, `vendored` or `source` |
| `tag` | the detector tag of the card's lead (a profile rule or a builtin miner), when the lead is a candidate |
| `visual_kind`, `template`, `meme_template`, `verdict`, `has_comments`, `interactive` | from the card |

Derived at read time: `group` (from config), `recency` (`new` < 7 days, `recent` < 30, `old`), and `familiarity`: how well the reader knows the card's deepest dir now (knowledge model, section 14): `new` (novelty ≥ 0.7), `some` (≥ 0.35) or `known`. Each pass writes the familiarity into each new impression (`data.familiarity`) before the knowledge model counts it, so the reward learns what the reader knew when the card was ranked. The reward snapshot keeps it.

Inputs: a bias, 1 for each feature, and 1/n for each of a card's n `dir` prefixes (they share one unit, so a deep card does not outweigh its format). Crosses (reward.yaml `crosses`, default `[angle, familiarity]`) add one input per pair of values (`cross:angle*familiarity = why|known`): the reader may like `why` cards about code they know and `what` cards about code they do not.

- Prior: mean 0, except for the default mix (story type and format via their category, tone): 0.5 · ln(share / mean share), clamped to ±0.7. The prior sd per feature is reward.yaml `prior_sd` (wide for what readers care about, narrow for `file`, which must back off to its dir).
- Update for reward y counted c times (the reward's weight): with z0 = Σ m·x and s = Σ x²/q, solve z = z0 − c·s·(σ(z) − y) by Newton; then each active weight moves to m − c·(σ(z) − y)·x/q and its precision grows by c·σ(z)(1 − σ(z))·x². Before the update the evidence decays: mean and precision move back toward the prior by 0.5^(Δdays / half_life_days), half-life 21 days.
- Thompson sampling: a draw samples each weight from N(mean, 1/precision), seeded by (draw seed, feature, value), so one draw scores the same in any order. Card score = σ(Σ sampled w·x): a sampled expected reward.
- The stored weights are a cache: `gittok relearn` rebuilds them from the rewards, oldest first, with each card's current features and the familiarity of the impression (the saved snapshot alone for a card that is gone). Run `gittok refeature` and then `gittok relearn` after a change to how features are derived or to the priors. A reset (section 9) stays reset: `model_resets` notes it, and relearn leaves the reset features out of older rewards (all of an older reward after a full reset).

Public API (`src/gittok/learning.py`):
```python
def process_events(conn, cfg, now=None) -> dict            # closed impressions → rewards → model updates; idempotent
def card_features(conn, cfg, card_id) -> list[tuple[str, str]]
class Model:                                                # Model.load(conn, cfg, now)
    def draw(self, rng) -> Draw                             # Draw.logit(feats), Draw.score(feats)
    def mean_logit(self, feats) -> float; def predict(self, feats) -> float
    def update(self, feats, y, c, now) -> None; def save(self, conn) -> int
def relearn(conn, cfg) -> int                               # rebuild model_weights from rewards
def posterior_means(conn, cfg, feature) -> dict[str, tuple[float, float]]  # value -> (expected reward of an average card, evidence)
def value_factors(conn, cfg, feature) -> dict[str, float]  # value -> factor for the brief
def category_shares(conn, cfg) -> dict[str, float]          # learned share per default-mix category
def reset_weights(conn, feature: str | None = None) -> int
```
`process_events` runs in the serve worker every 30 s, via `gittok learn`, and before a feed refresh (section 5).

## 5. Serving the feed (SPEC §12.4) — `src/gittok/slotter.py`

Cards are expensive to make, there are never many, and they are made as the reader scrolls. So the feed has no ranking: it serves every card the reader has not seen, in the order the cards were made. What the reader likes shapes the mix of the cards that get made next (sections 7 and 12), not the order of the ones that exist.

`GET /api/feed?limit=20&cursor=...` builds the next batch. A first page (no cursor) starts with the card of the newest impression, if it is still `ready`, so a reload resumes there (`resume_card_id`); the slots below fill the rest.

1. Candidates: `ready` cards that were never shown (no impression), not already served this feed session (the cursor carries served ids), and not of a repo that is no longer configured. A card once seen comes back only as a due quiz review (step 5).
2. No steering rule applies here: rules shape generation only (section 10).
3. Order: oldest first (`created_at`, then id).
4. Stories and series: variants of one story (same `story_key`, section 13) are never served within `repeat_days` (7) of each other, and a batch holds at most one card per `story_key`, the oldest. Parts of a series stay in order and at least `SERIES_GAP` (3) cards apart, and a part waits for unseen earlier parts.
5. Quiz reviews (SRS): at most `max_srs_per_batch` (2) due cards per batch, placed at positions ≥ 3.

The cursor is an opaque base64 of `{"served": [short ids], "seed": int}`; a malformed cursor is a 400. `seed` makes a batch reproducible for tests.

No refresh after a 👍 or 👎: the cards that the app already holds stay as they are. The thumbs reach the model through the normal learning pass (section 3).

## 6. Spaced repetition (SPEC §12.5)

On a wrong answer (`POST /api/answer`), upsert `srs(card_id)` with interval 1 day. A correct answer on a due card advances 1 → 3 → 7 days; a correct answer at 7 days sets `mastered = 1`. A wrong answer resets to 1 day and streak 0. Due = `due_at <= now and mastered = 0`.

## 7. Brief quotas from weights (SPEC §12.6)

`brief.build_brief` takes optional `category_shares`. Quotas come from the shares instead of the raw default mix, with a floor: every renderable category gets at least 1 card when `count >= number of categories`. The `interactive` category is now renderable (story types `spot_the_bug`, `guess_who`, `guess_when`, `quiz`, `this_or_that`; format `quiz`; packets with interactive slots are sonnet).

How many cards a run makes (`src/gittok/supply.py`): `get_brief` without `count` uses `want`.

- `backlog` = ready cards never shown.
- `burn` = max(distinct cards shown per day, 7-day mean; `agent.min_burn_per_day`).
- `short` = `ceil(agent.target_runway_days * burn) - backlog`.
- `want` = 0 when `short` is 0 or less. Otherwise `want` is `short`, but at least `agent.min_run_count` (8) and at most `agent.max_count`. A run has a fixed start-up cost, so a small shortfall still gets a full run.

When `want` is 0, `get_brief` returns `nothing_to_do` and opens no run. An explicit `count` skips this.

### Learned factors: formats, tones, personas, repos, angles

`learning.value_factors(feature)` gives a factor per value with evidence: exp(effect − mean effect over those values), clamped to [0.25, 4], where effect is how far the evidence moved the weight from its prior. A value without evidence has no factor (1). `mix_inputs` passes them to `build_brief`:

- `format_weights`: `_pick_format` multiplies the factor into the rule boost.
- `tone_weights`: scale the default tone mix (after limits and boosts).
- `persona_weights`: each persona's share of the cards (replaces the plain persona cycle).
- `repo_weights`: scale each repo's share of a category, clamped to [0.25, 4] so no repo starves.
- `angle_weights`: scale the story types of each angle (with the story type's own rule boost), so a reader who likes `why` cards gets more archaeology, rip and commit drama. Each card slot proposes an angle: its story type's default (`brief.ANGLE_OF`), or for an open story type (quiz, this_or_that) the next angle of a pool weighted by the factors. The packet lists them ("angles, one per card"); the writer sets the card's real `angle`, which is what the model learns.

Rules still win: caps and boosts work as before. With no evidence nothing changes.

### Image share target

`config/defaults.yaml` has `visual_mix.image_min_share` (default 0.5). Image formats are the formats whose visual kind is `meme`, `illustration`, `comic`, `chart` or `diagram`. The target is soft. Each packet tells its writer how many of its cards should use an image format: the share times the packet's cards, but never more than the number of its cards whose format list has an image format. No format is forced. A format that cannot be drawn is not in any list: `meme` without the meme server, `mascot_scene` and `comic` without the illustration renderer or for a repo with no mascot. So with no renderer the target counts only `chart` and `diagram`, which the client draws. Without `visual_mix` the target is 0.

## 8. Saved cards

`GET /api/saved` → `{"cards": [Card]}`, most recently saved first. Web route `/saved`.

Saved state lives in the `saved_cards` table (`card_id`, `saved_at`, `saved_ts`). Gc prunes old events, so events alone cannot hold it. `POST /api/events` updates the table in the same transaction as a `save` event. The newest `save` event by `ts` wins: an older event that arrives late changes nothing. A save for an unknown card is ignored. Gc never deletes a saved card (see section 11).

## 9. Reset

`gittok reset-weights [--feature F]` and `learning.reset_weights`. The MCP tool `reset_defaults` calls the same function. Each reset is noted in `model_resets`, so a later `gittok relearn` (section 4) does not bring the weights back.

## 10. What rules change

Rules steer what gets made: `brief.build_brief` reads them for each run. They never change the feed, which serves every unseen card oldest first (section 5). Types: `limit`, `boost`, `prefer`, `focus`. There is no ban: "never X" is a limit with share 0, and anything a rule cannot say goes in the reader's `local/guidance.md`. Boost and prefer use the stored `factor` as is (the steering layer stores the defaults, so `None` counts as 1.0). `dir` rules use path-prefix matching (`src` covers `src` and `src/api`, not `lib/src`; a leading `repo/` is accepted).

| (type, feature) | brief (generation) |
|---|---|
| limit `format`, `story_type`, `repo`, `tone` | share ceiling on matching slots (best effort when no alternative remains); share 0: never assigned, and a repo limited to 0 is left out |
| boost, prefer `format`, `story_type`, `repo`, `group`, `tone` | slot weight times the factor |
| boost, prefer `dir` | matching leads come first |
| boost, prefer `angle` | the story types of that angle get more slots, and open story types get that angle more |
| focus `repo`, `dir` | slot weight (1 + slots) / leads first, plus a focus line |
| focus `format`, `story_type`, `group`, `tone` | like boost with factor 1 + slots |
| any other rule | no effect |

## 11. Garbage collection

Nothing grows without bound. `src/gittok/gc.py` deletes cards and files that have no further use. `GcWorker` runs a pass every `gc.interval_s` (1 hour) inside `gittok serve`. `gittok gc [--dry-run] [--vacuum]` runs one pass and prints the counts as JSON. A dry run changes nothing. `VACUUM` runs only from the CLI.

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

Repos that are not configured. A pass also deletes all that GitTok holds for a repo that is not in `local/repos.yaml` any more (removed by hand, or left by an older version): its cards with every row that hangs off them, the rows keyed by the repo, and the files. This rule does not look at age, saved marks or review dates. The counts are `orphan_repos`, `orphan_cards` and `orphan_files`, also in a dry run. A repo removed with `keep_data` is not touched. The feed and the backlog count never include cards of a repo that is not configured, so such cards are not shown between the removal and the next pass.

Removing a repo (`remove_repo`, `gittok repos remove`) uses the same code at once. `gc.delete_cards` is the one function that deletes cards, and `gc.purge_repo` deletes a repo's data:

| what | on removal of the repo |
|---|---|
| `cards` whose own repo (the first of `repos`) is the repo, with `card_features`, `assets`, `srs` | deleted |
| `events`, `knowledge_events`, `saved_cards`, `replies`, `requests`, `notifications` of those cards | deleted (an old card deleted by the rules above keeps them) |
| `rewards` of those cards | kept without the card link (`card_id` and `impression_event_id` NULL): with their feature snapshot they are the evidence behind the kept weights, so `relearn` keeps what they taught |
| `replies.answered_card_id`, `digests.card_id` that point at such a card | set to NULL |
| `stories` of the repo | deleted, unless a card of another repo still has the story key |
| `leads`, `candidates`, `candidate_ratings`, `scout_batches`, `knowledge`, `knowledge_symbols`, `digests`, `story_views` of the repo | deleted |
| `git_signals`, `fact_*`, `repo_groups`, `mascots` rows of the repo, and its `repos` row | deleted |
| `hot_file` notifications of the repo, `rules` on the repo (`feature = repo`), followed paths of the repo | deleted |
| `runs` of the repo | kept without the repo and the brief (the daily run cap counts them); an open run becomes `expired`; the folder `data/runs/<id>/` is deleted |
| `model_weights` | kept: they are about the reader |
| files | `data/assets/<card_id>/` of each card, after the rows are committed |

The rows go in one transaction and the files after it, so a crash leaves a whole database. Before the rows go, `process_events` runs once, so closed impressions of these cards still reach the model. An impression that is still open (the last minutes) is lost. A card of another repo that only cites the removed repo stays: it is drawn from its stored `resolved` data, and a source in the removed repo has no link.

What stays, and why:

- `stories`: the duplicate check reads it, so a deleted story is not made again.
- `leads` that a card used: coverage history stays.
- `rewards` and `model_weights`: this is what the feed learned. A pass never changes the model.
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
- `times_covered`, `last_covered_at`: see below. (`mean_reward` and `rewards_n` are no longer written: the model learns from the lead's features instead.)

`get_brief` draws leads from the ledger. A row is a candidate when it was seen in the latest refresh of its repo (it still exists at HEAD) and its `last_covered_at` is not within `agent.lead_cooldown_days` (30). Candidates are sorted by one score from the learned model (section 4):

```
score = model log-odds of the lead's features
      + lead_score.strength x ln(strength)
      + lead_score.novelty  x novelty x symbol factor
      - lead_score.covered  x times_covered
      - lead_score.rejected x rejects
```

The lead's features (`ledger.lead_features`) are the ones its card would have before it is written: repo, group, story type, the dir prefixes and `file` of its path, `language`, `kind`, the detector `tag`, and `familiarity`. So what the reader likes decides what gets made, not only what is shown. `get_brief` makes one Thompson draw for all its leads (it explores); other callers use the posterior means. Strength is how teachable the lead is (signal rank, scout rating, rule factor). Novelty stays a fixed term so the feed keeps teaching new code; the learned part of "new or familiar" is the `familiarity` feature. A lead in the dir of a file the reader follows (`POST /api/follows`) gets `lead_score.followed` added. Defaults (reward.yaml `lead_score`): strength 1.0, novelty 1.5, covered 0.7, rejected 0.7, followed 1.0. Ties go to the lower row id. `focus` dir rules still put matching leads first by text. If the repo has no ledger rows for a story type, the brief computes the leads from signals as before. If all rows of a type are in cooldown, the type has no leads.

Dedup (`ledger.ranked`, `ledger.offerable`):

- Subject cooldown: a card's subject is its visual's commit or path, else its first source's. A commit or path that was the subject of a ready (or `pending_render`) card made in the last `agent.subject_cooldown_days` (14) is not offered, in any story type. Server-made leads (`notif:`, digests, replies) skip this filter.
- Rejects: when `submit_cards(packet_id)` rejects a card (not for `over_quota` or `illustration_budget`) that cites a packet lead, the lead gets `times_rejected + 1` and `last_rejected_at`. In `score` it costs `lead_score.rejected` per reject while `last_rejected_at` is inside the subject cooldown window. After the window the penalty is gone, and a later reject counts from 1 again.
- Packets: `build_brief` deals the leads of a (repo, story type) round robin over the packets that hold that type. An intro lead is only in its own packet. A commit or path is offered to one packet of a repo. So two packets of one repo never share a lead.
- Cross-repo leads (recap, drift, ripple) have no ledger row, so they have no cooldown. A card cannot be tied to one of them (it cites commits of several repos and carries no lead id), so coverage would be a guess.

Spot the Bug minimum: `agent.min_spot_the_bug_per_run` (0.125, one card per 8) of a brief's cards are `spot_the_bug` slots, reserved before the category quotas, when some repo has a lead for it. The interactive quota grows to hold them.

Coverage marking: `submit_cards(packet_id)` finds the packet lead each accepted card used. The first lead whose commit is cited by the card (sources, visual, or depth panels) wins. Else the first lead whose path is cited. The card gets `cards.lead_id`. The lead gets `times_covered + 1` and `last_covered_at`. Cards submitted without a packet mark nothing.

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

A repo profile is a YAML file `local/profiles/<repo>.yaml` in GitTok (never in the repo it describes). Its format is `src/gittok/schema/profile.schema.json`. `profiles.py` loads it and rejects unknown keys, a bad tag, a weight outside 0.1 to 3, a rule with both or neither of `regex` and `ast_grep`, and a bad glob. Each error names the detector id. A repo with no file has an empty profile: built-in miners only. Rules are data. GitTok never runs code from a profile.

The profile also owns the file set. `scan` (globs of files read), `ignore` (globs never read) and `kinds` (`test`, `fixture`, `generated`, `docs`, `vendored` -> globs) come from the profile; `generated_markers` (regexes for generated headers) is optional. A file is read iff it matches `scan` and not `ignore`. `kinds` classify read files: `test` sets `is_test`; generated, vendored and fixture files are never mined but stay classified for the intro, `whose_code` and the repo map. `profiles.FileSet` is the one classifier (`reads`, `kind`, `is_test`, `is_code_dir`). The bootstrap values are in `config/scan_defaults.yaml` (scan, ignore, kinds, generated markers, noise), with the user's `local/scan_defaults.yaml` merged over them for all repos (`docs/config.md`). They apply per key: a key the profile sets replaces the default, a key it omits uses it. No merging, so the agent is in control. A scanned file with no known language gets the `text` language: only the plain text rules (see the structure layer below) and profile rules apply. `noise` (lockfiles, source maps, images) always keeps such paths out of story leads. No Python file may hold path or extension lists (a test greps for them).

`detectors.py` runs the rules over the files of the file set (same size caps). A `regex` rule uses the `regex` module with a 0.2 s limit for each file and rule. A timeout logs the rule and file, and skips them. Lines over 1000 characters are not matched. An `ast_grep` rule needs `ast-grep-py`, a normal dependency. If it is missing, these rules are skipped with one log line. ast-grep supports Python, TypeScript, JavaScript and others, but not Clojure. The profile `ignore` globs also remove built-in candidates. `candidates.rule_id` holds the rule id (NULL for built-ins), and `load_candidates` and `load_rated` return it. `Config.role_for(repo, path)` gives the role of the longest matching dir in `roles`.

Per-rule outcomes (`rule_stats.py`, MCP tool `rule_stats(repo)`, `rule_outcomes` in `get_taste_profile`). Each rule id, and each built-in tag as `builtin:<tag>`, gets: candidates found, rated, mean teachable, cards made, mean reward of those cards, and their `knew_it` and `teach_more` counts. A card traces to its rule through `cards.lead_id -> leads.lead_key "cand:<path>:<start>:<tag>" -> candidates.rule_id`. The outcome factor is `clamp(0.5, 1.5, (5 + N x q) / (5 + N))`. N is rated windows plus rewarded cards. q is the N-weighted mean of `mean teachable / 3` and `mean card reward / mean reward of the repo`. A rule with no data has factor 1.0. `candidate_leads.leads_for` multiplies the lead strength by the factor; `rule_stats.effective_weight(weight, factors, rule)` gives the scaled profile weight. The stored candidate `score` is not changed.

When a profile is written. A repo with no profile is profiled by the agent without a question: right after `add_repo`, from the `gittok health --hint` line, and in step 0 of the `gittok-generate` skill (`list_repos` gives `profiled: true|false` for each repo). A repo that has a profile is revised only on request. `gittok health --hint` makes the agent offer it in two cases: the manifests changed since the profile (`profiling.profile_hint`), or `profiling.reprofile_hint` finds `WEAK_RULES_MIN` (3) or more rules of the profile with a factor under 0.8 (`rule_stats.weak_rules`). A factor that low needs data: with the prior of 5, at least 3 windows that the scout rated 1. The second offer names a repo at most once in 7 days (`REPROFILE_OFFER_DAYS`; the time is in the `prefs` table under `reprofile_offer:<repo>`). `survey_repo` gives `structure.missing_grammars`, so the profile skill can offer the grammar download at that moment.

Every lead built from git signals passes the repo's file set (`brief.lead_in_files`, applied at the end of `lead_refs_for`, so the ledger refresh and the no-ledger fallback are both clean). A path, or both files of a pair, must be read by the profile and not of kind generated, vendored or fixture; a dir lead must be a code dir; a commit lead with no path is dropped when every path it touched is outside the set (the `huge_diffs`, `late_night` and `recent_commits` signals carry them). `ledger._current` applies the same check to stored rows. Pinned server leads are exempt.

Intro slots use code dirs only (`brief.code_path`: no hidden, test, fixture, cassette, snapshot, vendored, generated or docs dirs), and prefer dirs that hold a `core` or `entry_point` candidate. `whose_code` never offers the root dir or hidden dirs.

### The structure layer

Shipping a regex set per language does not scale, so the miners read code through three layers. A file uses the first layer that can read it.

1. **Structure** (`structure.py`, tree-sitter, a normal dependency). Tree-sitter parses the file. Tags queries in `config/queries/<grammar>.scm` say what a definition, a reference, a comment and an import look like. `config/queries/languages.yaml` holds the rest as data: extensions, which node types nest and branch, how to count parameters, what is public, the head symbols of a Lisp (`def_heads`). Shipped: python, typescript (also tsx, javascript, jsx, svelte `<script>`), clojure, go, ruby, java, rust. The user's `local/queries/` can change a query or add a language for all repos.
2. **Regex patterns** (`config/languages.yaml`: python, clojure, typescript, go, rust, java, ruby, kotlin, csharp, php, swift; `local/languages.yaml` is merged over it). Used when the grammar is missing or the language has no query, and for what is a pattern, not structure: entry points, catch-all, sleep, regex literals, bit operations, skipped tests, metaprogramming, commented-out code, long lines, big literals.
3. **Plain text**, for a file with neither (a scanned file type with no grammar, such as `.zig` in a profile `scan`). The miners find `smell` markers in comment-like lines (prefixes in `text_fallback.comment_prefixes`), `long_line`, and `deep_nesting` by indentation. Data and prose extensions (`text_fallback.skip_extensions`) and `docs` files are skipped.

The pack downloads a grammar bundle on first use. Mining never starts that download: a grammar counts only when it is already in the local cache (`structure.ready`). `gittok structure --prefetch` fetches the grammars for the languages in the configured repos, and `gittok health --hint` prints one line when the group is installed but a grammar is missing. Until then those files use layer 2 or 3.

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

`save_profile` checks each query: it must compile for the grammar, use only the captures above, read at least one file of the file set and find something in it. A failure comes back in `errors["queries.<grammar>"]`; a pass returns `queries: {<grammar>: {files, defs}}`. If tree-sitter cannot be imported (a broken install), the query cannot be checked, so the save is refused. `survey_repo` returns a `structure` block: whether the layer is installed, what is shipped, and the file types in the repo that have a grammar in the pack but no query here (`uncovered`).

## 13. Story variants

A story that did well can be told again in another format. The `story_key` stays the same (it comes from the story type and the sources, not the format). Uniqueness on `cards` is per `(story_key, format)`. `stories.formats` is a JSON list of the formats already used. It lives on the story row, so it survives gc.

`submit_cards` and `check_cards` accept a card of an existing story only when all of these hold. If one fails, the card is rejected as `duplicate_story` and the detail names the failed condition.

- Its format is not in `stories.formats`.
- The story's `best_reward` is at least `agent.variant_min_reward` (0.6), or the story is liked.
- The story's last card is at least `agent.variant_after_days` (14) old.

The decision is `store.variant_blocker`. Two cards of one story in the same submission are always a duplicate.

The brief offers variants. `ledger.variants` lists the stories that meet the reward and age conditions (liked first, then best reward). It adds the hook of the newest card; if gc deleted every card, the lead has the story type and sources only. `build_brief` uses a variant for a slot only when that slot has no fresh lead: its (repo, story type) has fewer leads than slots. The variant must be in the slot's repo and a story type of the slot's category. At most `floor(agent.variant_max_share x count)` slots (0.2) become variants. A variant slot keeps the story's story type and gets a format of the category that the story has not used. The packet lead reads `[variant] retell "<hook>" (<story type>, first told as <formats>) as a <format>; cite the same sources: <sources>`. Its `lead_refs` entry is `{"kind": "variant", "story_key", "sources"}`. A variant lead marks no ledger coverage.

## 14. What the reader knows (knowledge model) — `src/gittok/knowledge.py`

The `knowledge` table (migration 0012) holds counts per `(repo, dir)`: `cards_seen`, `explains_opened`, `quiz_right`, `quiz_wrong`, `last_seen_ts`. `process_events` calls `knowledge.update_in_tx` after the rewards, in the same transaction.

Events counted:

| count | event |
|---|---|
| `cards_seen` | `impression`, once per card |
| `explains_opened` | `depth_open` whose `panel` is the explain panel, once per card. Panel 0 is the visual; depth panel `i` is panel `i + 1`. The explain panel is the first depth panel of kind `explain`. |
| `quiz_right`, `quiz_wrong` | `answer` with `correct` true or false (the server sets it). `null` counts nothing. |

Idempotent: each counted event is written to `knowledge_events(event_id, ts)`. An event already there is skipped, so reprocessing changes nothing. This is the same idea as `rewards.impression_event_id`.

A card counts toward each repo in its `repo` features and each of its `dir` features, cut to the first 2 path levels: `a/b/c` counts toward `a` and `a/b`. A deeper dir is not tracked, because the reader learns an area, not a file. Cards with no dir count nothing.

Novelty (0 = known, 1 = new), `knowledge.novelty(conn, repo, dir)`:

```
pos      = cards_seen + 2 explains_opened + 2 quiz_right
struggle = quiz_wrong
n = 1 / (1 + pos / 4)                          # never seen: 1
n = n + (1 - n) * struggle / (struggle + 2)    # wrong answers lift it
n = n + (1 - n) * 0.3 * min(1, commits_30d / 10)   # others changed it lately (signals churn, 30 days)
n = n * (1 - 0.25 * own_share)                 # only when settings.user.git_identities is set
```

A dir with no row has novelty 1. `commits_30d` comes from the stored churn signal (top 25 dirs per window; others count 0). `own_share` is the reader's share of changed lines in the top-level dir (signal `author_shares`, matched by name, case-insensitive). It lowers novelty by at most 25%, because the reader often studies code that other people wrote. `settings.user.git_identities` defaults to empty.

`knowledge.novelty_map(conn, repo)` gives `{dir: novelty}` for every dir with counts or with a card. The `coverage` tool adds `novelty` to each top-level dir (1.0 when unknown). `get_taste_profile` adds `knowledge`: the 10 most novel dirs.

### Knowledge per symbol

The `knowledge_symbols` table (migration 0023) holds the same counts per `(repo, symbol)`: `seen`, `explains_opened`, `quiz_right`, `quiz_wrong`, `last_seen`. The symbol is `fact_defines.symbol` from the syntax facts. It is updated in the same pass as the dir counts (same events, same once-per-card rule, same `knowledge_events` guard, so reprocessing changes nothing).

A card's symbols (`knowledge.card_symbols`): the symbols named by `resolved["facts"]` when the card has them; else the innermost definitions that overlap the lines of its code visual and code panels, plus backticked names (`` `name` `` or `` `name()` ``) that match at most 3 definitions in the card's repos.

A symbol's novelty is the dir formula (`knowledge.combine`) without churn and authorship. Lead ranking multiplies the dir novelty by a symbol factor (`knowledge.SymbolContext.factor`), from the innermost definitions in the lead's window:

```
f = 0.5 + 0.5 * max(novelty(symbol))       # all symbols seen: down to 0.5
f = f * 1.3                                # the window defines an unseen symbol that calls or is called by a seen one
```

A window with no known definitions, or a repo with no symbol knowledge, has factor 1. The repo map API adds `files`: for the 15 files with most functions, methods and classes, `symbols_defined` and `symbols_seen`. The UI shows "4 of 12 functions seen".

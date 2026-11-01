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
6. Series: parts of a series stay in order and at least 3 cards apart (series is null until M5; keep the hook).
7. SRS: at most 2 due cards per batch, placed at positions ≥ 3.

The cursor is an opaque base64 of `{"served": [short ids], "seed": int}`; a malformed cursor is a 400. `seed` makes a batch reproducible for tests.

## 6. Spaced repetition (SPEC §12.5)

On a wrong answer (`POST /api/answer`), upsert `srs(card_id)` with interval 1 day. A correct answer on a due card advances 1 → 3 → 7 days; a correct answer at 7 days sets `mastered = 1`. A wrong answer resets to 1 day and streak 0. Due = `due_at <= now and mastered = 0`.

## 7. Brief quotas from weights (SPEC §12.6)

`brief.build_brief` takes optional `category_shares`. Quotas come from the shares instead of the raw default mix, with a floor: every renderable category gets at least 1 card when `count >= number of categories`. The `interactive` category is now renderable (story types `spot_the_bug`, `guess_who`, `guess_when`, `quiz`, `this_or_that`; format `quiz`; packets with interactive slots are sonnet).

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

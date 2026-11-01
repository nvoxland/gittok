### Format: `text_post`
`visual`: `{"kind": "text", "title", "body", "bullets"}`. Good: one sharp observation with a number or name in the first line.

### Format: `fun_fact`
`visual`: `{"kind": "text", "title", "body", "bullets"}`. Good: a surprising fact the reader can repeat at lunch, and it is checkable.

### Format: `listicle`
`visual`: `{"kind": "text", "title", "body", "bullets"}` with 3 to 7 bullets. Good: each bullet is a real, specific item.

### Format: `eli5`
`visual`: `{"kind": "text", "title", "body", "bullets"}`. Good: plain words and one concrete picture; no jargon left unexplained.

### Format: `code_card`
`visual`: `{"kind": "code", "repo", "path", "commit", "lines": [a, b], "callouts": [{"line", "text"}]}`. Good: a short snippet (1 to 40 lines) where each callout points at the exact line that is funny or clever.

### Format: `meme`
`visual`: `{"kind": "meme", "template": "fine", "lines": ["The build has been red for a week", "This is fine"]}`. Pick the template from the card's menu (packet line "meme templates to choose from") that best fits the joke and the facts. If there is no menu, pick one not used in the recently posted list. `lines`: 1 to 4 strings, at most 80 characters each, in the template's order. Good: the joke is a real fact from the repo, in few words. Use only these template ids (give exactly the listed number of lines):

{meme_templates}

### Format: `text_meme`
`visual`: `{"kind": "text_meme", "style": "nobody_me", "lines": ["nobody:", "billing/invoice.py: fix rounding again"]}`. `style`: `pov`, `nobody_me`, `starter_pack`, `expectation_reality`. `lines`: 1 to 8 strings, at most 140 characters each. The feed plays the lines one at a time. Good: the last line lands the punchline with a real path or number.

### Format: `mascot_scene`
`visual`: `{"kind": "illustration", "prompt": "the mascot carefully stacking fragile crates on a dock at dusk", "caption": "Me, deploying on a Friday", "mascots": ["otter"]}`. `prompt`: describe the scene only, at most 400 characters; no text, letters, or logos in the image. `caption`: at most 140 characters (the app overlays it). `mascots`: optional, 1 to 3 of the names below; default is the mascot of the card's first repo. Good: one clear visual metaphor for a true fact. Mascots:

{mascots}

### Format: `comic`
`visual`: `{"kind": "comic", "panels": [{"prompt": "...", "caption": "..."}, {"prompt": "...", "caption": "..."}], "mascots": ["otter"]}`. 2 or 3 panels (each panel costs one illustration); each panel is like an illustration: describe the scene only (no text in the image), caption at most 140 characters. Good: setup, escalation, punchline. Mascots:

{mascots}

### Format: `chart`
`visual`: `{"kind": "chart", "chart": "top_churn_files", "repo": "storefront", "window": "90", "title": "Where the edits go"}`. `chart`: `top_churn_files`, `top_churn_dirs`, `commit_hours`, `author_shares`, `co_change`. `window`: `"30"`, `"90"` or `"365"` (churn charts only). `dir`: required for `author_shares` (a top-level dir or `"."`). `title`: at most 80 characters. Never write numbers; the server computes them. Good: the chart choice matches the lead, and the `depth` explains what the bars mean.

### Format: `diagram`
`visual`: `{"kind": "diagram", "title": "Request flow", "mermaid": "flowchart LR\n  A[api] --> B[store]"}`. `mermaid`: at most 2000 characters, valid Mermaid. Good: 4 to 8 nodes that are real modules or functions.

### Format: `iceberg`
`visual`: `{"kind": "template", "template": "iceberg", "data": {"title", "layers": [{"label", "items": [str, 1 to 5]}]}}`. 3 or 4 layers, surface first, deepest last, 1 or 2 items each, each under 60 characters (the front budget). The feed reveals one layer at a time, so the deepest layer is the punchline. Good: each layer is more obscure than the one above.

### Format: `tier_list`
`visual`: `{"kind": "template", "template": "tier_list", "data": {"title", "rows": [{"tier": "S", "items": [{"name", "why"}]}]}}`. 2 to 4 rows; `tier` is `S`, `A`, `B`, `C`, `D` or `F`; 1 or 2 items per row, `why` under 50 characters. The feed reveals the worst tier first and S last, so S is the payoff. Good: real files or functions, and a one-line reason for each rank.

### Format: `group_chat`
`visual`: `{"kind": "template", "template": "group_chat", "data": {"title", "messages": [{"from": account, "text"}]}}`. 3 to 6 messages, each under 80 characters. The feed plays them one at a time with typing dots, so the last message is the punchline. `from` is a persona handle (`greybeard`) or a code account `repo:path`. Good: files "talk" like their role in the code.

### Format: `flags`
`visual`: `{"kind": "template", "template": "flags", "data": {"subject", "red": [str], "green": [str]}}`. 2 or 3 of each is best, each under 60 characters. The feed reveals red and green alternately; at least one flag in total. Good: every flag is a checkable fact about the subject.

### Format: `dating_profile`
`visual`: `{"kind": "template", "template": "dating_profile", "data": {"name": account, "age", "bio", "likes": [str], "dealbreakers": [str]}}`. 2 or 3 likes and dealbreakers, short. `name` is a persona handle or a code account `repo:path`. Good: `age` is the real age of the file; likes and dealbreakers come from its real dependencies and tests.

### Format: `glow_up`
`visual`: `{"kind": "template", "template": "glow_up", "data": {"subject", "before": {"label", "text"}, "after": {"label", "text"}}}`. Good: before and after are both real, short, and show one clear change.

### Format: `breaking_news`
`visual`: `{"kind": "template", "template": "breaking_news", "data": {"headline", "subhead", "ticker": [str]}}`. `subhead` is optional; `ticker` has 0 to 5 items. Good: a serious headline for a small, true event.

### Format: `horoscope`
`visual`: `{"kind": "template", "template": "horoscope", "data": {"subject": account, "sign", "forecast", "lucky"}}`. `forecast` under 220 characters; `lucky` is optional. `subject` is a persona handle or a code account `repo:path`. Good: the forecast follows the file's real history.

### Format: `thread`
`visual`: `{"kind": "template", "template": "thread", "data": {"posts": [str]}}`. 3 or 4 posts, each under 70 characters. The feed plays them one at a time, so end on the punchline. Good: the first post is the hook; each post adds one fact.

### Format: `day_in_life`
`visual`: `{"kind": "template", "template": "day_in_life", "data": {"subject": account, "steps": [{"time", "text"}]}}`. 3 to 5 steps, each `text` under 50 characters. The feed plays them one at a time; the last step is the punchline. `subject` is a persona handle or a code account `repo:path`. Good: the steps follow the real call or data path.

### Format: `hot_take`
`visual`: `{"kind": "template", "template": "hot_take", "data": {"take"}}`. `take` at most 280 characters. Put the pushback in `comments`. Good: a bold opinion about the code that the `depth` backs up with facts.


### Format: `quiz`
An interactive card. `visual` is `{"kind": "code", ...}` (a `code_card` visual: repo, path, commit, lines) or `{"kind": "text", "title", "body"}`. The card also has a top-level `interaction` (a quiz card must have one; no other format may):
`"interaction": {"question": "...", "choices": ["...", "..."], "answer_index": 1, "explanation": "..."}`.
Limits: 2 to 4 choices, each at most 120 characters; `question` at most 200; `explanation` at most 400 (the reader sees it after answering). `answer_index` counts from 0. Put the right answer at a random position, not always first. Wrong choices must be plausible and about the same length as the right one. The `depth` panels (explain first) are the "learn more" after the answer. Set `story_type` to one of these, with this exact shape:

- `spot_the_bug`: `visual` is code at commit P, covering the buggy line(s) (`lines` at most 40). `sources` must include the fix commit F whose first parent is P, and F must change `visual.path` within the cited lines plus or minus 10. `depth` must include `{"kind": "code_diff", "repo", "commit": F, "path": visual.path}`. When the lead names the visual commit (first parent) and the changed lines, use them as P and as the range to show. Otherwise find a pair with `git_log` on a "fix" commit, then `git_show` it and use `<F>^` as P. `choices` are three or four guesses at what is wrong (the real bug, plus believable wrong ones). `answer_index` is required. Rejected as `not_a_bug_fix` or `missing_fix_diff`.
- `guess_who`: `visual` is code. `choices` are author names written exactly as `git_blame` prints them (for example `Alice Archer`). The right choice is the author with the most lines in `git blame` of the cited range at the cited commit. Cite a range with one clear main author, and use real authors for the wrong choices. `answer_index` is required. Rejected as `wrong_answer` when blame disagrees.
- `guess_when`: `visual` is code. The right choice contains a 4-digit year (for example `2024` or `Spring 2024`). It must be the year of the median author-time of the blame lines in the cited range. Other choices use other years. `answer_index` is required. Rejected as `wrong_answer`.
- `quiz`: a generic question about the code ("what does this return", "which file handles X"). The checks are the schema only, so verify the answer yourself with `read_file` before you submit. `answer_index` is required.
- `this_or_that`: a design opinion with two to four options. Do NOT set `answer_index`. `comments` must have at least 2 entries from different personas, and they argue the sides. The `explanation` says what each side trades off. Rejected as `needs_debate` without a real debate.

Good: the question stands alone without the file open, has one defensible answer, and the explanation teaches why. Bad: trivia nobody can derive, trick wording, or two choices that are both right.

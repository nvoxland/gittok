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
`visual`: `{"kind": "meme", "template": "drake", "lines": ["Reading the docs", "Reading git blame"]}`. `lines`: 1 to 4 strings, at most 80 characters each, in the template's order. Good: the joke is a real fact from the repo, in few words. Use only these template ids (give exactly the listed number of lines):

{meme_templates}

### Format: `text_meme`
`visual`: `{"kind": "text_meme", "style": "nobody_me", "lines": ["nobody:", "billing/invoice.py: fix rounding again"]}`. `style`: `pov`, `nobody_me`, `starter_pack`, `expectation_reality`. `lines`: 1 to 8 strings, at most 140 characters each. Good: the last line lands the punchline with a real path or number.

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
`visual`: `{"kind": "template", "template": "iceberg", "data": {"title", "layers": [{"label", "items": [str, 1 to 5]}]}}`. 3 to 6 layers, surface first, deepest last. Strings at most 200 characters. Good: each layer is more obscure than the one above.

### Format: `tier_list`
`visual`: `{"kind": "template", "template": "tier_list", "data": {"title", "rows": [{"tier": "S", "items": [{"name", "why"}]}]}}`. 2 to 6 rows; `tier` is `S`, `A`, `B`, `C`, `D` or `F`; 1 to 4 items per row. Good: real files or functions, and a one-line reason for each rank.

### Format: `group_chat`
`visual`: `{"kind": "template", "template": "group_chat", "data": {"title", "messages": [{"from": account, "text"}]}}`. 2 to 10 messages. `from` is a persona handle (`greybeard`) or a code account `repo:path`. Good: files "talk" like their role in the code.

### Format: `flags`
`visual`: `{"kind": "template", "template": "flags", "data": {"subject", "red": [str], "green": [str]}}`. 0 to 5 of each, at least one flag in total. Good: every flag is a checkable fact about the subject.

### Format: `dating_profile`
`visual`: `{"kind": "template", "template": "dating_profile", "data": {"name": account, "age", "bio", "likes": [str], "dealbreakers": [str]}}`. 1 to 5 likes and dealbreakers. `name` is a persona handle or a code account `repo:path`. Good: `age` is the real age of the file; likes and dealbreakers come from its real dependencies and tests.

### Format: `glow_up`
`visual`: `{"kind": "template", "template": "glow_up", "data": {"subject", "before": {"label", "text"}, "after": {"label", "text"}}}`. Good: before and after are both real, short, and show one clear change.

### Format: `breaking_news`
`visual`: `{"kind": "template", "template": "breaking_news", "data": {"headline", "subhead", "ticker": [str]}}`. `subhead` is optional; `ticker` has 0 to 5 items. Good: a serious headline for a small, true event.

### Format: `horoscope`
`visual`: `{"kind": "template", "template": "horoscope", "data": {"subject": account, "sign", "forecast", "lucky"}}`. `forecast` at most 400 characters; `lucky` is optional. `subject` is a persona handle or a code account `repo:path`. Good: the forecast follows the file's real history.

### Format: `thread`
`visual`: `{"kind": "template", "template": "thread", "data": {"posts": [str]}}`. 2 to 8 posts, at most 280 characters each. Good: the first post is the hook; each post adds one fact.

### Format: `day_in_life`
`visual`: `{"kind": "template", "template": "day_in_life", "data": {"subject": account, "steps": [{"time", "text"}]}}`. 3 to 8 steps. `subject` is a persona handle or a code account `repo:path`. Good: the steps follow the real call or data path.

### Format: `hot_take`
`visual`: `{"kind": "template", "template": "hot_take", "data": {"take"}}`. `take` at most 280 characters. Put the pushback in `comments`. Good: a bold opinion about the code that the `depth` backs up with facts.

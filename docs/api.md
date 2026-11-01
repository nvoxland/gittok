# Feed API contract (M1)

All endpoints are served by `codescroll serve` (default `http://127.0.0.1:8008`). JSON everywhere.

## GET /api/feed?limit=20&cursor=<opaque>

```json
{
  "cards": [Card, ...],
  "next_cursor": "string or null"
}
```

`Card` is the stored card spec (see `schema/card.schema.json`) plus server fields:

```json
{
  "id": "c_01H...",
  "created_at": "2026-10-30T12:00:00Z",
  "repo": "gittok",
  "story_type": "hot_spot",
  "format": "code_card",
  "persona": "greybeard",
  "tone": "dry-deadpan",
  "hook": "This file has been edited 41 times in 90 days.",
  "visual": { "kind": "code", "repo": "gittok", "path": "src/x.py", "commit": "<full sha>", "lines": [10, 24], "callouts": [{ "line": 12, "text": "..." }] },
  "depth": [ { "kind": "explain", "text": "..." }, { "kind": "code", "repo": "...", "path": "...", "commit": "...", "lines": [1, 5] } ],
  "comments": [ { "persona": "penny_learns", "text": "..." } ],
  "sources": [ { "repo": "gittok", "commit": "<full sha>" } ],
  "resolved": {
    "visual": { "code": "line10\nline11\n...", "language": "python", "start_line": 10 },
    "depth": [ null, { "code": "...", "language": "python", "start_line": 1 } ]
  }
}
```

`resolved` holds text the server read from git. The client renders code only from `resolved`, never from model output. For `code_diff` depth panels, `resolved.depth[i]` is `{ "diff": "<unified diff>" }`. For `text` visuals, `resolved.visual` is `null` and the client uses `visual.title`, `visual.body`, `visual.bullets`.

## GET /api/cards/{id}

One `Card`, or 404.

## GET /api/repos

`{ "repos": [ { "name": "...", "ref": "HEAD", "head_sha": "...", "group": null } ] }`

## POST /api/events

```json
{ "events": [ { "card_id": "c_...", "type": "impression|dwell|skip|scroll_back|depth_open|like|explain_more|answer|source_tap", "ts": 1730000000000, "data": { "ms": 4200, "panel": 1 } } ] }
```

Response: `{ "stored": 3 }`. Unknown types are rejected with 422.

## MCP `get_packet(run_id, packet_id)`

Not an HTTP route. A writer subagent calls it for one work packet. Fields:

- `id`, `repo`, `repos`, `count`, `suggested_model`, `categories`, `story_types`, `formats`, `tones`, `personas`.
- `leads`: lead text, one per line of `packet_markdown`.
- `lead_refs`: one object per lead, same order. Keys: `story_type`, `repo`, `kind` (`commit`, `path`, or `none`), `commit`, `path`, `lines` (`[start, end]` or null), `text`, `id` (the lead ledger row, or null for a lead computed on the fly). `submit_cards(packet_id)` uses `id` to mark the lead covered.
- `packet_markdown`: the packet, focus lines, and recent stories not to repeat.
- `materials_markdown`: evidence for the leads. A commit lead gets subject, author, date, `--stat` (15 files), and the diff of the most-changed file (80 lines). A path lead gets the blob sha, 60 numbered lines, top 3 blame authors, and first and last commit dates. At most 6 KB per lead and 30 KB per packet, cut with `[truncated]`. Computed on each call, not stored.
- `guidance_markdown`: card-writing rules and the sections for the packet's formats.

`finish_run` returns `seconds_per_card`: run duration divided by accepted cards, rounded to 0.1 s (null when no card was accepted).

## POST /api/answer

Body: `{ "card_id": "c_...", "choice": 0, "session": "..." }`. Returns the reveal `{ "correct", "answer_index", "explanation" }`. A card id that does not exist (for example, deleted by garbage collection) returns 404. A card with no question, or a bad `choice`, returns 400. The Quiz component shows "This card is gone." on 404 and does not retry.

## GET /healthz

`{ "ok": true }`

## MCP: feed_health and get_brief

`feed_health()` is a read-only MCP tool. `codescroll health` prints the same JSON.

```json
{ "backlog": 41, "burn_per_day": 12.0, "runway_days": 3.4, "target_days": 3,
  "want": 0, "pending_render": 2, "render_failed": 0,
  "image_share": { "ready": 0.02, "shown_7d": 0.0 }, "db_mb": 3.1, "assets_mb": 0.6,
  "gc": { "at": "2026-06-01T12:00:00Z", "counts": { "seen": 4, "liked": 0, "unseen": 1 } } }
```

- `backlog`: ready cards with no impression in the last `repeat_days`.
- `burn_per_day`: distinct cards shown per day, mean of 7 days, never below `agent.min_burn_per_day`.
- `want`: how many cards to make so the backlog lasts `agent.target_runway_days`. It is 0, or between `agent.min_run_count` and `agent.max_count`.
- `gc`: when the last real garbage collection pass ran and what it deleted, or `null` before the first pass (see docs/learning.md).
- `image_share`: share of cards with a meme, illustration, comic, chart, or diagram visual.

`get_brief(repo=None, count=None)`: without `count`, it makes `want` cards. When `want` is 0, it returns `{"run_id": null, "nothing_to_do": true, "health": {...}}`. It opens no run, analyzes no repo, and does not count toward `per_day_runs`. An explicit `count` always opens a run.

Once per UTC day, when `runway_days < 1`, the notify worker adds a `low_runway` notification (`dedup_key` `low_runway:<date>`).

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

## GET /healthz

`{ "ok": true }`

## MCP: feed_health and get_brief

`feed_health()` is a read-only MCP tool. `codescroll health` prints the same JSON.

```json
{ "backlog": 41, "burn_per_day": 12.0, "runway_days": 3.4, "target_days": 3,
  "want": 0, "pending_render": 2, "render_failed": 0,
  "image_share": { "ready": 0.02, "shown_7d": 0.0 }, "db_mb": 3.1, "assets_mb": 0.6 }
```

- `backlog`: ready cards with no impression in the last `repeat_days`.
- `burn_per_day`: distinct cards shown per day, mean of 7 days, never below `agent.min_burn_per_day`.
- `want`: how many cards to make so the backlog lasts `agent.target_runway_days` (0 to `agent.max_count`).
- `image_share`: share of cards with a meme, illustration, comic, chart, or diagram visual.

`get_brief(repo=None, count=None)`: without `count`, it makes `want` cards. When `want` is 0, it returns `{"run_id": null, "nothing_to_do": true, "health": {...}}`. It opens no run, analyzes no repo, and does not count toward `per_day_runs`. An explicit `count` always opens a run.

Once per UTC day, when `runway_days < 1`, the notify worker adds a `low_runway` notification (`dedup_key` `low_runway:<date>`).

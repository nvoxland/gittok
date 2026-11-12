# Feed API contract

All endpoints are served by `gittok serve` (default `http://127.0.0.1:8008`). Request and response bodies are JSON, except where a route says otherwise (`/pair`, `/assets/*`, `/api/avatars/*`, the web app). The routes are defined in `src/gittok/api.py`.

## Routes

"Auth" is the same for every route unless the table says otherwise: see "Access rules".

| Method | Path | What it does |
|---|---|---|
| GET | `/api/feed` | One page of the feed |
| GET | `/api/cards/{id}` | One card |
| POST | `/api/events` | Store a batch of reader events |
| POST | `/api/answer` | Answer a quiz card |
| GET | `/api/saved` | The saved cards |
| POST | `/api/replies` | Reply to a comment |
| GET | `/api/stories` | The stories row |
| POST | `/api/stories/seen` | Mark story commits as seen |
| GET | `/api/notifications` | The notifications |
| POST | `/api/notifications/read` | Mark notifications as read |
| GET | `/api/repos` | The configured repos |
| GET | `/api/repos/{name}` | One repo's profile page |
| GET | `/api/repos/{name}/map` | One repo's knowledge map |
| GET | `/api/personas/{handle}` | One persona's page |
| GET | `/api/files/{repo}/{path}` | One file's page |
| POST | `/api/follows` | Follow or unfollow a path |
| GET | `/api/prefs` | Reader preferences |
| GET | `/api/avatars/{handle}` | A persona avatar image |
| GET | `/assets/{folder}/{file}` | A card image or mascot image |
| GET | `/pair?t=<token>` | Pair a LAN device (no cookie needed) |
| GET | `/healthz` | Liveness |
| any | `/mcp` | The MCP endpoint (loopback peers only) |
| GET | any other path | The web app (`index.html` for unknown paths) |

## Access rules

The server checks each request in this order. The first check that fails answers the request.

1. **Host.** The `Host` header must be a known local name: `127.0.0.1`, `localhost`, `[::1]`, one of this machine's LAN IPv4 addresses, its host name (also the short name and `<short name>.local`), or a name in `server.allowed_hosts` (`config/settings.yaml` or `local/settings.yaml`). The port is ignored. Any other, missing or repeated `Host` gets **421** `{"detail": "unknown Host"}`. This applies to every path.
2. **Origin.** A request that is not `GET`, `HEAD` or `OPTIONS` and has an `Origin` header whose host is not in the same list gets **403** `{"detail": "cross-origin request"}`. A request with no `Origin` passes.
3. **MCP.** `/mcp` answers only peers with a loopback address. Other peers get **403** `{"detail": "MCP is loopback-only"}`.
4. **Pairing.** When the server has a pairing token, a peer that is not loopback needs the `cs_lan` cookie on every path except `/pair`. The server has a token whenever it binds a non-loopback address (`--lan`, `server.lan: true`, or a non-loopback `--host`). Without the cookie, `/api/*` gets **401** `{"detail": "pair this device"}` and every other path gets a 401 HTML page. Loopback peers never need the cookie. The web app shows "This device is not paired" on a 401 from the feed.
5. **Body size.** A body over 1 MB gets **413** `{"detail": "request body too large"}`. A `Content-Length` that is not a number gets **400** `{"detail": "bad content-length"}`.

"Loopback" is decided from the address of the TCP peer. The server does not read `X-Forwarded-For`. A reverse proxy on the same machine is therefore a loopback peer: see `docs/install.md`, "HTTPS on a LAN".

Every response has `Content-Security-Policy`, `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer` (see `docs/social.md`, "LAN access").

## Errors

There is no machine-readable error code. An error is an HTTP status plus a JSON body with one key, `detail`. A client can only use the status; the `detail` text can change.

| Status | Body | When |
|---|---|---|
| 400 | `{"detail": "<text>"}` | A bad value: `invalid cursor`, `card has no question to answer`, a bad `choice`, a bad reply, `send ids or all`, `bad content-length` |
| 401 | `{"detail": "pair this device"}` | `/api/*` from an unpaired LAN device. `/pair` with a wrong token: `{"detail": "bad pairing token"}` |
| 403 | `{"detail": "<text>"}` | `cross-origin request`, or `MCP is loopback-only` |
| 404 | `{"detail": "unknown card <id>"}` and the like | An unknown card, repo, persona or asset |
| 413 | `{"detail": "request body too large"}` | A body over 1 MB |
| 421 | `{"detail": "unknown Host"}` | A `Host` header that is not a known local name |
| 422 | `{"detail": [{"type", "loc", "msg", "input", ...}]}` | The body or a query parameter does not match the route's schema (FastAPI validation). Here `detail` is a list, not a string. |

A 401 on a path outside `/api/` is an HTML page, not JSON.

## GET /api/feed

Query parameters: `limit` (1 to 50, default 20), `cursor` (the `next_cursor` of the page before), `repo` and `dir` (optional: only cards of that repo, or under that directory of it). A cursor that the server cannot read returns 400 `invalid cursor`.

```json
{
  "cards": [Card, ...],
  "next_cursor": "string or null",
  "resume_card_id": "string or null"
}
```

`resume_card_id` is set only when there is no `cursor`. It is the card of the newest `impression` event, if that card still exists and is `ready`. The server puts that card first, so a reload opens on the card you saw last. The page still has `limit` cards. The card is also in the served list of `next_cursor`, so it is not repeated. With a `cursor`, or with no impressions, the value is `null`.

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
  },
  "links": {
    "repo_url": "https://github.com/org/gittok",
    "panels": [ null, "https://github.com/org/gittok/blob/<sha>/src/x.py#L1-L5" ],
    "sources": [ { "label": "abc1234", "url": "https://github.com/org/gittok/commit/<sha>" } ]
  }
}
```

`links` is `null` when the repo has no GitHub URL (see `docs/formats.md`).

`resolved` holds text the server read from git. The client renders code only from `resolved`, never from model output. For `code_diff` depth panels, `resolved.depth[i]` is `{ "diff": "<unified diff>" }`. For `text` visuals, `resolved.visual` is `null` and the client uses `visual.title`, `visual.body`, `visual.bullets`.

## GET /api/cards/{id}

One `Card`, with a `replies` list (the reader's replies on that card). 404 for an unknown id. The card is served in any status, also one that is not in the feed yet.

## GET /api/repos

`{ "repos": [ { "name": "...", "ref": "HEAD", "head_sha": "... or null", "group": null } ] }`

One entry per configured repo. `head_sha` is the last analyzed commit, or `null` before the first analysis. An empty list means no repo is configured; the web app then shows how to add one in place of "You're all caught up".

## GET /api/repos/{name}

```json
{ "name": "storefront", "mascot": "otter or null", "mascot_image": "/assets/mascots/otter.png?v=<mtime> or null", "group": null,
  "stats": { "commits_365": 120, "authors_365": 4, "last_commit_ts": 1730000000,
             "top_files": [ { "path": "src/x.py", "commits": 41 } ], "top_dirs": [ { "path": "src", "commits": 90 } ] },
  "verdicts": [ { "dir": "src", "counts": { "<verdict>": 3 } } ],
  "cards": [Card, ...] }
```

`cards` holds the 20 newest `ready` cards of the repo. The numbers in `stats` are `null` (and the lists empty) before the first analysis or when the repo cannot be read. 404 for a repo that is not configured.

## GET /api/repos/{name}/map

```json
{ "name": "storefront",
  "dirs": [ { "dir": "src", "cards_seen": 3, "cards_available": 9, "quiz_right": 1, "quiz_wrong": 0, "novelty": 0.7, "verdicts": { "<verdict>": 2 } } ],
  "files": [ { "path": "src/x.py", "symbols_defined": 12, "symbols_seen": 4 } ] }
```

404 for a repo that is not configured.

## GET /api/personas/{handle}

`{ "handle", "name", "voice", "bio": "string or null", "posts": [Card, ...], "comments": [ { "card_id", "repo", "hook", "text" } ] }`. 404 for an unknown persona.

## GET /api/files/{repo}/{path}

`path` can hold slashes. Response: `{ "repo", "path", "history": { "commits": 41, "last_touched": "string or null", "authors": [ { "name", "commits" } ] } or null, "cards": [Card, ...], "followed": false }`. `cards` are the cards that cite the path. 404 for a repo that is not configured; a path that is not in the repo still returns 200.

## POST /api/follows

Body: `{ "repo": "storefront", "path": "src/billing", "on": true }`. `path` is 1 to 400 characters; `on` defaults to `true`. Response: `{ "followed": true }`. 404 for a repo that is not configured.

## POST /api/events

```json
{ "events": [ { "card_id": "c_...", "type": "impression", "ts": 1730000000000, "data": { "ms": 4200, "panel": 1 } } ] }
```

`type` is one of `impression`, `dwell`, `skip`, `scroll_back`, `depth_open`, `lightbox_open`, `like`, `save`, `explain_more`, `answer`, `source_tap`, `beats_done`, `replay`, `beat_tap`, `knew_it`, `teach_more`. `ts` is in milliseconds. `card_id` and `data` are optional. A batch holds at most 500 events, and each `data` is at most 4 KB as JSON.

Response: `{ "stored": 3 }`. An unknown type, or a batch over a limit, is rejected whole with 422. The server writes the reason to `<data_dir>/logs/rejected-events.log`.

A `save` event (`data: {"on": bool}`) also updates the `saved_cards` table in the same transaction. The newest event by `ts` wins. `GET /api/saved` reads that table, most recently saved first.

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

## GET /api/saved

`{ "cards": [Card, ...] }`, most recently saved first. Each card has a `replies` list.

## POST /api/replies

Body: `{ "card_id": "c_...", "comment_index": 0, "text": "Why floats?" }`. `comment_index` is the place of the comment in the card's `comments`. `text` is at most 280 characters and not empty.

Response: `{ "id": 4, "card_id": "c_...", "persona": "greybeard", "comment_index": 0, "text": "Why floats?", "created_at": "...", "answered_card_id": null }`. 404 for an unknown card. 400 for an empty or too long text, or a `comment_index` that is out of range.

## GET /api/stories

```json
{ "stories": [ { "repo": "storefront", "mascot": "otter or null", "mascot_image": "string or null", "seen": false,
    "digest": { "card_id": "c_...", "day": "2026-06-01", "hook": "...", "learn": "..." },
    "commits": [ { "sha": "<full sha>", "short": "abc1234", "ts": 1730000000, "author": "Ann", "subject": "Fix it",
                   "files": 2, "seen": false, "card_id": "c_... or null", "url": "string or null" } ] } ] }
```

`digest` is absent or `null` when the repo has no digest card. `url` is the GitHub commit URL, only when no card covers the commit.

## POST /api/stories/seen

Body: `{ "repo": "storefront", "shas": ["<7 to 40 hex characters>", ...] }`, at most 100 shas. Response: `{ "recorded": 2 }` (the number of shas that were new). 404 for a repo that is not configured. 422 for a bad sha.

## GET /api/notifications

Query parameter: `unread=1` returns only unread ones. Response:

```json
{ "notifications": [ { "id": 7, "kind": "low_runway", "text": "...", "card_id": "c_... or null",
                       "created_at": "...", "read": false, "repo": "string or null" } ],
  "unread": 3 }
```

Newest first. `unread` always counts every unread notification. `repo` is set only for `hot_file` notifications.

## POST /api/notifications/read

Body: `{ "ids": [7, 8] }` or `{ "all": true }`. Response: `{ "unread": 1 }`. A body with neither returns 400 `send ids or all`.

## GET /api/prefs

`{ "playback_speed": 1.0 }`. The speed of beat cards; the `set_playback_speed` MCP tool changes it.

## GET /api/avatars/{handle}

An image, not JSON: the persona's generated PNG when there is one, otherwise an SVG with initials. A leading `@` in the handle is ignored. Any handle gets an image; there is no 404. `Cache-Control: no-cache`.

## GET /assets/{folder}/{file}

A PNG from `<data_dir>/assets`. Two forms: `/assets/<card id>/<number>.png` (a card image; cached as immutable for a year) and `/assets/mascots/<name>.png` (cached for an hour). Any other name, or a missing file, returns 404 `unknown asset`. The URLs come from `resolved.visual.images` and `mascot_image`; clients do not build them.

## GET /pair?t=<token>

For a LAN device. With the right token, the server sets the `cs_lan` cookie (HttpOnly, SameSite=Lax, long expiry) and redirects to `/` with 303. A wrong token, or a server with no pairing token, returns 401 `bad pairing token`. The server prints the full URL at start-up (a line that begins with `pair:`).

## GET /healthz

`{ "ok": true }`. It follows the access rules like every other path.

## /mcp

The MCP server over streamable HTTP (stateless, JSON responses). Loopback peers only. Its tools are not part of this contract, except the ones described below.

## The web app

Every other `GET` path serves the built web app; an unknown path serves `index.html`. Files under `/_app/immutable/` are cached for a year, everything else is `no-cache`. A path that starts with `api/` and matches no route returns 404. When the web app is not built, `/` returns a short HTML page that says how to build it.

## MCP: feed_health and get_brief

`feed_health()` is a read-only MCP tool. `gittok health` prints the same JSON.

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

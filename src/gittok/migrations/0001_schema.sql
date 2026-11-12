-- The GitTok schema. Add a new numbered file for each later change.

CREATE TABLE repos (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  path TEXT NOT NULL,
  ref TEXT NOT NULL DEFAULT 'HEAD',
  mascot TEXT,
  last_analyzed_sha TEXT,
  last_analyzed_at TEXT
);

CREATE TABLE groups (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  standalone INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE repo_groups (
  repo_id INTEGER NOT NULL REFERENCES repos(id),
  group_id INTEGER NOT NULL REFERENCES groups(id),
  PRIMARY KEY (repo_id, group_id)
);

CREATE TABLE git_signals (
  id INTEGER PRIMARY KEY,
  repo_id INTEGER NOT NULL REFERENCES repos(id),
  head_sha TEXT NOT NULL,
  kind TEXT NOT NULL,
  payload TEXT NOT NULL,
  computed_at TEXT NOT NULL,
  duration_ms INTEGER,
  UNIQUE (repo_id, head_sha, kind)
);

CREATE TABLE runs (
  id TEXT PRIMARY KEY,
  repo_id INTEGER REFERENCES repos(id),
  backend TEXT NOT NULL DEFAULT 'mcp',
  status TEXT NOT NULL CHECK (status IN ('open', 'finished', 'expired', 'failed')),
  brief TEXT,
  requested INTEGER,
  accepted INTEGER NOT NULL DEFAULT 0,
  rejected INTEGER NOT NULL DEFAULT 0,
  submissions INTEGER NOT NULL DEFAULT 0,
  reject_reasons TEXT NOT NULL DEFAULT '[]',
  meta TEXT NOT NULL DEFAULT '{}',
  started_at TEXT NOT NULL,
  finished_at TEXT,
  duration_ms INTEGER
);

CREATE TABLE cards (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(id),
  repo_id INTEGER NOT NULL REFERENCES repos(id),
  story_type TEXT NOT NULL,
  format TEXT NOT NULL,
  persona TEXT NOT NULL,
  tone TEXT NOT NULL,
  spec TEXT NOT NULL,
  resolved TEXT,
  status TEXT NOT NULL DEFAULT 'ready',
  story_key TEXT NOT NULL,
  created_at TEXT NOT NULL
, lead_id INTEGER);

CREATE INDEX idx_cards_created_at ON cards(created_at);

CREATE INDEX idx_cards_repo_id ON cards(repo_id);

CREATE TABLE card_features (
  card_id TEXT NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
  feature TEXT NOT NULL,
  value TEXT NOT NULL,
  PRIMARY KEY (card_id, feature, value)
);

CREATE TABLE assets (
  id INTEGER PRIMARY KEY,
  card_id TEXT NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  path TEXT NOT NULL,
  meta TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE events (
  id INTEGER PRIMARY KEY,
  card_id TEXT,
  type TEXT NOT NULL,
  ts INTEGER NOT NULL,
  data TEXT NOT NULL DEFAULT '{}',
  received_at TEXT NOT NULL
);

CREATE INDEX idx_events_card_id ON events(card_id);

CREATE INDEX idx_events_ts ON events(ts);

CREATE TABLE rewards (
  id INTEGER PRIMARY KEY,
  card_id TEXT NOT NULL,
  impression_event_id INTEGER,
  reward REAL NOT NULL,
  computed_at TEXT NOT NULL
);

CREATE TABLE weights (
  feature TEXT NOT NULL,
  value TEXT NOT NULL,
  alpha REAL NOT NULL,
  beta REAL NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (feature, value)
);

CREATE TABLE rules (
  id INTEGER PRIMARY KEY,
  type TEXT NOT NULL CHECK (type IN ('boost', 'ban', 'focus', 'limit', 'prefer')),
  feature TEXT NOT NULL,
  value TEXT NOT NULL,
  factor REAL,
  slots INTEGER,
  max_share REAL,
  expires_at TEXT,
  created_by TEXT,
  reason TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE personas (
  handle TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  voice TEXT NOT NULL,
  avatar_path TEXT
);

CREATE TABLE mascots (
  name TEXT PRIMARY KEY,
  repo_id INTEGER REFERENCES repos(id),
  style TEXT,
  seed INTEGER
);

CREATE TABLE srs (
  card_id TEXT PRIMARY KEY,
  interval_days INTEGER NOT NULL,
  due_at TEXT NOT NULL,
  streak INTEGER NOT NULL DEFAULT 0,
  mastered INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE notifications (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,
  text TEXT NOT NULL,
  card_id TEXT,
  created_at TEXT NOT NULL,
  read_at TEXT
, dedup_key TEXT);

CREATE INDEX idx_events_type_ts ON events (type, ts);

CREATE UNIQUE INDEX idx_rewards_impression ON rewards (impression_event_id)
    WHERE impression_event_id IS NOT NULL;

CREATE TABLE story_views (
  repo TEXT NOT NULL,
  sha TEXT NOT NULL,
  seen_at TEXT NOT NULL,
  PRIMARY KEY (repo, sha)
);

CREATE UNIQUE INDEX idx_notifications_dedup ON notifications (dedup_key)
    WHERE dedup_key IS NOT NULL;

CREATE TABLE prefs (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE stories (
  story_key TEXT PRIMARY KEY,
  repo TEXT,
  story_type TEXT NOT NULL,
  sources TEXT NOT NULL DEFAULT '[]',
  first_card_at TEXT NOT NULL,
  last_card_at TEXT NOT NULL,
  cards_made INTEGER NOT NULL DEFAULT 1,
  best_reward REAL,
  liked INTEGER NOT NULL DEFAULT 0
, formats TEXT NOT NULL DEFAULT '[]');

CREATE UNIQUE INDEX idx_cards_story_key_format_unique ON cards(story_key, format);

CREATE TABLE saved_cards (
    card_id  TEXT PRIMARY KEY,
    saved_at TEXT NOT NULL,
    saved_ts INTEGER NOT NULL  -- ts (ms) of the save event that put it here
);

CREATE TABLE candidates (
  id INTEGER PRIMARY KEY,
  repo TEXT NOT NULL,
  path TEXT NOT NULL,
  line_start INTEGER NOT NULL,
  line_end INTEGER NOT NULL,
  tag TEXT NOT NULL,
  why TEXT NOT NULL,
  score REAL NOT NULL DEFAULT 0,
  head_sha TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL, window_hash TEXT, rule_id TEXT, fact_ids TEXT,
  UNIQUE(repo, path, line_start, tag)
);

CREATE INDEX candidates_repo_tag ON candidates(repo, tag, score DESC);

CREATE TABLE knowledge (
    repo            TEXT NOT NULL,
    dir             TEXT NOT NULL,
    cards_seen      INTEGER NOT NULL DEFAULT 0,
    explains_opened INTEGER NOT NULL DEFAULT 0,
    quiz_right      INTEGER NOT NULL DEFAULT 0,
    quiz_wrong      INTEGER NOT NULL DEFAULT 0,
    knew_it         INTEGER NOT NULL DEFAULT 0,
    teach_more      INTEGER NOT NULL DEFAULT 0,
    last_seen_ts    INTEGER,
    PRIMARY KEY (repo, dir)
);

CREATE TABLE knowledge_events (
    event_id INTEGER NOT NULL,
    ts       INTEGER NOT NULL,
    card_id  TEXT NOT NULL,
    kind     TEXT NOT NULL,
    PRIMARY KEY (event_id, ts)
);

CREATE INDEX idx_knowledge_events_card ON knowledge_events(card_id, kind);

CREATE TABLE "leads" (
  id INTEGER PRIMARY KEY,
  repo TEXT NOT NULL,
  story_type TEXT NOT NULL,
  kind TEXT NOT NULL,
  path TEXT NOT NULL DEFAULT '',
  commit_sha TEXT NOT NULL DEFAULT '',
  blob_sha TEXT NOT NULL DEFAULT '',
  lead_key TEXT NOT NULL,
  lines TEXT,
  text TEXT NOT NULL,
  strength REAL NOT NULL,
  head_sha TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  times_covered INTEGER NOT NULL DEFAULT 0,
  last_covered_at TEXT,
  mean_reward REAL,
  rewards_n INTEGER NOT NULL DEFAULT 0, times_rejected INTEGER NOT NULL DEFAULT 0, last_rejected_at TEXT,
  UNIQUE(repo, story_type, lead_key)
);

CREATE INDEX leads_repo_type ON leads(repo, story_type);

CREATE TABLE candidate_ratings (
  repo TEXT NOT NULL,
  path TEXT NOT NULL,
  line_start INTEGER NOT NULL,
  tag TEXT NOT NULL,
  window_hash TEXT NOT NULL,
  teachable INTEGER NOT NULL CHECK (teachable BETWEEN 1 AND 5),
  verdict TEXT NOT NULL CHECK (verdict IN ('good', 'bad', 'clever', 'cursed', 'core')),
  concept TEXT NOT NULL,
  why TEXT NOT NULL,
  rated_at TEXT NOT NULL,
  batch_id TEXT,
  PRIMARY KEY (repo, path, line_start, tag, window_hash)
);

CREATE TABLE scout_batches (
  id TEXT PRIMARY KEY,
  repo TEXT NOT NULL,
  head_sha TEXT NOT NULL,
  items TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE requests (
    id          INTEGER PRIMARY KEY,
    card_id     TEXT NOT NULL UNIQUE,
    repo        TEXT NOT NULL,
    story_type  TEXT NOT NULL,
    path        TEXT NOT NULL DEFAULT '',
    commit_sha  TEXT NOT NULL DEFAULT '',
    dirs        TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL,
    served_at   TEXT
);

CREATE TABLE digests (
    repo        TEXT NOT NULL,
    day         TEXT NOT NULL,
    card_id     TEXT,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (repo, day)
);

CREATE TABLE replies (
    id                INTEGER PRIMARY KEY,
    card_id           TEXT NOT NULL,
    persona           TEXT NOT NULL,
    comment_index     INTEGER NOT NULL,
    text              TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    answered_card_id  TEXT
);

CREATE INDEX replies_card ON replies(card_id);

CREATE TABLE fact_builds (
  repo_id INTEGER PRIMARY KEY REFERENCES repos(id),
  head_sha TEXT NOT NULL,
  built_at TEXT NOT NULL,
  duration_ms INTEGER NOT NULL,
  counts TEXT NOT NULL,          -- JSON: rows per table and which caps cut
  query_key TEXT NOT NULL        -- hash of the profile queries used
);

CREATE TABLE fact_defines (
  fact_id TEXT PRIMARY KEY,
  repo_id INTEGER NOT NULL REFERENCES repos(id),
  path TEXT NOT NULL,
  symbol TEXT NOT NULL,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  start INTEGER NOT NULL,
  "end" INTEGER NOT NULL,
  size INTEGER NOT NULL,
  params INTEGER NOT NULL,
  depth INTEGER NOT NULL,
  branches INTEGER NOT NULL,
  public INTEGER NOT NULL,
  source TEXT NOT NULL DEFAULT 'syntax'
);

CREATE INDEX fact_defines_name ON fact_defines(repo_id, name);

CREATE INDEX fact_defines_symbol ON fact_defines(repo_id, symbol);

CREATE INDEX fact_defines_path ON fact_defines(repo_id, path, start);

CREATE TABLE fact_calls (
  fact_id TEXT PRIMARY KEY,
  repo_id INTEGER NOT NULL REFERENCES repos(id),
  caller_symbol TEXT NOT NULL,
  callee_name TEXT NOT NULL,
  path TEXT NOT NULL,
  line INTEGER NOT NULL,
  resolved INTEGER NOT NULL,
  callee_symbol TEXT,
  source TEXT NOT NULL DEFAULT 'syntax'
);

CREATE INDEX fact_calls_caller ON fact_calls(repo_id, caller_symbol);

CREATE INDEX fact_calls_callee ON fact_calls(repo_id, callee_symbol);

CREATE INDEX fact_calls_path ON fact_calls(repo_id, path, line);

CREATE TABLE fact_imports (
  fact_id TEXT PRIMARY KEY,
  repo_id INTEGER NOT NULL REFERENCES repos(id),
  path TEXT NOT NULL,
  line INTEGER NOT NULL,
  module_text TEXT NOT NULL,
  resolved_path TEXT,
  source TEXT NOT NULL DEFAULT 'syntax'
);

CREATE INDEX fact_imports_path ON fact_imports(repo_id, path);

CREATE TABLE fact_touched (
  fact_id TEXT PRIMARY KEY,
  repo_id INTEGER NOT NULL REFERENCES repos(id),
  commit_sha TEXT NOT NULL,
  ts INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  path TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'syntax'
);

CREATE INDEX fact_touched_symbol ON fact_touched(repo_id, symbol, ts);

CREATE TABLE fact_analyzers (
  repo_id INTEGER NOT NULL REFERENCES repos(id),
  tool TEXT NOT NULL,
  head_sha TEXT NOT NULL,
  submitted_at TEXT NOT NULL,
  counts TEXT NOT NULL,          -- JSON: accepted facts per kind
  PRIMARY KEY (repo_id, tool)
);

CREATE TABLE fact_schema (
  fact_id TEXT PRIMARY KEY,
  repo_id INTEGER NOT NULL REFERENCES repos(id),
  kind TEXT NOT NULL,            -- 'returns' or 'accepts'
  path TEXT NOT NULL,
  line INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  type TEXT,                     -- returns: the type text
  params TEXT,                   -- accepts: JSON list
  source TEXT NOT NULL
);

CREATE INDEX fact_schema_symbol ON fact_schema(repo_id, symbol);

CREATE INDEX fact_schema_path ON fact_schema(repo_id, path, line);

CREATE TABLE knowledge_symbols (
    repo            TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    seen            INTEGER NOT NULL DEFAULT 0,
    explains_opened INTEGER NOT NULL DEFAULT 0,
    quiz_right      INTEGER NOT NULL DEFAULT 0,
    quiz_wrong      INTEGER NOT NULL DEFAULT 0,
    knew_it         INTEGER NOT NULL DEFAULT 0,
    teach_more      INTEGER NOT NULL DEFAULT 0,
    last_seen       INTEGER,
    PRIMARY KEY (repo, symbol)
);

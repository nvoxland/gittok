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
);
CREATE INDEX idx_cards_created_at ON cards(created_at);
CREATE INDEX idx_cards_story_key ON cards(story_key);
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

-- card_id is intentionally not a foreign key: events for deleted cards survive.
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
);

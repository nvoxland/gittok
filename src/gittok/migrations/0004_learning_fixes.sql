-- Learning fixes (docs/learning.md).
-- events: AUTOINCREMENT, so an id that gc deleted is never used again. A reward names its
--   impression by id, and a reused id would hide a new impression from the learner.
-- rewards: card_id may be NULL. Removing a repo keeps the rewards of its cards (with their
--   feature snapshot) but drops the link, so `gittok relearn` keeps what they taught.
-- model_resets: each reset of the learned weights, so `gittok relearn` does not bring back
--   what the user reset.

CREATE TABLE events_new (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  card_id TEXT,
  type TEXT NOT NULL,
  ts INTEGER NOT NULL,
  data TEXT NOT NULL DEFAULT '{}',
  received_at TEXT NOT NULL
);
INSERT INTO events_new(id, card_id, type, ts, data, received_at)
  SELECT id, card_id, type, ts, data, received_at FROM events;
DROP TABLE events;
ALTER TABLE events_new RENAME TO events;
CREATE INDEX idx_events_card_id ON events(card_id);
CREATE INDEX idx_events_ts ON events(ts);
CREATE INDEX idx_events_type_ts ON events (type, ts);
DELETE FROM sqlite_sequence WHERE name = 'events';
INSERT INTO sqlite_sequence(name, seq) SELECT 'events', MAX(
  COALESCE((SELECT MAX(id) FROM events), 0),
  COALESCE((SELECT MAX(impression_event_id) FROM rewards), 0),
  COALESCE((SELECT MAX(event_id) FROM knowledge_events), 0));

CREATE TABLE rewards_new (
  id INTEGER PRIMARY KEY,
  card_id TEXT,
  impression_event_id INTEGER,
  reward REAL NOT NULL,
  computed_at TEXT NOT NULL,
  weight REAL NOT NULL DEFAULT 1,
  signal TEXT,
  features TEXT
);
INSERT INTO rewards_new(id, card_id, impression_event_id, reward, computed_at, weight, signal,
  features)
  SELECT id, card_id, impression_event_id, reward, computed_at, weight, signal, features
  FROM rewards;
DROP TABLE rewards;
ALTER TABLE rewards_new RENAME TO rewards;
CREATE UNIQUE INDEX idx_rewards_impression ON rewards (impression_event_id)
    WHERE impression_event_id IS NOT NULL;
CREATE INDEX idx_rewards_card_id ON rewards (card_id);

CREATE TABLE model_resets (
  id INTEGER PRIMARY KEY,
  feature TEXT,              -- NULL: every weight was reset
  at TEXT NOT NULL
);

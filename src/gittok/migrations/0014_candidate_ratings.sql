-- Scout stage (SPEC 10.4): a cheap agent rates candidate windows before writers run.
-- A rating is keyed by the window's text hash, so it survives a new head while the code is
-- unchanged and is redone when the code changes.
ALTER TABLE candidates ADD COLUMN window_hash TEXT;

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

-- Server-side batch assignment, so the ids a scout gets stay stable. items is JSON.
CREATE TABLE scout_batches (
  id TEXT PRIMARY KEY,
  repo TEXT NOT NULL,
  head_sha TEXT NOT NULL,
  items TEXT NOT NULL,
  created_at TEXT NOT NULL
);

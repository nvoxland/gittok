-- Places in the code the miners (candidates.py) found worth a card. No LLM involved.
-- One row per repo, path, start line and tag; a new head keeps first_seen_at and drops
-- rows the miners no longer find.
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
  last_seen_at TEXT NOT NULL,
  UNIQUE(repo, path, line_start, tag)
);
CREATE INDEX candidates_repo_tag ON candidates(repo, tag, score DESC);

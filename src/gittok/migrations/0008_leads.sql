-- One row per lead (a commit or a file at a given blob) the analysis ever offered.
-- A changed file is a new row, so "covered before, changed since" stays visible.
CREATE TABLE leads (
  id INTEGER PRIMARY KEY,
  repo TEXT NOT NULL,
  story_type TEXT NOT NULL,
  kind TEXT NOT NULL,
  path TEXT NOT NULL DEFAULT '',
  commit_sha TEXT NOT NULL DEFAULT '',
  blob_sha TEXT NOT NULL DEFAULT '',
  lines TEXT,
  text TEXT NOT NULL,
  strength REAL NOT NULL,
  head_sha TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  times_covered INTEGER NOT NULL DEFAULT 0,
  last_covered_at TEXT,
  mean_reward REAL,
  rewards_n INTEGER NOT NULL DEFAULT 0,
  UNIQUE(repo, story_type, kind, path, commit_sha, blob_sha)
);
CREATE INDEX leads_repo_type ON leads(repo, story_type);

-- No foreign key: cards may outlive or predate their lead.
ALTER TABLE cards ADD COLUMN lead_id INTEGER;

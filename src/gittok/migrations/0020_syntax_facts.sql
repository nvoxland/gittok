-- Syntax facts per repo head (src/gittok/facts.py). Every row has source = 'syntax' and a
-- stable fact_id that cards can cite. A refresh replaces all rows of one repo.
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

-- One row per (commit, symbol) whose lines the commit changed. introduced = oldest row,
-- last_changed = newest row, per symbol (only commits inside the bounded window are seen).
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

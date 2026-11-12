-- Facts an agent submitted from an analyzer it ran itself (src/blamescroll/facts.py,
-- submit_analyzer). Rows in the fact_* tables with source 'analyzer:<tool>' or 'schema:<tool>'.
-- fact_analyzers records, per repo and tool label, the head the facts were checked against.
-- A syntax refresh at a new head drops the facts; this row stays, so the head no longer matches
-- and the SessionStart hint can say the analyzer facts are stale.
CREATE TABLE fact_analyzers (
  repo_id INTEGER NOT NULL REFERENCES repos(id),
  tool TEXT NOT NULL,
  head_sha TEXT NOT NULL,
  submitted_at TEXT NOT NULL,
  counts TEXT NOT NULL,          -- JSON: accepted facts per kind
  PRIMARY KEY (repo_id, tool)
);

-- returns / accepts facts: the type a symbol returns, or the parameters it accepts.
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

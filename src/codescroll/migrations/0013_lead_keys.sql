-- A lead is keyed by what it points at, not by file content: a path lead by its path (an edit
-- keeps its cooldown), a commit lead by sha and path, a lead with no git identity (a dir or a
-- file pair) by a synthetic key such as "dir:src". Rows that differ only by blob are merged:
-- the newest row is kept, with the summed coverage and reward counts.
CREATE TEMP TABLE lead_map AS
SELECT id, repo, story_type, last_seen_at,
  CASE kind WHEN 'commit' THEN 'c:' || commit_sha || ':' || path
            WHEN 'path' THEN 'p:' || path
            ELSE 'n:' || id END AS lead_key
FROM leads;

CREATE TEMP TABLE lead_keep AS
SELECT m.id AS old_id, (
  SELECT m2.id FROM lead_map m2
  WHERE m2.lead_key = m.lead_key AND m2.repo = m.repo AND m2.story_type = m.story_type
  ORDER BY m2.last_seen_at DESC, m2.id DESC LIMIT 1) AS keep_id
FROM lead_map m;

CREATE TABLE leads_new (
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
  rewards_n INTEGER NOT NULL DEFAULT 0,
  UNIQUE(repo, story_type, lead_key)
);

INSERT INTO leads_new(id, repo, story_type, kind, path, commit_sha, blob_sha, lead_key, lines,
  text, strength, head_sha, first_seen_at, last_seen_at, times_covered, last_covered_at,
  mean_reward, rewards_n)
SELECT l.id, l.repo, l.story_type, l.kind, l.path, l.commit_sha, l.blob_sha, m.lead_key, l.lines,
  l.text, l.strength, l.head_sha,
  (SELECT MIN(a.first_seen_at) FROM leads a JOIN lead_keep k ON k.old_id = a.id
    WHERE k.keep_id = l.id),
  l.last_seen_at,
  (SELECT SUM(a.times_covered) FROM leads a JOIN lead_keep k ON k.old_id = a.id
    WHERE k.keep_id = l.id),
  (SELECT MAX(a.last_covered_at) FROM leads a JOIN lead_keep k ON k.old_id = a.id
    WHERE k.keep_id = l.id),
  (SELECT SUM(a.mean_reward * a.rewards_n) / SUM(a.rewards_n) FROM leads a
    JOIN lead_keep k ON k.old_id = a.id WHERE k.keep_id = l.id AND a.rewards_n > 0),
  (SELECT SUM(a.rewards_n) FROM leads a JOIN lead_keep k ON k.old_id = a.id
    WHERE k.keep_id = l.id)
FROM leads l JOIN lead_map m ON m.id = l.id
WHERE l.id IN (SELECT keep_id FROM lead_keep);

UPDATE cards SET lead_id = (SELECT keep_id FROM lead_keep WHERE old_id = cards.lead_id)
WHERE lead_id IN (SELECT old_id FROM lead_keep);

DROP INDEX IF EXISTS leads_repo_type;
DROP TABLE leads;
ALTER TABLE leads_new RENAME TO leads;
CREATE INDEX leads_repo_type ON leads(repo, story_type);
DROP TABLE lead_map;
DROP TABLE lead_keep;

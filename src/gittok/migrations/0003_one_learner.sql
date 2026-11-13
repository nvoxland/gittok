-- One learner (docs/learning.md): a thumbs-down replaces "Knew it" and "More", the follow-up
-- requests behind "More" are gone, and an additive model (model_weights) replaces the Beta
-- weights. Each reward keeps its update weight, its explicit signal and the features of the
-- impression, so `gittok relearn` can rebuild the model from the rewards.

DROP TABLE requests;
DELETE FROM leads WHERE lead_key LIKE 'req:%';

ALTER TABLE knowledge DROP COLUMN knew_it;
ALTER TABLE knowledge DROP COLUMN teach_more;
ALTER TABLE knowledge_symbols DROP COLUMN knew_it;
ALTER TABLE knowledge_symbols DROP COLUMN teach_more;
DELETE FROM knowledge_events WHERE kind IN ('knew_it', 'teach_more');

ALTER TABLE stories ADD COLUMN disliked INTEGER NOT NULL DEFAULT 0;

ALTER TABLE rewards ADD COLUMN weight REAL NOT NULL DEFAULT 1;
ALTER TABLE rewards ADD COLUMN signal TEXT;    -- 'like', 'dislike' or NULL
ALTER TABLE rewards ADD COLUMN features TEXT;  -- JSON [[feature, value], ...] at impression time

DROP TABLE weights;
CREATE TABLE model_weights (
  feature    TEXT NOT NULL,
  value      TEXT NOT NULL,
  mean       REAL NOT NULL,   -- posterior mean of the weight (log-odds)
  precision  REAL NOT NULL,   -- 1 / posterior variance
  n          REAL NOT NULL DEFAULT 0,  -- decayed evidence (sum of update weights)
  updated_at TEXT NOT NULL,
  PRIMARY KEY (feature, value)
);

-- One row per story ever made. Survives card deletion (gc), so duplicate checks keep working.
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
);

INSERT INTO stories(story_key, repo, story_type, sources, first_card_at, last_card_at,
                    cards_made, best_reward, liked)
SELECT c.story_key,
       (SELECT r.name FROM repos r WHERE r.id = c.repo_id),
       c.story_type,
       COALESCE(json_extract(c.spec, '$.sources'), '[]'),
       MIN(c.created_at),
       MAX(c.created_at),
       COUNT(*),
       (SELECT MAX(w.reward) FROM rewards w WHERE w.card_id = c.id),
       COALESCE(
         (SELECT COALESCE(json_extract(e.data, '$.on'), 1) FROM events e
          WHERE e.card_id = c.id AND e.type = 'like' ORDER BY e.ts DESC, e.id DESC LIMIT 1),
         0)
FROM cards c
GROUP BY c.story_key;

-- A story may be told again in another format: uniqueness is per (story_key, format).
-- stories.formats lists the formats already used, so the check survives card deletion (gc).
DROP INDEX IF EXISTS idx_cards_story_key_unique;
CREATE UNIQUE INDEX idx_cards_story_key_format_unique ON cards(story_key, format);

ALTER TABLE stories ADD COLUMN formats TEXT NOT NULL DEFAULT '[]';

UPDATE stories SET formats = COALESCE(
  (SELECT json_group_array(format) FROM
     (SELECT DISTINCT c.format AS format FROM cards c
      WHERE c.story_key = stories.story_key ORDER BY c.format)),
  '[]');

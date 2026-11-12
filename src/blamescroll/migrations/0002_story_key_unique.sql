DROP INDEX IF EXISTS idx_cards_story_key;
CREATE UNIQUE INDEX idx_cards_story_key_unique ON cards(story_key);

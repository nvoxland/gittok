CREATE TABLE story_views (
  repo TEXT NOT NULL,
  sha TEXT NOT NULL,
  seen_at TEXT NOT NULL,
  PRIMARY KEY (repo, sha)
);

ALTER TABLE notifications ADD COLUMN dedup_key TEXT;
CREATE UNIQUE INDEX idx_notifications_dedup ON notifications (dedup_key)
    WHERE dedup_key IS NOT NULL;

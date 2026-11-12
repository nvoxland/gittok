-- learning.process_events scans impressions by type and time, and must never write two
-- rewards for one impression (idempotency also holds without this, but the index guards races).
CREATE INDEX IF NOT EXISTS idx_events_type_ts ON events (type, ts);
CREATE UNIQUE INDEX IF NOT EXISTS idx_rewards_impression ON rewards (impression_event_id)
    WHERE impression_event_id IS NOT NULL;

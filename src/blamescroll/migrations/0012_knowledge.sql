-- What the reader already knows, per repo and dir prefix (docs/learning.md section 14).
CREATE TABLE knowledge (
    repo            TEXT NOT NULL,
    dir             TEXT NOT NULL,
    cards_seen      INTEGER NOT NULL DEFAULT 0,
    explains_opened INTEGER NOT NULL DEFAULT 0,
    quiz_right      INTEGER NOT NULL DEFAULT 0,
    quiz_wrong      INTEGER NOT NULL DEFAULT 0,
    knew_it         INTEGER NOT NULL DEFAULT 0,
    teach_more      INTEGER NOT NULL DEFAULT 0,
    last_seen_ts    INTEGER,
    PRIMARY KEY (repo, dir)
);

-- Events already counted, so a second pass over the same events changes nothing.
-- (event_id, ts) because gc may delete old events and SQLite can reuse the top ids.
CREATE TABLE knowledge_events (
    event_id INTEGER NOT NULL,
    ts       INTEGER NOT NULL,
    card_id  TEXT NOT NULL,
    kind     TEXT NOT NULL,
    PRIMARY KEY (event_id, ts)
);
CREATE INDEX idx_knowledge_events_card ON knowledge_events(card_id, kind);

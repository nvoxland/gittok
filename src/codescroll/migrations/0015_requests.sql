-- "Teach me more" requests: one per card. Each becomes a high-priority ledger lead
-- (lead_key "req:<id>") until a card covers it (served_at).
CREATE TABLE requests (
    id          INTEGER PRIMARY KEY,
    card_id     TEXT NOT NULL UNIQUE,
    repo        TEXT NOT NULL,
    story_type  TEXT NOT NULL,
    path        TEXT NOT NULL DEFAULT '',
    commit_sha  TEXT NOT NULL DEFAULT '',
    dirs        TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL,
    served_at   TEXT
);

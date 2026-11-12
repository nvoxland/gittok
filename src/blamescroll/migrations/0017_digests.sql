-- Daily digest per repo: one ledger lead (lead_key "digest:<repo>:<day>") until a card covers it.
CREATE TABLE digests (
    repo        TEXT NOT NULL,
    day         TEXT NOT NULL,
    card_id     TEXT,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (repo, day)
);

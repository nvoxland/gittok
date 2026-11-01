-- Reader replies to a persona's comment. Each open reply is a pinned ledger lead
-- (lead_key "reply:<id>") until a card by that persona answers it (answered_card_id).
CREATE TABLE replies (
    id                INTEGER PRIMARY KEY,
    card_id           TEXT NOT NULL,
    persona           TEXT NOT NULL,
    comment_index     INTEGER NOT NULL,
    text              TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    answered_card_id  TEXT
);
CREATE INDEX replies_card ON replies(card_id);

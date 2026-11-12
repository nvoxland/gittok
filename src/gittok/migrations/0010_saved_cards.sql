-- Saved cards live in their own table: gc prunes old events, and a saved card is never collected.
CREATE TABLE saved_cards (
    card_id  TEXT PRIMARY KEY,
    saved_at TEXT NOT NULL,
    saved_ts INTEGER NOT NULL  -- ts (ms) of the save event that put it here
);

INSERT INTO saved_cards(card_id, saved_at, saved_ts)
SELECT e.card_id, strftime('%Y-%m-%dT%H:%M:%SZ', e.ts / 1000, 'unixepoch'), e.ts
FROM events e
WHERE e.type = 'save'
  AND e.id = (SELECT e2.id FROM events e2 WHERE e2.card_id = e.card_id AND e2.type = 'save'
              ORDER BY e2.ts DESC, e2.id DESC LIMIT 1)
  AND COALESCE(json_extract(e.data, '$.on'), 1) != 0
  AND e.card_id IN (SELECT id FROM cards);

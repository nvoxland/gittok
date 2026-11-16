-- pair_requests.peer: the address that asked, so one device cannot take every slot.
-- events: an index on the client's `event_id` (in `data`), so a retried batch is found fast
--   and its events are stored once. Not unique: older rows may repeat an id.
ALTER TABLE pair_requests ADD COLUMN peer TEXT;
CREATE INDEX idx_events_event_id ON events(json_extract(data, '$.event_id'))
  WHERE json_extract(data, '$.event_id') IS NOT NULL;

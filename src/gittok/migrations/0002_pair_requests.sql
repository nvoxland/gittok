-- Pairing by code: a device that is not paired asks for a code (`pair_codes.request`), the
-- user tells Claude the code, and Claude approves it (`pair_codes.approve`). The device
-- polls with its secret id and gets the pairing cookie once (`pair_codes.status`).

CREATE TABLE pair_requests (
  id TEXT PRIMARY KEY,
  code TEXT UNIQUE NOT NULL,
  created_at TEXT NOT NULL,
  approved_at TEXT
);

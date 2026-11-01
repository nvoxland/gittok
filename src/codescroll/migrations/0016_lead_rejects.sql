-- A card that was rejected and cited a lead lowers that lead's rank in later briefs.
ALTER TABLE leads ADD COLUMN times_rejected INTEGER NOT NULL DEFAULT 0;
ALTER TABLE leads ADD COLUMN last_rejected_at TEXT;

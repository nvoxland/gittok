-- Which profile detector (config/profiles/<repo>.yaml) found a candidate. NULL for the built-in miners.
ALTER TABLE candidates ADD COLUMN rule_id TEXT;

-- The fact path of a candidate from conventions.py: a JSON list of fact ids (definition, call,
-- ..., schema) that show why the miner flagged it. NULL for the other miners.
ALTER TABLE candidates ADD COLUMN fact_ids TEXT;

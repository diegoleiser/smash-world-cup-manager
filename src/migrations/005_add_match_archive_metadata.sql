PRAGMA foreign_keys = ON;

-- Tournament Manager archives use these nullable metadata fields.
-- Existing Challonge matches remain valid without backfilled values.
ALTER TABLE matches ADD COLUMN stage TEXT;
ALTER TABLE matches ADD COLUMN suggested_play_order INTEGER;
ALTER TABLE matches ADD COLUMN completed_at TEXT;

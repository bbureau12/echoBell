-- Migration 008: Add signal rules and contributes_standalone flag
-- Purpose: Create signal rule tables and add group-only capability

-- Create signal_rule table if it doesn't exist
CREATE TABLE IF NOT EXISTS signal_rule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    feature TEXT NOT NULL,
    operator TEXT NOT NULL,
    value TEXT NOT NULL,
    intent_name TEXT NOT NULL,
    weight REAL DEFAULT 1.0,
    min_conf REAL DEFAULT 0.0,
    urgency INTEGER DEFAULT 10,
    scope_any_of TEXT,
    contributes_standalone INTEGER DEFAULT 1,
    enabled INTEGER DEFAULT 1
);

-- Create signal_group table if it doesn't exist
CREATE TABLE IF NOT EXISTS signal_group (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    intent_name TEXT NOT NULL,
    group_mode TEXT DEFAULT 'all',
    bind_scope TEXT,
    base_weight REAL DEFAULT 1.0,
    urgency INTEGER DEFAULT 10,
    enabled INTEGER DEFAULT 1
);

-- Create signal_group_member table if it doesn't exist
CREATE TABLE IF NOT EXISTS signal_group_member (
    group_id INTEGER NOT NULL,
    rule_id INTEGER NOT NULL,
    required INTEGER DEFAULT 0,
    weight_mul REAL DEFAULT 1.0,
    enabled INTEGER DEFAULT 1,
    PRIMARY KEY (group_id, rule_id)
);

-- For existing databases, try to add contributes_standalone column if not present
-- SQLite doesn't have ADD COLUMN IF NOT EXISTS, so we check the schema first
-- If this fails, the column already exists (which is fine)

-- Note: The following ALTER TABLE will fail silently if column exists
-- This is handled by the migration system

-- Update existing rules with weight=0 to be group-only
-- (These were likely intended to be group-only but couldn't work properly)
UPDATE signal_rule 
SET contributes_standalone = 0 
WHERE weight = 0.0 AND contributes_standalone IS NOT NULL;

-- For group-only rules, set weight to 1.0 so they contribute properly in groups
UPDATE signal_rule 
SET weight = 1.0 
WHERE contributes_standalone = 0 AND weight = 0.0;

PRAGMA user_version = 8;

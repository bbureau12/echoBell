-- Migration 008: Add contributes_standalone flag to signal_rule
-- Purpose: Allow rules to be group-only (don't score standalone, only via signal groups)

-- Add contributes_standalone column (default=1 for backward compatibility)
ALTER TABLE signal_rule 
ADD COLUMN contributes_standalone INTEGER DEFAULT 1 NOT NULL;

-- Update existing rules with weight=0 to be group-only
-- (These were likely intended to be group-only but couldn't work properly)
UPDATE signal_rule 
SET contributes_standalone = 0 
WHERE weight = 0.0;

-- For group-only rules, set weight to 1.0 so they contribute properly in groups
UPDATE signal_rule 
SET weight = 1.0 
WHERE contributes_standalone = 0 AND weight = 0.0;

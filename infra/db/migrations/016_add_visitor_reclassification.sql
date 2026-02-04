-- Migration 016: Add visitor event reclassification tracking
-- Purpose: Track LLM-driven intent reclassifications with full audit trail

-- Add reclassification tracking columns to visitor_events
ALTER TABLE visitor_events ADD COLUMN reclassification_count INTEGER DEFAULT 0;
ALTER TABLE visitor_events ADD COLUMN reclassified_by TEXT;
ALTER TABLE visitor_events ADD COLUMN reclassification_reason TEXT;
ALTER TABLE visitor_events ADD COLUMN reclassified_ts INTEGER;

-- Create index for finding reclassified events
CREATE INDEX IF NOT EXISTS idx_visitor_events_reclassified 
    ON visitor_events(reclassification_count, reclassified_ts DESC)
    WHERE reclassification_count > 0;

-- Create index for reclassification source analysis
CREATE INDEX IF NOT EXISTS idx_visitor_events_reclassified_by 
    ON visitor_events(reclassified_by, reclassified_ts DESC)
    WHERE reclassified_by IS NOT NULL;

-- Add MCP tool permissions for reclassification tools
INSERT OR IGNORE INTO mcp_tool_permissions (tool_name, voice_enabled, requires_confidence, security_level, created_ts, updated_ts, notes)
VALUES 
    ('reclassify_visitor_intent', 1, 0.80, 'normal', strftime('%s', 'now'), strftime('%s', 'now'), 
     'Allow LLM to reclassify visitor intent with evidence injection or override'),
    ('get_visitor_event', 1, 0.75, 'low', strftime('%s', 'now'), strftime('%s', 'now'), 
     'Query visitor event details for reclassification decisions');

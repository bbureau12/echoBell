-- Migration 019: Add Presence Tracking System
-- 
-- This migration implements a dual-table presence tracking system for monitoring
-- who is currently home based on multiple evidence sources (phones, vehicles, faces).
--
-- Architecture:
-- 1. presence_events: Immutable evidence log (phone heartbeats, vehicle detections, etc.)
-- 2. presence_state: Current aggregated state per person (home/away with confidence)
--
-- Use Cases:
-- - Policy conditions: "Don't notify if owner is home"
-- - LLM queries: "Is Beau home?"
-- - Automation: "Turn on lights when first person arrives"

-- ============================================================================
-- Table 1: presence_events (Evidence Log)
-- ============================================================================
-- Stores all presence evidence from various sources.
-- This is append-only for audit trail purposes.

CREATE TABLE IF NOT EXISTS presence_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp INTEGER NOT NULL,
    
    -- Source classification
    source TEXT NOT NULL,           -- "phone", "plate", "face", "manual", "bluetooth"
    signal TEXT NOT NULL,            -- "heartbeat", "vehicle_present", "vehicle_left", 
                                     -- "face_seen", "override_home", "override_away"
    
    -- Subject identification
    subject_id TEXT NOT NULL,        -- Specific entity: "beau_phone", "beau_tesla", "beau_face"
    person_id TEXT,                  -- Person this evidence belongs to: "beau"
    
    -- Confidence and metadata
    confidence REAL,                 -- 0.0-1.0, NULL for definitive signals (manual overrides)
    metadata_json TEXT,              -- Source-specific data: {"ip": "...", "rssi": -45, "camera_id": 1}
    
    -- Constraints
    CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)),
    CHECK (source IN ('phone', 'plate', 'face', 'manual', 'bluetooth', 'other')),
    CHECK (length(signal) > 0)
);

-- Index for time-based queries (recent evidence)
CREATE INDEX IF NOT EXISTS idx_presence_events_timestamp 
ON presence_events(timestamp);

-- Index for person-based lookups (all evidence for one person)
CREATE INDEX IF NOT EXISTS idx_presence_events_person_time 
ON presence_events(person_id, timestamp DESC);

-- Index for subject tracking (specific device history)
CREATE INDEX IF NOT EXISTS idx_presence_events_subject 
ON presence_events(subject_id, timestamp DESC);

-- Index for signal type queries
CREATE INDEX IF NOT EXISTS idx_presence_events_signal 
ON presence_events(signal, timestamp DESC);

-- ============================================================================
-- Table 2: presence_state (Current Aggregated State)
-- ============================================================================
-- Stores the current presence status for each person.
-- Updated by background aggregation service every 60 seconds.

CREATE TABLE IF NOT EXISTS presence_state (
    person_id TEXT PRIMARY KEY,
    
    -- Current state
    status TEXT NOT NULL,            -- "home", "away", "uncertain"
    confidence REAL NOT NULL,        -- 0.0-1.0 (how confident we are in this status)
    last_updated INTEGER NOT NULL,   -- When this state was last computed
    
    -- Detailed state (JSON)
    state_json TEXT,                 -- Full state with reasons and evidence details
                                     -- Example:
                                     -- {
                                     --   "reasons": ["phone_seen_2m_ago", "car_present"],
                                     --   "evidence": {
                                     --     "phone_last_seen": 1738890880,
                                     --     "vehicles_present": ["tesla", "truck"],
                                     --     "face_last_seen": null
                                     --   },
                                     --   "raw_signals": [
                                     --     {"source": "phone", "confidence": 0.95, "age_seconds": 120},
                                     --     {"source": "plate", "confidence": 0.90, "age_seconds": 300}
                                     --   ]
                                     -- }
    
    -- Constraints
    CHECK (status IN ('home', 'away', 'uncertain')),
    CHECK (confidence >= 0.0 AND confidence <= 1.0)
);

-- Index for status-based queries (e.g., "who is home?")
CREATE INDEX IF NOT EXISTS idx_presence_state_status 
ON presence_state(status);

-- Index for high-confidence presence (policy conditions)
CREATE INDEX IF NOT EXISTS idx_presence_state_confidence 
ON presence_state(status, confidence);

-- ============================================================================
-- Helper Views
-- ============================================================================

-- View: Recent presence events (last 24 hours)
CREATE VIEW IF NOT EXISTS recent_presence_events AS
SELECT 
    id,
    timestamp,
    datetime(timestamp, 'unixepoch', 'localtime') as timestamp_readable,
    source,
    signal,
    subject_id,
    person_id,
    confidence,
    metadata_json
FROM presence_events
WHERE timestamp > unixepoch() - 86400  -- Last 24 hours
ORDER BY timestamp DESC;

-- View: Current presence summary (denormalized for quick queries)
CREATE VIEW IF NOT EXISTS presence_summary AS
SELECT 
    ps.person_id,
    ps.status,
    ps.confidence,
    ps.last_updated,
    datetime(ps.last_updated, 'unixepoch', 'localtime') as last_updated_readable,
    ps.state_json,
    -- Count of supporting evidence in last hour
    (SELECT COUNT(*) 
     FROM presence_events pe 
     WHERE pe.person_id = ps.person_id 
       AND pe.timestamp > unixepoch() - 3600
       AND pe.signal IN ('heartbeat', 'vehicle_present', 'face_seen', 'override_home')
    ) as recent_home_signals,
    (SELECT COUNT(*) 
     FROM presence_events pe 
     WHERE pe.person_id = ps.person_id 
       AND pe.timestamp > unixepoch() - 3600
       AND pe.signal IN ('vehicle_left', 'override_away')
    ) as recent_away_signals
FROM presence_state ps;

-- ============================================================================
-- Example Data (for testing/demonstration)
-- ============================================================================

-- Example: Insert demo presence events
-- (These can be removed after testing)

-- Phone heartbeat example
INSERT INTO presence_events (
    timestamp, source, signal, subject_id, person_id, confidence, metadata_json
) VALUES (
    unixepoch(),
    'phone',
    'heartbeat',
    'demo_user_phone',
    'demo_user',
    0.95,
    json_object(
        'ip', '192.168.1.50',
        'rssi', -42,
        'last_seen', unixepoch()
    )
);

-- Vehicle present example
INSERT INTO presence_events (
    timestamp, source, signal, subject_id, person_id, confidence, metadata_json
) VALUES (
    unixepoch(),
    'plate',
    'vehicle_present',
    'demo_user_tesla',
    'demo_user',
    0.90,
    json_object(
        'plate', 'ABC123',
        'camera_id', 1,
        'event_id', 'evt_demo_123'
    )
);

-- Manual override example
INSERT INTO presence_events (
    timestamp, source, signal, subject_id, person_id, confidence, metadata_json
) VALUES (
    unixepoch(),
    'manual',
    'override_away',
    'demo_user',
    'demo_user',
    1.0,
    json_object(
        'source', 'voice',
        'duration_hours', 2,
        'reason', 'Going to store',
        'expires_at', unixepoch() + 7200
    )
);

-- Initialize demo presence state
INSERT INTO presence_state (
    person_id, status, confidence, last_updated, state_json
) VALUES (
    'demo_user',
    'home',
    0.86,
    unixepoch(),
    json_object(
        'reasons', json_array(
            'phone_seen_2m_ago',
            'vehicle_present'
        ),
        'evidence', json_object(
            'phone_last_seen', unixepoch() - 120,
            'vehicles_present', json_array('tesla'),
            'face_last_seen', NULL
        ),
        'raw_signals', json_array(
            json_object('source', 'phone', 'confidence', 0.95, 'age_seconds', 120),
            json_object('source', 'plate', 'confidence', 0.90, 'age_seconds', 0)
        )
    )
);

-- ============================================================================
-- Cleanup Trigger (Optional - Auto-delete old events)
-- ============================================================================

-- Trigger to automatically delete presence_events older than 30 days
-- This prevents unbounded growth while maintaining recent history
CREATE TRIGGER IF NOT EXISTS cleanup_old_presence_events
AFTER INSERT ON presence_events
BEGIN
    DELETE FROM presence_events
    WHERE timestamp < unixepoch() - (30 * 86400);  -- 30 days
END;

-- ============================================================================
-- Migration Metadata
-- ============================================================================

INSERT INTO schema_version (version, applied_ts, description)
VALUES (19, unixepoch(), 'Add presence tracking system (events + state tables)');

-- ============================================================================
-- Rollback Instructions (for reference)
-- ============================================================================

-- To rollback this migration:
-- DROP TRIGGER IF EXISTS cleanup_old_presence_events;
-- DROP VIEW IF EXISTS presence_summary;
-- DROP VIEW IF EXISTS recent_presence_events;
-- DROP INDEX IF EXISTS idx_presence_state_confidence;
-- DROP INDEX IF EXISTS idx_presence_state_status;
-- DROP TABLE IF EXISTS presence_state;
-- DROP INDEX IF EXISTS idx_presence_events_signal;
-- DROP INDEX IF EXISTS idx_presence_events_subject;
-- DROP INDEX IF EXISTS idx_presence_events_person_time;
-- DROP INDEX IF EXISTS idx_presence_events_timestamp;
-- DROP TABLE IF EXISTS presence_events;
-- DELETE FROM schema_version WHERE version = 19;

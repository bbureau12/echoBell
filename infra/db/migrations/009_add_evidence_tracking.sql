-- Migration 009: Evidence Tracking Table
-- 
-- Enables queryable evidence storage for people and vehicles.
-- Supports temporal queries, analytics, and retention-based cleanup.

CREATE TABLE IF NOT EXISTS evidence_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- Timestamps
    created_ts INTEGER NOT NULL,             -- Unix timestamp when evidence was recorded
    
    -- Event context
    event_id TEXT,                           -- FK to visitor_events (nullable for orphaned evidence)
    camera_id INTEGER,                       -- Which camera produced this evidence
    
    -- Evidence fields (matches Evidence dataclass)
    source TEXT NOT NULL,                    -- 'vision', 'ocr', 'face', 'scene', 'plate_trust', etc.
    feature TEXT NOT NULL,                   -- 'class', 'vehicle_type', 'color', 'plate_text', etc.
    value TEXT NOT NULL,                     -- The observed value
    conf REAL NOT NULL,                      -- Confidence 0.0-1.0
    
    -- Object association
    object_id INTEGER,                       -- SceneObject.object_id (links to specific detection)
    track_type TEXT,                         -- 'person' or 'vehicle' (for quick filtering)
    track_key TEXT,                          -- plate_hmac, visitor_id, or temp UUID
    
    -- Metadata
    metadata_json TEXT,                      -- Optional JSON for additional context
    
    FOREIGN KEY(event_id) REFERENCES visitor_events(event_id),
    FOREIGN KEY(camera_id) REFERENCES camera(id)
);

-- Index for cleanup queries (retention policy)
CREATE INDEX IF NOT EXISTS idx_evidence_log_created_ts 
ON evidence_log(created_ts);

-- Index for track-based queries (all evidence for a person/vehicle)
CREATE INDEX IF NOT EXISTS idx_evidence_log_track 
ON evidence_log(track_type, track_key);

-- Index for event-based queries (all evidence for an event)
CREATE INDEX IF NOT EXISTS idx_evidence_log_event 
ON evidence_log(event_id);

-- Index for source/feature queries (all vision.vehicle_type evidence)
CREATE INDEX IF NOT EXISTS idx_evidence_log_source_feature 
ON evidence_log(source, feature);

-- Index for camera-based queries (all evidence from camera 1)
CREATE INDEX IF NOT EXISTS idx_evidence_log_camera 
ON evidence_log(camera_id);

-- Index for temporal + track queries (person X evidence over last 24h)
CREATE INDEX IF NOT EXISTS idx_evidence_log_track_time 
ON evidence_log(track_type, track_key, created_ts);

-- Set schema version
PRAGMA user_version = 9;

-- Migration 010: Alert History Table
-- Date: 2026-01-24
-- Description: Track alerts sent to prevent spam and enable escalation logic

PRAGMA foreign_keys = ON;

-- Alert history for tracking what alerts were sent and when
CREATE TABLE IF NOT EXISTS alert_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- Context
    camera_id TEXT NOT NULL,
    track_key TEXT NOT NULL,              -- plate_hmac, visitor_id, or temp UUID
    track_type TEXT NOT NULL,             -- 'vehicle' or 'person'
    
    -- Policy & Action
    policy_id TEXT,                       -- Which policy triggered this alert (future use)
    alert_type TEXT NOT NULL,             -- 'telegram', 'speak', 'sms', 'webhook'
    message TEXT,                         -- Alert message/text sent
    priority TEXT DEFAULT 'normal',       -- 'low', 'normal', 'urgent'
    
    -- Timing
    sent_ts INTEGER NOT NULL,             -- Unix timestamp when alert was sent
    
    -- Success tracking
    success INTEGER DEFAULT 1,            -- 1 = sent successfully, 0 = failed
    error_message TEXT,                   -- Error details if failed
    
    FOREIGN KEY(camera_id) REFERENCES camera(id)
);

-- Index for checking recent alerts for a track (prevent spam)
CREATE INDEX IF NOT EXISTS idx_alert_history_track_time 
ON alert_history(track_key, track_type, sent_ts DESC);

-- Index for camera-based queries
CREATE INDEX IF NOT EXISTS idx_alert_history_camera 
ON alert_history(camera_id, sent_ts DESC);

-- Index for cleanup/retention queries
CREATE INDEX IF NOT EXISTS idx_alert_history_sent_ts 
ON alert_history(sent_ts);

-- Index for alert type analysis
CREATE INDEX IF NOT EXISTS idx_alert_history_type 
ON alert_history(alert_type, sent_ts DESC);

-- Set schema version
PRAGMA user_version = 10;

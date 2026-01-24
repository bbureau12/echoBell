-- Migration 004: Add edge camera registry for scheduler daemon
--
-- This table stores the registry of edge cameras that the scheduler daemon
-- will periodically trigger for captures. Cameras can be dynamically
-- added/removed and enabled/disabled without restarting the daemon.

CREATE TABLE IF NOT EXISTS edge_cameras (
    camera_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    endpoint_url TEXT NOT NULL,  -- HTTP endpoint to trigger capture (e.g., http://192.168.1.100:5000)
    enabled BOOLEAN DEFAULT 1,   -- Whether this camera should be triggered
    capture_interval_s INTEGER DEFAULT 60,  -- How often to capture (seconds), per-camera override
    last_capture_ts INTEGER,     -- Last time we attempted to trigger this camera
    last_success_ts INTEGER,     -- Last successful capture
    consecutive_failures INTEGER DEFAULT 0,  -- Track failing cameras
    metadata TEXT,               -- JSON metadata: location, priority, etc.
    created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
    updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
);

-- Index for efficient queries
CREATE INDEX IF NOT EXISTS idx_edge_cameras_enabled ON edge_cameras(enabled);
CREATE INDEX IF NOT EXISTS idx_edge_cameras_last_capture ON edge_cameras(last_capture_ts);

-- Example camera entries (front door, driveway, back door)
INSERT INTO edge_cameras (camera_id, name, endpoint_url, enabled, capture_interval_s, metadata) VALUES
(1, 'Front Door', 'http://localhost:5001', 1, 60, '{"location": "front_door", "priority": "high"}'),
(2, 'Driveway', 'http://localhost:5002', 1, 120, '{"location": "driveway", "priority": "medium"}'),
(3, 'Back Door', 'http://localhost:5003', 0, 60, '{"location": "back_door", "disabled_reason": "maintenance"}');

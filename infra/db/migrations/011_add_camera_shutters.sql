-- Migration 011: Add camera shutters (ignore regions)
-- Stores polygon-based ignore regions for cameras

CREATE TABLE IF NOT EXISTS camera_shutters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id INTEGER NOT NULL,
    name TEXT,  -- Optional label like "neighbor's driveway", "sky", etc.
    mode TEXT NOT NULL DEFAULT 'ignore',  -- 'ignore' or 'allow' (future-proof for inverse masking)
    polygon_json TEXT NOT NULL,  -- JSON array of normalized points: [[x1,y1],[x2,y2],...]
    enabled INTEGER DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (camera_id) REFERENCES camera(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_camera_shutters_camera ON camera_shutters(camera_id);
CREATE INDEX IF NOT EXISTS idx_camera_shutters_enabled ON camera_shutters(camera_id, enabled);

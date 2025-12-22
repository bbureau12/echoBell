-- Migration 005: Add camera table
-- Camera configuration and connection details

CREATE TABLE IF NOT EXISTS camera (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    location_id INTEGER,
    description TEXT,
    capability_level_id INTEGER NOT NULL,
    
    -- Network connection details
    hostname TEXT,
    ip_address TEXT,
    port INTEGER,
    protocol TEXT,          -- "rtsp", "http", "https"
    endpoint TEXT,          -- optional path/endpoint
    stream_url TEXT,        -- full constructed URL or override
    auth_profile_id INTEGER,
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_camera_name ON camera(name);
CREATE INDEX IF NOT EXISTS idx_camera_location ON camera(location_id);

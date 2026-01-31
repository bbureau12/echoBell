-- Migration 012: Add quiet hours table for time-based notification/alert suppression
-- Date: 2026-01-30

CREATE TABLE IF NOT EXISTS quiet_hours (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    weekday INTEGER NOT NULL CHECK(weekday >= 0 AND weekday <= 6),  -- 0=Monday, 6=Sunday
    start_time TEXT NOT NULL CHECK(length(start_time) = 5 AND start_time LIKE '__:__'),  -- HH:MM format (24h)
    end_time TEXT NOT NULL CHECK(length(end_time) = 5 AND end_time LIKE '__:__'),      -- HH:MM format (24h)
    enabled INTEGER DEFAULT 1 CHECK(enabled IN (0, 1)),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for fast lookups by weekday
CREATE INDEX IF NOT EXISTS idx_quiet_hours_weekday ON quiet_hours(weekday);

-- Index for enabled-only queries
CREATE INDEX IF NOT EXISTS idx_quiet_hours_enabled ON quiet_hours(enabled);

-- Insert example quiet hours (disabled by default)
INSERT INTO quiet_hours (name, weekday, start_time, end_time, enabled) VALUES
    ('Weeknight Sleep', 0, '22:00', '07:00', 0),  -- Monday
    ('Weeknight Sleep', 1, '22:00', '07:00', 0),  -- Tuesday
    ('Weeknight Sleep', 2, '22:00', '07:00', 0),  -- Wednesday
    ('Weeknight Sleep', 3, '22:00', '07:00', 0),  -- Thursday
    ('Weeknight Sleep', 4, '22:00', '07:00', 0),  -- Friday
    ('Weekend Sleep', 5, '23:00', '09:00', 0),    -- Saturday
    ('Weekend Sleep', 6, '23:00', '09:00', 0);    -- Sunday

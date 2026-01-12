-- Migration 007: Scene awareness and visitor events
-- Date: 2026-01-11
-- Description: Creates visitor_events and scene_tracks tables for visitor tracking

PRAGMA foreign_keys = ON;

-- Create visitor_events table
CREATE TABLE IF NOT EXISTS visitor_events (
    event_id TEXT PRIMARY KEY,
    visitor_id TEXT,
    camera_id INTEGER,
    detected_ts DATETIME NOT NULL,
    duration_s REAL,
    intent_inferred TEXT,
    intent_confidence REAL,
    evidence_json TEXT,
    intent_locked INTEGER NOT NULL DEFAULT 0,
    snapshot_path TEXT,
    urgency INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_visitor_events_locked 
    ON visitor_events(intent_locked, detected_ts DESC);

CREATE INDEX IF NOT EXISTS idx_visitor_events_visitor 
    ON visitor_events(visitor_id, detected_ts DESC);

CREATE INDEX IF NOT EXISTS idx_visitor_events_camera 
    ON visitor_events(camera_id, detected_ts DESC);

-- Create scene_tracks table for tracking objects across frames
CREATE TABLE IF NOT EXISTS scene_tracks (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id           INTEGER NOT NULL,
    track_type          TEXT NOT NULL,
    key_kind            TEXT NOT NULL,
    track_key           TEXT NOT NULL,
    first_seen_ts       INTEGER NOT NULL,
    last_seen_ts        INTEGER NOT NULL,
    active              INTEGER NOT NULL DEFAULT 1,
    last_box_json       TEXT,
    raw_class           TEXT,
    color               TEXT,
    last_event_id       TEXT,
    tags                TEXT,
    UNIQUE(camera_id, track_type, track_key)
);

CREATE INDEX IF NOT EXISTS idx_scene_tracks_active 
    ON scene_tracks(camera_id, track_type, active, last_seen_ts);

-- =========================
-- Migration Complete
-- =========================

PRAGMA user_version = 7;



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

-- Create visitor_embeddings table for facial recognition
CREATE TABLE IF NOT EXISTS visitor_embeddings (
    embedding_id TEXT PRIMARY KEY,
    visitor_id TEXT NOT NULL,
    model_name TEXT NOT NULL,
    embedding_dim INTEGER NOT NULL,
    embedding_blob BLOB NOT NULL,
    source_event_id TEXT,
    created_ts INTEGER NOT NULL,
    quality_score REAL NOT NULL DEFAULT 1.0,
    camera_id INTEGER
);

CREATE INDEX IF NOT EXISTS idx_visitor_embeddings_visitor 
    ON visitor_embeddings(visitor_id, created_ts DESC);

CREATE INDEX IF NOT EXISTS idx_visitor_embeddings_model 
    ON visitor_embeddings(model_name, created_ts DESC);

-- Create known_visitors table for tracking visitor patterns
CREATE TABLE IF NOT EXISTS known_visitors (
    visitor_id TEXT PRIMARY KEY,
    first_seen_ts INTEGER NOT NULL,
    last_seen_ts INTEGER NOT NULL,
    visit_count_total INTEGER NOT NULL DEFAULT 1,
    visit_count_7d INTEGER NOT NULL DEFAULT 1,
    visit_count_30d INTEGER NOT NULL DEFAULT 1,
    confidence_score REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'active',
    intent_last TEXT,
    intent_last_ts INTEGER,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_known_visitors_last_seen 
    ON known_visitors(last_seen_ts DESC);

CREATE INDEX IF NOT EXISTS idx_known_visitors_status 
    ON known_visitors(status, last_seen_ts DESC);

-- =========================
-- Migration Complete
-- =========================

PRAGMA user_version = 7;



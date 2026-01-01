-- Migration 007: Scene Awareness and Visitor Tracking
-- Date: 2025-01-XX
-- Description: Adds comprehensive visitor event tracking, scene awareness, plate sightings, and entity linkage

PRAGMA foreign_keys = ON;

-- =========================
-- Visitor Identity Tables
-- =========================

-- Known visitors (ReID-based identity tracking)
CREATE TABLE IF NOT EXISTS known_visitors (
    visitor_id          TEXT PRIMARY KEY,
    first_seen_ts       INTEGER NOT NULL,
    last_seen_ts        INTEGER NOT NULL,
    visit_count_total   INTEGER NOT NULL DEFAULT 1,
    visit_count_7d      INTEGER NOT NULL DEFAULT 1,
    visit_count_30d     INTEGER NOT NULL DEFAULT 1,
    confidence_score    REAL NOT NULL DEFAULT 0.0,
    status              TEXT NOT NULL DEFAULT 'active',
    intent_last         TEXT,
    intent_last_ts      INTEGER,
    notes               TEXT
);

CREATE INDEX IF NOT EXISTS idx_known_visitors_last_seen 
    ON known_visitors(last_seen_ts DESC);

CREATE INDEX IF NOT EXISTS idx_known_visitors_status 
    ON known_visitors(status, last_seen_ts DESC);

-- Visitor embeddings (ReID feature vectors)
CREATE TABLE IF NOT EXISTS visitor_embeddings (
    embedding_id        TEXT PRIMARY KEY,
    visitor_id          TEXT NOT NULL,
    model_name          TEXT NOT NULL,
    embedding_dim       INTEGER NOT NULL,
    embedding_blob      BLOB NOT NULL,
    source_event_id     TEXT,
    created_ts          INTEGER NOT NULL,
    quality_score       REAL NOT NULL DEFAULT 1.0,
    camera_id           INTEGER,
    FOREIGN KEY(visitor_id) REFERENCES known_visitors(visitor_id)
);

CREATE INDEX IF NOT EXISTS idx_visitor_embeddings_visitor 
    ON visitor_embeddings(visitor_id, created_ts DESC);

CREATE INDEX IF NOT EXISTS idx_visitor_embeddings_model 
    ON visitor_embeddings(model_name, created_ts DESC);

-- =========================
-- Event Tracking Tables
-- =========================

-- Visitor events (replaces old events table, supports cross-camera tracking)
CREATE TABLE IF NOT EXISTS visitor_events (
    event_id            TEXT PRIMARY KEY,
    visitor_id          TEXT,
    camera_id           INTEGER,
    detected_ts         TEXT NOT NULL,
    intent_inferred     TEXT,
    intent_confidence   REAL,
    intent_locked       INTEGER NOT NULL DEFAULT 0,
    duration_s          REAL,
    evidence_json       TEXT,
    snapshot_path       TEXT,
    created_at          INTEGER NOT NULL DEFAULT (strftime('%s','now')),
    FOREIGN KEY(visitor_id) REFERENCES known_visitors(visitor_id)
);

CREATE INDEX IF NOT EXISTS idx_visitor_events_visitor 
    ON visitor_events(visitor_id, detected_ts DESC);

CREATE INDEX IF NOT EXISTS idx_visitor_events_camera 
    ON visitor_events(camera_id, detected_ts DESC);

CREATE INDEX IF NOT EXISTS idx_visitor_events_intent 
    ON visitor_events(intent_inferred, intent_confidence DESC);

CREATE INDEX IF NOT EXISTS idx_visitor_events_locked 
    ON visitor_events(intent_locked, detected_ts DESC);

-- =========================
-- Plate Recognition Tables
-- =========================

-- Plate visit history (privacy-safe HMAC storage)
CREATE TABLE IF NOT EXISTS plate_visitors (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    plate_hmac          TEXT NOT NULL UNIQUE,
    first_seen_ts       INTEGER NOT NULL,
    last_seen_ts        INTEGER NOT NULL,
    visit_count         INTEGER NOT NULL DEFAULT 1,
    last_camera_id      INTEGER,
    notes               TEXT
);

CREATE INDEX IF NOT EXISTS idx_plate_visitors_last_seen 
    ON plate_visitors(last_seen_ts);

-- Trusted plate allowlist (for authorities, known residents, etc.)
CREATE TABLE IF NOT EXISTS trusted_plates (
    plate_hmac          TEXT PRIMARY KEY,
    label               TEXT NOT NULL,
    created_ts          INTEGER NOT NULL,
    enabled             INTEGER NOT NULL DEFAULT 1,
    notes               TEXT
);

CREATE INDEX IF NOT EXISTS idx_trusted_plates_enabled 
    ON trusted_plates(enabled);

-- Event-plate linkage (M:N relationship, supports multiple plates per event)
CREATE TABLE IF NOT EXISTS visitor_event_plate_sightings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id            TEXT NOT NULL,
    plate_hmac          TEXT NOT NULL,
    confidence          REAL,
    camera_id           INTEGER,
    object_id           INTEGER,
    created_ts          INTEGER NOT NULL,
    UNIQUE(event_id, plate_hmac),
    FOREIGN KEY(event_id) REFERENCES visitor_events(event_id)
);

CREATE INDEX IF NOT EXISTS idx_veps_event 
    ON visitor_event_plate_sightings(event_id);

CREATE INDEX IF NOT EXISTS idx_veps_plate 
    ON visitor_event_plate_sightings(plate_hmac);

-- =========================
-- Scene Awareness Tables
-- =========================

-- Scene object tracking (temporal tracking across frames)
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

CREATE INDEX IF NOT EXISTS idx_scene_tracks_tags 
    ON scene_tracks(tags);

-- Visit entity links (person-vehicle associations, etc.)
CREATE TABLE IF NOT EXISTS visit_entity_links (
    link_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    visit_id            TEXT NOT NULL,
    camera_id           INTEGER,
    relation            TEXT NOT NULL,
    confidence          REAL NOT NULL DEFAULT 0.0,
    subject_type        TEXT NOT NULL,
    subject_object_id   INTEGER NOT NULL,
    subject_key         TEXT,
    subject_meta_json   TEXT,
    object_type         TEXT NOT NULL,
    object_object_id    INTEGER NOT NULL,
    object_key          TEXT,
    object_meta_json    TEXT,
    created_ts          INTEGER NOT NULL,
    updated_ts          INTEGER NOT NULL,
    notes               TEXT,
    UNIQUE(visit_id, relation, subject_type, subject_object_id, object_type, object_object_id)
);

CREATE INDEX IF NOT EXISTS idx_visit_entity_links_visit 
    ON visit_entity_links(visit_id);

CREATE INDEX IF NOT EXISTS idx_visit_entity_links_visit_relation 
    ON visit_entity_links(visit_id, relation);

CREATE INDEX IF NOT EXISTS idx_visit_entity_links_camera_updated 
    ON visit_entity_links(camera_id, updated_ts DESC);

-- =========================
-- Vision Signal Rules
-- =========================

-- Signal rule patterns (if needed for vision classification)
CREATE TABLE IF NOT EXISTS signal_rule (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_name        TEXT NOT NULL,
    enabled             INTEGER NOT NULL DEFAULT 1,
    rule_json           TEXT NOT NULL,
    created_ts          INTEGER NOT NULL,
    updated_ts          INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_signal_rule_enabled 
    ON signal_rule(enabled);

-- =========================
-- Migration Complete
-- =========================

PRAGMA user_version = 7;

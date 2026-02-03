-- Migration 014: Add voiceprint speaker identification
-- Purpose: Store speaker voiceprints from SpeechBrain for trusted person identification

-- Voiceprints table
CREATE TABLE IF NOT EXISTS trusted_voiceprints (
    voiceprint_id INTEGER PRIMARY KEY AUTOINCREMENT,
    trusted_id INTEGER NOT NULL,
    model_name TEXT NOT NULL,              -- 'speechbrain_ecapa', 'resemblyzer', etc.
    embedding_dim INTEGER NOT NULL,        -- Typically 192 or 512
    embedding_blob BLOB NOT NULL,          -- Serialized voiceprint vector
    camera_id INTEGER,                     -- Optional: which camera/edge captured this
    created_ts INTEGER NOT NULL,
    quality_score REAL DEFAULT 1.0,        -- Quality of the audio sample
    audio_duration_sec REAL,               -- Length of audio sample used
    notes TEXT,                            -- Optional metadata
    FOREIGN KEY (trusted_id) REFERENCES trusted_person(trusted_id) ON DELETE CASCADE
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_voiceprints_trusted_id 
    ON trusted_voiceprints(trusted_id);

CREATE INDEX IF NOT EXISTS idx_voiceprints_model 
    ON trusted_voiceprints(model_name);

CREATE INDEX IF NOT EXISTS idx_voiceprints_camera 
    ON trusted_voiceprints(camera_id) 
    WHERE camera_id IS NOT NULL;

-- Composite index for model + trusted_id lookups
CREATE INDEX IF NOT EXISTS idx_voiceprints_model_trusted 
    ON trusted_voiceprints(model_name, trusted_id);

-- Table for tracking voiceprint matching attempts
-- Useful for debugging and improving matching thresholds
CREATE TABLE IF NOT EXISTS voiceprint_matches (
    match_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,                       -- Link to llm_conversations
    camera_id INTEGER,
    matched_trusted_id INTEGER,            -- NULL if no match
    confidence_score REAL NOT NULL,        -- Similarity score (0-1)
    threshold_used REAL NOT NULL,          -- Matching threshold at time of match
    model_name TEXT NOT NULL,
    matched_ts INTEGER NOT NULL,
    audio_duration_sec REAL,
    notes TEXT,
    FOREIGN KEY (matched_trusted_id) REFERENCES trusted_person(trusted_id)
);

CREATE INDEX IF NOT EXISTS idx_voiceprint_matches_session 
    ON voiceprint_matches(session_id);

CREATE INDEX IF NOT EXISTS idx_voiceprint_matches_trusted 
    ON voiceprint_matches(matched_trusted_id) 
    WHERE matched_trusted_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_voiceprint_matches_timestamp 
    ON voiceprint_matches(matched_ts);

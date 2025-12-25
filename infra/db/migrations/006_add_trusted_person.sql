-- Migration 006: Add trusted person and embeddings tables
-- Support for facial recognition of trusted individuals

CREATE TABLE IF NOT EXISTS trusted_person (
    trusted_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    label TEXT,
    created_ts INTEGER NOT NULL,
    updated_ts INTEGER,
    active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS trusted_person_embedding (
    embedding_id INTEGER PRIMARY KEY AUTOINCREMENT,
    trusted_id INTEGER NOT NULL,
    embedding_type TEXT NOT NULL,  -- 'face', 'body', etc.
    model_name TEXT NOT NULL,
    embedding_dim INTEGER NOT NULL,
    embedding_blob BLOB NOT NULL,
    created_ts INTEGER NOT NULL,
    quality_score REAL DEFAULT 1.0,
    camera_id INTEGER,
    FOREIGN KEY (trusted_id) REFERENCES trusted_person(trusted_id) ON DELETE CASCADE,
    FOREIGN KEY (camera_id) REFERENCES camera(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_trusted_person_name ON trusted_person(name);
CREATE INDEX IF NOT EXISTS idx_trusted_person_active ON trusted_person(active);
CREATE INDEX IF NOT EXISTS idx_trusted_embedding_person ON trusted_person_embedding(trusted_id);
CREATE INDEX IF NOT EXISTS idx_trusted_embedding_type ON trusted_person_embedding(embedding_type, model_name);

-- Migration 001: Initial schema

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  source TEXT DEFAULT 'user',
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS features (
  name TEXT PRIMARY KEY,
  enabled INTEGER NOT NULL CHECK (enabled IN (0,1)),
  note TEXT
);

CREATE TABLE IF NOT EXISTS modes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  mode TEXT NOT NULL CHECK (mode IN ('HOME','AWAY','WORKING','SLEEPING')),
  source TEXT NOT NULL,
  starts_at DATETIME NOT NULL,
  ends_at DATETIME
);
CREATE INDEX IF NOT EXISTS idx_modes_starts ON modes(starts_at DESC);
CREATE INDEX IF NOT EXISTS idx_modes_active ON modes(mode, starts_at);

CREATE TABLE IF NOT EXISTS dnd (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  start_local TEXT NOT NULL,
  end_local TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS visitors (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT,
  tag TEXT,
  face_hash TEXT,
  last_seen DATETIME
);
CREATE INDEX IF NOT EXISTS idx_visitors_last_seen ON visitors(last_seen DESC);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts DATETIME DEFAULT CURRENT_TIMESTAMP,
  type TEXT,
  intent TEXT,
  confidence REAL,
  urgency INTEGER,
  mode TEXT,
  snapshot_path TEXT,
  transcript TEXT,
  actions TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_intent ON events(intent);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);

CREATE TABLE IF NOT EXISTS notifiers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  target TEXT NOT NULL,
  priority TEXT DEFAULT 'normal'
);

-- Seed rows
INSERT OR IGNORE INTO dnd(id, start_local, end_local) VALUES (1,'22:00','07:00');

INSERT OR IGNORE INTO features(name, enabled, note) VALUES
  ('auto_reply_delivery', 1, 'Speak leave-it-by-door when package detected'),
  ('use_llm_for_intent_backstop', 1, 'Enable LLM fallback when conf < 0.7'),
  ('echobell_active', 1, 'Doorbell AI subsystem enabled');

INSERT OR IGNORE INTO settings(key, value, source) VALUES
  ('tts_voice', 'en_US_piper_medium', 'yaml'),
  ('llm_model', 'vicuna-7b-q4_k_m', 'yaml'),
  ('latency_budget_ms', '2000', 'yaml'),
  ('agent_echobell', 'enabled', 'user');

INSERT OR IGNORE INTO modes(id, mode, source, starts_at, ends_at)
VALUES (1, 'WORKING', 'yaml', datetime('now'), NULL);

-- Set schema version
PRAGMA user_version = 1;

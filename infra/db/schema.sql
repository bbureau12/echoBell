-- Doorbell AI - Full Schema
-- Safe to run multiple times; uses IF NOT EXISTS and idempotent inserts.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

-- =========================
-- Core tables
-- =========================

-- Key/value settings (simple config knobs)
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  source TEXT DEFAULT 'user',                 -- user|yaml|env|runtime
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Feature flags (enable/disable modules without redeploy)
CREATE TABLE IF NOT EXISTS features (
  name TEXT PRIMARY KEY,
  enabled INTEGER NOT NULL CHECK (enabled IN (0,1)),
  note TEXT
);

-- Current/scheduled modes (HOME/AWAY/WORKING/SLEEPING)
CREATE TABLE IF NOT EXISTS modes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  mode TEXT NOT NULL CHECK (mode IN ('HOME','AWAY','WORKING','SLEEPING')),
  source TEXT NOT NULL,                       -- yaml|user|schedule|presence
  starts_at DATETIME NOT NULL,
  ends_at DATETIME
);
CREATE INDEX IF NOT EXISTS idx_modes_starts ON modes(starts_at DESC);
CREATE INDEX IF NOT EXISTS idx_modes_active ON modes(mode, starts_at);

-- Quiet hours / Do Not Disturb windows (local times)
CREATE TABLE IF NOT EXISTS dnd (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  start_local TEXT NOT NULL,                  -- "22:00"
  end_local TEXT NOT NULL                     -- "07:00"
);

-- Known/opt-in visitors (tags can influence policy)
CREATE TABLE IF NOT EXISTS visitors (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT,
  tag TEXT,                                   -- neighbor|delivery|authority|sales|unknown
  face_hash TEXT,                             -- optional: embedding hash or identifier
  last_seen DATETIME
);
CREATE INDEX IF NOT EXISTS idx_visitors_last_seen ON visitors(last_seen DESC);

-- Event log (structured metadata only; no raw A/V by default)
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts DATETIME DEFAULT CURRENT_TIMESTAMP,
  type TEXT,                                  -- ring|motion|speak|notify|error
  intent TEXT,                                -- package_drop|neighbor_help|...
  confidence REAL,                            -- 0..1
  urgency INTEGER,                            -- 0..100
  mode TEXT,                                  -- HOME|AWAY|WORKING|SLEEPING
  snapshot_path TEXT,                         -- optional single JPEG path
  transcript TEXT,                            -- short text
  actions TEXT                                -- JSON string of executed plan
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_intent ON events(intent);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);

-- Notifier endpoints (Telegram/Signal/Webhook)
CREATE TABLE IF NOT EXISTS notifiers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,                         -- telegram|signal|webhook
  target TEXT NOT NULL,                       -- chat id / phone / URL
  priority TEXT DEFAULT 'normal'              -- summary|normal|priority
);

-- =========================
-- Seed data (idempotent)
-- =========================

-- Default quiet hours
INSERT OR IGNORE INTO dnd(id, start_local, end_local) VALUES (1,'22:00','07:00');

-- Feature flags
INSERT OR IGNORE INTO features(name, enabled, note) VALUES
  ('auto_reply_delivery', 1, 'Speak leave-it-by-door when package detected'),
  ('use_llm_for_intent_backstop', 1, 'Enable LLM fallback when conf < 0.7'),
  ('echobell_active', 1, 'Doorbell AI subsystem enabled');

-- Settings (TTS/LLM knobs)
INSERT OR IGNORE INTO settings(key, value, source) VALUES
  ('tts_voice', 'en_US_piper_medium', 'yaml'),
  ('llm_model', 'vicuna-7b-q4_k_m', 'yaml'),
  ('latency_budget_ms', '2000', 'yaml'),
  ('agent_echobell', 'enabled', 'user');

-- Start with WORKING mode (override as needed)
INSERT OR IGNORE INTO modes(id, mode, source, starts_at, ends_at)
VALUES (1, 'WORKING', 'yaml', datetime('now'), NULL);

-- =========================
-- Version marker
-- =========================
PRAGMA user_version = 1;

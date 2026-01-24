-- Migration: Add policy_rules table for dynamic policy management
-- Enables API-driven policy CRUD without editing YAML files

CREATE TABLE IF NOT EXISTS policy_rules (
    id TEXT PRIMARY KEY,                    -- Policy ID (e.g., "loitering_alert")
    name TEXT NOT NULL,                     -- Human-readable name
    description TEXT,                       -- What this policy does
    enabled INTEGER NOT NULL DEFAULT 1,     -- 1 = active, 0 = disabled
    priority INTEGER NOT NULL DEFAULT 50,   -- Higher = evaluated first
    conditions_json TEXT NOT NULL,          -- JSON: condition tree
    actions_json TEXT NOT NULL,             -- JSON: array of actions
    variables_json TEXT,                    -- JSON: variable definitions
    created_ts INTEGER NOT NULL,
    updated_ts INTEGER NOT NULL,
    created_by TEXT DEFAULT 'system',       -- user|system|api
    tags TEXT,                              -- Space-separated tags for filtering
    version INTEGER DEFAULT 1               -- For optimistic locking
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_policy_enabled ON policy_rules(enabled, priority DESC);
CREATE INDEX IF NOT EXISTS idx_policy_tags ON policy_rules(tags);

-- Policy execution audit log (track which policies fired)
CREATE TABLE IF NOT EXISTS policy_executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_id TEXT NOT NULL,
    event_id TEXT,                          -- FK to visitor_events
    track_key TEXT,                         -- plate_hmac or visitor_id
    track_type TEXT,                        -- 'vehicle' | 'person'
    camera_id INTEGER,
    matched_conditions TEXT,                -- JSON: which conditions matched
    executed_actions TEXT,                  -- JSON: actions executed
    execution_ts INTEGER NOT NULL,
    success INTEGER DEFAULT 1,
    error_message TEXT,
    FOREIGN KEY(policy_id) REFERENCES policy_rules(id)
);

CREATE INDEX IF NOT EXISTS idx_policy_exec_ts ON policy_executions(execution_ts DESC);
CREATE INDEX IF NOT EXISTS idx_policy_exec_policy ON policy_executions(policy_id, execution_ts DESC);

-- Example policies (seed data - can be removed once API is used)
INSERT OR IGNORE INTO policy_rules (id, name, description, enabled, priority, conditions_json, actions_json, created_ts, updated_ts)
VALUES 
(
    'unknown_vehicle_alert',
    'Unknown Vehicle Alert',
    'Alert when unknown vehicle arrives',
    1,
    80,
    '{"all": [{"evidence_exists": {"source": "vision", "feature": "vehicle_present"}}, {"evidence_missing": {"source": "plate_trust", "feature": "trusted_plate"}}]}',
    '[{"type": "telegram", "message": "⚠️ Unknown {vehicle_color} {vehicle_type} detected", "priority": "normal"}]',
    strftime('%s', 'now'),
    strftime('%s', 'now')
),
(
    'trusted_person_quiet',
    'Trusted Person - Quiet Entry',
    'No alert for known family members',
    1,
    100,
    '{"trust_check": {"check_type": "trusted_person"}}',
    '[{"type": "telegram", "message": "🏠 {person_name} arrived home", "priority": "low"}]',
    strftime('%s', 'now'),
    strftime('%s', 'now')
),
(
    'nighttime_loitering',
    'Nighttime Loitering Alert',
    'Alert if person loiters at night (>5 min)',
    1,
    90,
    '{"all": [{"time_between": {"start": "22:00", "end": "06:00"}}, {"track_duration_gt": {"track_type": "person", "duration_s": 300}}, {"no_recent_alert": {"track_type": "person", "within_seconds": 600}}]}',
    '[{"type": "telegram", "message": "⚠️ Person loitering for {duration_minutes} minutes at night", "priority": "urgent"}, {"type": "speak", "text": "You are being recorded. Please leave the premises."}]',
    strftime('%s', 'now'),
    strftime('%s', 'now')
);

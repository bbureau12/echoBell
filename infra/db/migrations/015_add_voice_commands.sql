-- Migration 015: Add voice command tracking and correlation IDs
-- Purpose: Track voice commands from Echonet edge devices and maintain correlation across LLM interactions

-- Voice commands table - audit trail of all voice interactions
CREATE TABLE IF NOT EXISTS voice_commands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    correlation_id TEXT NOT NULL UNIQUE,        -- Our internal tracking ID
    echonet_event_id TEXT NOT NULL,             -- Echonet's event_id
    session_id TEXT,                            -- Multi-turn conversation session
    
    -- Speaker identification
    voiceprint_user_id TEXT,                    -- Echonet's voiceprint user ID (e.g., "alice")
    voiceprint_confidence REAL,                 -- Voiceprint match confidence (0-1)
    trusted_person_id INTEGER,                  -- Mapped to our trusted_person table
    
    -- Command details
    text TEXT NOT NULL,                         -- Transcribed command
    speech_confidence REAL,                     -- Speech recognition confidence
    mode TEXT NOT NULL,                         -- 'triggered' or 'open_listen'
    
    -- Source metadata
    source_device TEXT NOT NULL,                -- Echonet source_id (e.g., "microphone")
    room TEXT,                                  -- Physical location
    timestamp INTEGER NOT NULL,                 -- Unix timestamp from Echonet
    received_ts INTEGER NOT NULL,               -- When we received it
    
    -- Processing results
    policy_matched TEXT,                        -- Policy ID that handled this (null = LLM)
    llm_used INTEGER DEFAULT 0,                 -- 1 if routed to LLM
    response_text TEXT,                         -- Response sent back to user
    actions_taken TEXT,                         -- JSON array of actions executed
    
    -- Authorization
    auth_result TEXT,                           -- 'allowed', 'denied', '2fa_required'
    auth_reason TEXT,                           -- Why allowed/denied
    
    -- Audit
    created_ts INTEGER NOT NULL,
    processing_time_ms INTEGER,                 -- How long processing took
    
    FOREIGN KEY (trusted_person_id) REFERENCES trusted_person(trusted_id) ON DELETE SET NULL
);

-- Indexes for voice command queries
CREATE INDEX IF NOT EXISTS idx_voice_cmd_correlation 
    ON voice_commands(correlation_id);

CREATE INDEX IF NOT EXISTS idx_voice_cmd_session 
    ON voice_commands(session_id) 
    WHERE session_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_voice_cmd_person 
    ON voice_commands(trusted_person_id) 
    WHERE trusted_person_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_voice_cmd_timestamp 
    ON voice_commands(timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_voice_cmd_echonet 
    ON voice_commands(echonet_event_id);

-- Composite index for session analysis
CREATE INDEX IF NOT EXISTS idx_voice_cmd_session_time 
    ON voice_commands(session_id, timestamp) 
    WHERE session_id IS NOT NULL;

-- Index for LLM usage analysis
CREATE INDEX IF NOT EXISTS idx_voice_cmd_llm 
    ON voice_commands(llm_used, timestamp DESC);


-- Voiceprint to person mapping
-- Links Echonet voiceprint_user_id to our trusted_person records
CREATE TABLE IF NOT EXISTS voiceprint_person_mapping (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    voiceprint_user_id TEXT NOT NULL UNIQUE,    -- Echonet's voiceprint ID
    trusted_person_id INTEGER NOT NULL,         -- Our person ID
    created_ts INTEGER NOT NULL,
    updated_ts INTEGER NOT NULL,
    notes TEXT,
    
    FOREIGN KEY (trusted_person_id) REFERENCES trusted_person(trusted_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_voiceprint_mapping_person 
    ON voiceprint_person_mapping(trusted_person_id);


-- MCP tool permissions for voice commands
-- Defines which MCP tools can be called via voice and required confidence levels
CREATE TABLE IF NOT EXISTS mcp_tool_permissions (
    tool_name TEXT PRIMARY KEY,
    voice_enabled INTEGER NOT NULL DEFAULT 0,   -- 1 = can be called via voice
    requires_confidence REAL DEFAULT 0.75,      -- Minimum voiceprint confidence
    requires_2fa INTEGER DEFAULT 0,             -- 1 = always require Telegram confirmation
    security_level TEXT DEFAULT 'normal',       -- 'low', 'normal', 'high', 'critical'
    notes TEXT,
    created_ts INTEGER NOT NULL,
    updated_ts INTEGER NOT NULL
);

-- Seed some initial tool permissions
INSERT OR IGNORE INTO mcp_tool_permissions (tool_name, voice_enabled, requires_confidence, security_level, created_ts, updated_ts)
VALUES 
    ('list_policies', 1, 0.75, 'low', strftime('%s', 'now'), strftime('%s', 'now')),
    ('get_policy', 1, 0.75, 'low', strftime('%s', 'now'), strftime('%s', 'now')),
    ('query_scene', 1, 0.75, 'normal', strftime('%s', 'now'), strftime('%s', 'now')),
    ('get_active_tracks', 1, 0.75, 'normal', strftime('%s', 'now'), strftime('%s', 'now')),
    ('get_visit_history', 1, 0.80, 'normal', strftime('%s', 'now'), strftime('%s', 'now')),
    ('log_note', 1, 0.75, 'low', strftime('%s', 'now'), strftime('%s', 'now')),
    ('create_policy', 0, 0.95, 'critical', strftime('%s', 'now'), strftime('%s', 'now')),
    ('update_policy', 0, 0.95, 'critical', strftime('%s', 'now'), strftime('%s', 'now')),
    ('delete_policy', 0, 0.95, 'critical', strftime('%s', 'now'), strftime('%s', 'now')),
    -- Echonet interaction tools (allow LLM to request more voice input)
    ('activate_echonet_listening', 1, 0.75, 'normal', strftime('%s', 'now'), strftime('%s', 'now')),
    ('deactivate_echonet_listening', 1, 0.75, 'normal', strftime('%s', 'now'), strftime('%s', 'now')),
    ('get_echonet_status', 1, 0.75, 'low', strftime('%s', 'now'), strftime('%s', 'now'));



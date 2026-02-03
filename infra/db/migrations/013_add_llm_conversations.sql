-- Migration: Add LLM conversation tracking
-- Tracks multi-turn conversations between doorbell system and Claude API

CREATE TABLE IF NOT EXISTS llm_conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT UNIQUE NOT NULL,
    camera_id INTEGER,
    started_ts INTEGER NOT NULL,
    completed_ts INTEGER,
    state TEXT NOT NULL CHECK(state IN ('active', 'complete', 'timeout', 'error')),
    context_json TEXT,          -- Initial context (visitor info, scene, etc.)
    messages_json TEXT,         -- Full conversation history
    result_action TEXT,         -- Final action taken (unlock, alert, deny, etc.)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_llm_conv_session ON llm_conversations(session_id);
CREATE INDEX IF NOT EXISTS idx_llm_conv_camera ON llm_conversations(camera_id, started_ts DESC);
CREATE INDEX IF NOT EXISTS idx_llm_conv_state ON llm_conversations(state, started_ts DESC);

-- Optional: Detailed message log (if you want granular tracking)
CREATE TABLE IF NOT EXISTS llm_conversation_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'tool')),
    content TEXT NOT NULL,
    tool_name TEXT,             -- If role='tool', which tool was used
    timestamp INTEGER NOT NULL,
    FOREIGN KEY(conversation_id) REFERENCES llm_conversations(id)
);

CREATE INDEX IF NOT EXISTS idx_llm_msg_conversation ON llm_conversation_messages(conversation_id, timestamp);

-- Example queries for monitoring:

-- Active conversations
-- SELECT * FROM llm_conversations WHERE state = 'active' ORDER BY started_ts DESC;

-- Recent conversation history
-- SELECT 
--     session_id, 
--     camera_id, 
--     datetime(started_ts, 'unixepoch') as started,
--     state,
--     result_action
-- FROM llm_conversations 
-- ORDER BY started_ts DESC 
-- LIMIT 50;

-- Average conversation duration
-- SELECT 
--     AVG(completed_ts - started_ts) as avg_duration_seconds
-- FROM llm_conversations 
-- WHERE state = 'complete';

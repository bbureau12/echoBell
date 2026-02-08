-- Migration 020: Add watches table for time-based policy evaluation
-- 
-- Watches enable deferred policy evaluation:
-- - Create watch on event (e.g., person detected)
-- - Re-evaluate conditions at due_ts
-- - Chain watches for escalation (2min → 5min → 10min)
--
-- Example flow:
--   1. Unknown person enters → create watch (due in 2 min)
--   2. At 2 min: check if still present → alert + create next watch (due in 3 min)
--   3. At 5 min: check if still present → escalate alert

CREATE TABLE IF NOT EXISTS watches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- Identification & deduplication
    watch_type TEXT NOT NULL,           -- "loitering_2min", "delivery_timeout", "vehicle_idling", etc.
    watch_key TEXT UNIQUE NOT NULL,     -- Dedup key: "cam{id}:track_{key}:{type}"
    
    -- Links to existing data
    camera_id INTEGER NOT NULL,         -- Which camera
    scene_track_id INTEGER,             -- FK to scene_tracks (optional, for track-based watches)
    event_id TEXT,                      -- Original event that created watch
    
    -- Timing
    created_ts INTEGER NOT NULL,        -- When watch was created (Unix timestamp)
    due_ts INTEGER NOT NULL,            -- When to fire/evaluate (Unix timestamp)
    evaluated_ts INTEGER,               -- When it was actually evaluated
    expires_ts INTEGER,                 -- Auto-expire if not triggered by this time
    
    -- State machine (armed → triggered/disarmed/expired)
    state TEXT NOT NULL DEFAULT 'armed',
    
    -- Context for debugging (serialized JSON)
    context_json TEXT,
    
    -- Results
    trigger_reason TEXT,                -- Why it triggered/disarmed ("track_inactive", "condition_met", etc.)
    
    -- Metadata
    created_by_policy_id TEXT,          -- Policy that created this watch
    last_updated_ts INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
    
    -- Foreign keys
    FOREIGN KEY (scene_track_id) REFERENCES scene_tracks(id) ON DELETE CASCADE,
    FOREIGN KEY (camera_id) REFERENCES camera(id) ON DELETE CASCADE,
    
    -- Constraints
    CHECK (state IN ('armed', 'triggered', 'disarmed', 'expired')),
    CHECK (due_ts > created_ts),
    CHECK (expires_ts IS NULL OR expires_ts >= due_ts)
);

-- Performance indexes
CREATE INDEX IF NOT EXISTS idx_watches_due_armed 
    ON watches(due_ts, state) 
    WHERE state = 'armed';

CREATE INDEX IF NOT EXISTS idx_watches_state 
    ON watches(state);

CREATE INDEX IF NOT EXISTS idx_watches_camera 
    ON watches(camera_id);

CREATE INDEX IF NOT EXISTS idx_watches_scene_track 
    ON watches(scene_track_id) 
    WHERE scene_track_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_watches_expires 
    ON watches(expires_ts) 
    WHERE state = 'armed' AND expires_ts IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_watches_watch_type
    ON watches(watch_type, state);

-- Migration complete

# Database Schema Reference

This document describes the complete database schema for echoBell, including all tables, their purposes, and which migrations create them.

**Current Database Version:** 9 (as of 2026-01-12)

## Quick Reference

| Table | Purpose | Created By | Key Indexes |
|-------|---------|------------|-------------|
| [visitor_events](#visitor_events) | Event log with intent classification | Migration 007 | event_id, visitor_id, camera_id, detected_ts |
| [visitor_event_plate_sightings](#visitor_event_plate_sightings) | Links events to license plates | Migration 007 | event_id, plate_hmac |
| [evidence_log](#evidence_log) | Queryable evidence tracking | Migration 009 | event_id, track_type/track_key, created_ts |
| [scene_tracks](#scene_tracks) | Object tracking across frames | Migration 007 | camera_id, track_type, active |
| [intent_def](#intent_def) | Intent definitions | Migration 003 | name |
| [signal_rule](#signal_rule) | Evidence-based classification rules | Migration 008 | source, feature, intent_name |
| [signal_group](#signal_group) | Rule groups for complex patterns | Migration 008 | intent_name |
| [pattern_def](#pattern_def) | Text pattern matching | Migration 003 | pattern |
| [cameras](#cameras) | Camera configuration | Migration 005 | camera_id |
| [settings](#settings) | System configuration | Migration 001 | key |

## Core Event Tables

### visitor_events

**Purpose:** Primary event log storing visitor interactions with intent classification.

**Created By:** Migration 007

**Schema:**
```sql
CREATE TABLE visitor_events (
    event_id TEXT PRIMARY KEY,           -- UUID for event
    visitor_id TEXT,                     -- Optional: identified visitor
    camera_id INTEGER,                   -- Which camera detected event
    detected_ts DATETIME NOT NULL,       -- When event occurred
    duration_s REAL,                     -- Event duration
    intent_inferred TEXT,                -- Classified intent (refs intent_def)
    intent_confidence REAL,              -- Classification confidence (0.0-1.0)
    evidence_json TEXT,                  -- Legacy: JSON of all evidence
    intent_locked INTEGER NOT NULL DEFAULT 0,  -- 1 = high confidence, locked
    snapshot_path TEXT,                  -- Path to saved snapshot
    urgency INTEGER DEFAULT 0            -- Urgency score (0-100)
);
```

**Indexes:**
- `idx_visitor_events_locked` - (intent_locked, detected_ts DESC)
- `idx_visitor_events_visitor` - (visitor_id, detected_ts DESC)
- `idx_visitor_events_camera` - (camera_id, detected_ts DESC)

**Related Tables:**
- Links to `evidence_log` via `event_id`
- Links to `visitor_event_plate_sightings` via `event_id`
- References `cameras` via `camera_id`
- References `intent_def` via `intent_inferred`

**Usage:**
```python
# Create event
event_id = str(uuid.uuid4())
conn.execute("""
    INSERT INTO visitor_events 
    (event_id, camera_id, detected_ts, intent_inferred, intent_confidence)
    VALUES (?, ?, ?, ?, ?)
""", (event_id, 1, int(time.time()), "package_drop", 0.92))

# Query recent events
events = conn.execute("""
    SELECT * FROM visitor_events 
    WHERE camera_id = ? 
    ORDER BY detected_ts DESC 
    LIMIT 10
""", (camera_id,)).fetchall()
```

---

### evidence_log

**Purpose:** Queryable evidence tracking for debugging and analytics. Stores individual perception signals with optional track associations.

**Created By:** Migration 009

**Schema:**
```sql
CREATE TABLE evidence_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_ts INTEGER NOT NULL,        -- Unix timestamp
    event_id TEXT,                      -- Links to visitor_events
    camera_id INTEGER,                  -- Which camera
    source TEXT NOT NULL,               -- vision|ocr|fashion|scene
    feature TEXT NOT NULL,              -- class|color|token|linkage
    value TEXT NOT NULL,                -- Observed value
    conf REAL NOT NULL,                 -- Confidence (0.0-1.0)
    object_id INTEGER,                  -- Which object in scene (0-based)
    track_type TEXT,                    -- person|vehicle (for tracking)
    track_key TEXT,                     -- visitor_id or plate_hmac
    metadata_json TEXT                  -- Additional context (JSON)
);
```

**Indexes:**
- `idx_evidence_log_created_ts` - (created_ts)
- `idx_evidence_log_event_id` - (event_id)
- `idx_evidence_log_track` - (track_type, track_key, created_ts)
- `idx_evidence_log_camera` - (camera_id, created_ts)
- `idx_evidence_log_source_feature` - (source, feature)

**Track Types:**
- `person` - Track by visitor_id
- `vehicle` - Track by plate_hmac

**Common Queries:**
```python
# Get all evidence for an event
evidence = conn.execute("""
    SELECT * FROM evidence_log 
    WHERE event_id = ? 
    ORDER BY created_ts
""", (event_id,)).fetchall()

# Get evidence timeline for a vehicle
vehicle_history = conn.execute("""
    SELECT * FROM evidence_log 
    WHERE track_type = 'vehicle' 
    AND track_key = ?
    ORDER BY created_ts DESC
""", (plate_hmac,)).fetchall()

# Find all bicycle detections
bicycles = conn.execute("""
    SELECT * FROM evidence_log 
    WHERE source = 'vision' 
    AND feature = 'vehicle_type' 
    AND value = 'bicycle'
""").fetchall()
```

**Usage with EvidenceService:**
```python
from packages.data.evidence_service import create_evidence_service

service = create_evidence_service(retention_days=30)

# Log evidence with track association
service.log_evidence(
    conn=conn,
    event_id=event_id,
    camera_id=1,
    evidence_list=[
        Evidence(source="vision", feature="class", value="vehicle", conf=0.90),
        Evidence(source="vision", feature="color", value="blue", conf=0.85)
    ],
    track_type="vehicle",
    track_key=plate_hmac,
    metadata={"raw_class": "bicycle"}
)
```

---

### visitor_event_plate_sightings

**Purpose:** Links events to license plate detections for vehicle tracking.

**Created By:** Migration 007

**Schema:**
```sql
CREATE TABLE visitor_event_plate_sightings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,             -- Links to visitor_events
    plate_hmac TEXT NOT NULL,           -- HMAC of plate text (privacy)
    confidence REAL,                    -- OCR confidence
    camera_id INTEGER,                  -- Which camera
    object_id INTEGER,                  -- Which object in scene
    created_ts INTEGER NOT NULL,        -- Unix timestamp
    UNIQUE(event_id, plate_hmac)        -- One entry per plate per event
);
```

**Usage:**
```python
# Add plate sighting
conn.execute("""
    INSERT OR IGNORE INTO visitor_event_plate_sightings
    (event_id, plate_hmac, confidence, camera_id, object_id, created_ts)
    VALUES (?, ?, ?, ?, ?, ?)
""", (event_id, plate_hmac, 0.87, camera_id, object_id, int(time.time())))
```

---

### scene_tracks

**Purpose:** Track objects (people, vehicles) across frames and events.

**Created By:** Migration 007

**Schema:**
```sql
CREATE TABLE scene_tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id INTEGER NOT NULL,         -- Which camera
    track_type TEXT NOT NULL,           -- person|vehicle
    key_kind TEXT NOT NULL,             -- visitor_id|plate_hmac
    track_key TEXT NOT NULL,            -- Actual key value
    first_seen_ts INTEGER NOT NULL,     -- First detection
    last_seen_ts INTEGER NOT NULL,      -- Most recent detection
    active INTEGER NOT NULL DEFAULT 1,  -- Currently on camera?
    last_box_json TEXT,                 -- Last bounding box (JSON)
    raw_class TEXT,                     -- YOLO class name
    color TEXT,                         -- Detected color
    last_event_id TEXT,                 -- Most recent event
    tags TEXT,                          -- Optional tags
    UNIQUE(camera_id, track_type, track_key)
);
```

**Indexes:**
- `idx_scene_tracks_active` - (camera_id, track_type, active, last_seen_ts)

**Usage:**
```python
# Update track
conn.execute("""
    INSERT INTO scene_tracks 
    (camera_id, track_type, key_kind, track_key, first_seen_ts, last_seen_ts)
    VALUES (?, ?, ?, ?, ?, ?)
    ON CONFLICT(camera_id, track_type, track_key) 
    DO UPDATE SET 
        last_seen_ts = excluded.last_seen_ts,
        active = 1
""", (camera_id, "vehicle", "plate_hmac", plate_hmac, now_ts, now_ts))
```

## Classification Tables

### intent_def

**Purpose:** Defines available intents for classification.

**Created By:** Migration 003

**Schema:**
```sql
CREATE TABLE intent_def (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,          -- Intent identifier
    description TEXT,                   -- Human-readable description
    urgency INTEGER DEFAULT 10          -- Default urgency (0-100)
);
```

**Seeded Intents:**
- `package_drop` - Delivery person dropping package
- `sales_solicit` - Salesperson/solicitation
- `neighbor_help` - Neighbor asking for help
- `authority_urgent` - Police/fire/urgent
- `technician_visit` - Utility/ISP technician
- `fundraiser_child` - Child fundraising
- `religious_outreach` - Religious missionary
- `unknown` - Unclear/other

---

### signal_rule

**Purpose:** Evidence-based classification rules (e.g., "if vision sees bicycle, boost package_drop").

**Created By:** Migration 008

**Schema:**
```sql
CREATE TABLE signal_rule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,               -- vision|ocr|fashion|scene
    feature TEXT NOT NULL,              -- class|color|token|linkage
    operator TEXT NOT NULL,             -- eq|contains|gt|lt|match
    value TEXT NOT NULL,                -- Value to compare against
    intent_name TEXT NOT NULL,          -- Intent to boost
    weight REAL DEFAULT 1.0,            -- Score contribution
    min_conf REAL DEFAULT 0.0,          -- Minimum evidence confidence
    urgency INTEGER DEFAULT 10,         -- Urgency to set
    scope_any_of TEXT,                  -- Optional: object labels
    contributes_standalone INTEGER DEFAULT 1,  -- Score without groups?
    enabled INTEGER DEFAULT 1           -- Active?
);
```

**Example Rules:**
```sql
-- Bicycle detection suggests package drop
INSERT INTO signal_rule 
(source, feature, operator, value, intent_name, weight)
VALUES ('vision', 'vehicle_type', 'eq', 'bicycle', 'package_drop', 2.0);

-- UPS uniform suggests delivery
INSERT INTO signal_rule
(source, feature, operator, value, intent_name, weight)
VALUES ('fashion', 'company', 'eq', 'ups', 'package_drop', 3.0);
```

---

### signal_group

**Purpose:** Group multiple rules for complex classification patterns.

**Created By:** Migration 008

**Schema:**
```sql
CREATE TABLE signal_group (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,                 -- Group identifier
    intent_name TEXT NOT NULL,          -- Intent to boost
    group_mode TEXT DEFAULT 'all',      -- all|any|best
    bind_scope TEXT,                    -- self|root|scene|person|vehicle
    base_weight REAL DEFAULT 1.0,       -- Base score
    urgency INTEGER DEFAULT 10,
    enabled INTEGER DEFAULT 1
);
```

**Related:** `signal_group_member` links groups to rules.

---

### pattern_def

**Purpose:** Text pattern matching for OCR/transcript classification.

**Created By:** Migration 003

**Schema:**
```sql
CREATE TABLE pattern_def (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern TEXT NOT NULL,              -- Text to match
    is_regex INTEGER NOT NULL DEFAULT 0, -- 0=substring, 1=regex
    entity_name TEXT,                   -- Links to entity_def
    intent_name TEXT,                   -- Intent to boost
    weight REAL NOT NULL DEFAULT 1.0,   -- Score contribution
    FOREIGN KEY (intent_name) REFERENCES intent_def(name)
);
```

**Example:**
```sql
INSERT INTO pattern_def (pattern, is_regex, intent_name, weight)
VALUES ('amazon', 0, 'package_drop', 0.8);
```

## Configuration Tables

### cameras

**Purpose:** Camera configuration and capabilities.

**Created By:** Migration 005

**Schema:**
```sql
CREATE TABLE cameras (
    camera_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    location TEXT,
    enabled INTEGER DEFAULT 1
);
```

---

### settings

**Purpose:** System-wide configuration key-value store.

**Created By:** Migration 001

**Schema:**
```sql
CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    source TEXT DEFAULT 'user',         -- user|yaml|env|runtime
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**Common Settings:**
- `evidence_retention_days` - How long to keep evidence (default: 30)
- `evidence_cleanup_batch_size` - Batch size for cleanup (default: 1000)
- `evidence_cleanup_enabled` - Enable auto-cleanup (default: true)

## Migration History

| Version | Migration | Description | Tables Created/Modified |
|---------|-----------|-------------|-------------------------|
| 1 | 001_init_sql.sql | Initial setup | settings, features, modes, dnd, visitors, events, notifiers |
| 2 | 002_add_echobell_settings.sql | EchoBell config | settings additions |
| 3 | 003_add_intent.sql | Intent system | intent_def, entity_def, pattern_def |
| 4 | 004_add_vision_maps.sql | Vision class mapping | vision_class_map |
| 5 | 005_add_camera.sql | Camera config | cameras |
| 6 | 006_add_trusted_person.sql | Person recognition | trusted_person, trusted_person_embedding |
| 7 | 007_scene_awareness_and_visitors.sql | Event tracking | visitor_events, scene_tracks |
| 8 | 008_add_contributes_standalone.sql | Signal rules | signal_rule, signal_group, signal_group_member |
| 9 | 009_add_evidence_tracking.sql | Evidence logging | evidence_log |

## Relationships

```
visitor_events
  ├── evidence_log (event_id)
  ├── visitor_event_plate_sightings (event_id)
  ├── cameras (camera_id)
  └── intent_def (intent_inferred)

evidence_log
  ├── visitor_events (event_id)
  └── cameras (camera_id)

scene_tracks
  └── cameras (camera_id)

signal_rule
  └── intent_def (intent_name)

signal_group
  ├── intent_def (intent_name)
  └── signal_group_member (group_id)
```

## Database Maintenance

### Checking Version

```python
from storage.dao import get_db_version
print(f"Database version: {get_db_version()}")
```

### Applying Migrations

```python
from storage.dao import migrate
migrate()
```

### Evidence Cleanup

```bash
# Dry run
python scripts/cleanup_evidence.py --dry-run --verbose

# Actual cleanup (30 days retention)
python scripts/cleanup_evidence.py --retention-days 30

# Force cleanup without confirmation
python scripts/cleanup_evidence.py --force
```

### Querying Schema

```python
import sqlite3

conn = sqlite3.connect('data/echo_local.db')

# List all tables
tables = conn.execute("""
    SELECT name FROM sqlite_master 
    WHERE type='table' 
    ORDER BY name
""").fetchall()

# Get table schema
schema = conn.execute("""
    SELECT sql FROM sqlite_master 
    WHERE type='table' AND name='visitor_events'
""").fetchone()[0]
```

## Performance Considerations

### Indexes

All tables have appropriate indexes for common queries:
- Time-based queries: indexed on timestamp columns
- Lookups: indexed on ID/key columns
- Foreign keys: indexed for join performance

### Retention

- `evidence_log` - Cleaned up by retention policy (default: 30 days)
- `visitor_events` - Retained indefinitely (consider archive strategy)
- `scene_tracks` - Marked inactive after timeout

### Query Optimization

```python
# ❌ Slow: Full table scan
conn.execute("SELECT * FROM evidence_log WHERE created_ts > ?", (cutoff,))

# ✅ Fast: Uses idx_evidence_log_created_ts
conn.execute("""
    SELECT * FROM evidence_log 
    WHERE created_ts > ? 
    ORDER BY created_ts DESC
""", (cutoff,))
```

## See Also

- [CONTRIBUTING.md](../CONTRIBUTING.md) - Migration best practices
- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture
- [EVIDENCE_TRACKING.md](EVIDENCE_TRACKING.md) - Evidence system guide

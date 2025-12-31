# EchoBell Architecture

**Document Version**: 1.0  
**Last Updated**: December 31, 2025  
**Branch**: scene_awareness

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Core Architecture](#core-architecture)
3. [Data Flow](#data-flow)
4. [Module Breakdown](#module-breakdown)
5. [Key Design Patterns](#key-design-patterns)
6. [Database Schema](#database-schema)
7. [Configuration System](#configuration-system)
8. [Testing & Development](#testing--development)

---

## System Overview

EchoBell is a privacy-focused, multimodal doorbell intelligence system that:

- **Detects and classifies** visitors using computer vision, OCR, and facial recognition
- **Tracks scene changes** including vehicle/person arrivals and departures
- **Infers intent** from multimodal evidence (visual, textual, temporal, historical)
- **Respects privacy** through hashing, minimal retention, and configurable policies
- **Maintains context** across visits using plate tracking and visitor memory
- **Provides actionable alerts** based on configurable rules and learned patterns

### Design Principles

1. **Privacy-first**: No raw images stored; embeddings and HMACs only
2. **Evidence-based reasoning**: All decisions traced to specific evidence
3. **Configurable thresholds**: All magic numbers exposed in config
4. **Stateless classification**: Intent classification is pure function of evidence
5. **Stateful tracking**: Scene awareness persists across frames/events
6. **Separation of concerns**: Clear boundaries between perception, classification, storage

---

## Core Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         EchoBell System                         │
└─────────────────────────────────────────────────────────────────┘
                                │
                ┌───────────────┴───────────────┐
                │                               │
        ┌───────▼────────┐              ┌──────▼──────┐
        │  Perception    │              │   Policy    │
        │   Pipeline     │              │   Engine    │
        └───────┬────────┘              └──────┬──────┘
                │                              │
        ┌───────▼────────┐              ┌──────▼──────┐
        │ Classification │              │   Action    │
        │    & Logging   │              │  Executor   │
        └───────┬────────┘              └─────────────┘
                │
        ┌───────▼────────┐
        │   Storage &    │
        │  Persistence   │
        └────────────────┘
```

### Layer Responsibilities

**Perception Layer** (`packages/perception/`):
- Vision: Object detection, classification, color analysis
- OCR: License plate reading with pattern-based validation
- ASR: Audio transcription (future/placeholder)
- Face recognition: Visitor embedding matching

**Classification Layer** (`packages/classify/`):
- Intent classification from multimodal evidence
- Pattern matching (text, regex, entities)
- Signal rules (vision, plate history, scene events)
- Evidence grouping and confidence aggregation

**Storage Layer** (`packages/data/`, `storage/`):
- Visitor events and identity tracking
- Plate visit history with privacy-safe HMACs
- Scene tracking (vehicle/person trajectories)
- Snapshot management with retention policies

**Policy Layer** (`packages/policy/`):
- Rule-based action selection
- Context-aware decision making
- Configurable response templates

---

## Data Flow

### Complete Request Lifecycle

```
1. Image Capture
   └─> snapshot_and_detect()
       ├─> Object Detection (YOLOv8)
       ├─> Color Analysis (per vehicle/object)
       ├─> OCR (PaddleOCR on vehicle crops)
       │   └─> Plate Validation & Boosting
       ├─> Face Recognition (InsightFace)
       └─> Evidence Collection
           └─> VisionResult (objects, evidence, detections)

2. Plate Processing
   └─> group_plate_tokens()
       ├─> Proximity grouping (spatial clustering)
       ├─> Pattern validation (length, alpha/digit balance)
       ├─> Spatial validation (center-bottom of vehicle)
       ├─> Size validation (1-5% of vehicle area)
       └─> Confidence boosting (pattern + position + size)

3. Classification
   └─> classify()
       ├─> Text pattern matching (regex, keywords, entities)
       ├─> Vision signal rules (vehicle, person, plate evidence)
       ├─> Plate history lookup (past intents for this vehicle)
       ├─> Signal grouping (co-occurrence within spatial scope)
       └─> Intent selection (weighted score aggregation)

4. Event Logging
   └─> classify_and_log()
       ├─> Create visitor_event (with or without visitor_id)
       ├─> Link plate sightings (visitor_event_plate_sightings)
       ├─> Update scene tracking (vehicle/person enter/exit)
       ├─> Save snapshots (if retention policy allows)
       └─> Lock intent (if confidence >= threshold)

5. Scene Tracking
   └─> SceneTracker.update()
       ├─> Match observations to existing tracks
       │   ├─> Strong key matching (plate_hmac, visitor_id)
       │   └─> IoU matching (bounding box overlap)
       ├─> Create new tracks (for new vehicles/people)
       ├─> Mark exits (after grace period without detection)
       └─> Generate evidence (entered, exited, still_present, count)
```

---

## Module Breakdown

### `packages/perception/`

#### `vision.py` - Main Vision Pipeline

**Key Function**: `snapshot_and_detect()`

```python
def snapshot_and_detect(
    db_path: str,
    img_source: str | np.ndarray,
    camera_id: str | None = None,
    debug: bool = False,
    cache = None,
    camera_service = None,
    plate_service = None,
    plate_modifiers: PlateModifiers | None = None,
) -> VisionResult
```

**Responsibilities**:
1. Load image from file or use provided array
2. Run object detection (YOLOv8 via Ultralytics)
3. Analyze vehicle colors (K-means clustering on crops)
4. Run OCR on vehicle bounding boxes
5. Process plate candidates with configurable boosting
6. Run face recognition on person detections
7. Establish parent-child relationships (person in vehicle)
8. Return structured VisionResult with objects and evidence

**Evidence Generated**:
- `vision.vehicle_present = "true"` (conf: 0.9)
- `vision.color = "white"` (conf: 0.8)
- `ocr.plate_text = "ABC1234"` (conf: 0.12 → 0.87 after boosting)
- `face.visitor_id = "uuid..."` (conf: similarity score)

#### `plate_heurystics.py` - License Plate Validation

**Key Classes**:

```python
@dataclass
class PlateModifiers:
    """Configurable parameters for plate detection."""
    boost_standard_length: float = 0.35      # 6-7 char plates
    boost_acceptable_length: float = 0.20    # 5 or 8 char plates
    boost_good_balance: float = 0.35         # 2-4 alphas AND 2-4 digits
    boost_weak_balance: float = 0.20         # Any alphas AND any digits
    boost_spatial_position: float = 0.15     # Center-bottom of vehicle
    boost_size_ratio: float = 0.10           # 1-5% of vehicle area
    max_confidence: float = 0.95
    expected_horizontal_range: tuple = (0.2, 0.8)
    expected_vertical_range: tuple = (0.5, 1.0)
    expected_size_ratio_range: tuple = (0.01, 0.05)
    # ... grouping and validation thresholds
```

**Boost Formula**:
```python
new_conf = raw_conf + boost * (1 - raw_conf)
# Diminishing returns: low confidence gets bigger boost
```

**Multi-factor Validation**:
1. **Pattern**: Length (6-7 optimal) + Alpha/digit balance
2. **Spatial**: Plate position within vehicle bbox (center-bottom)
3. **Size**: Plate area relative to vehicle (1-5%)

**Example**: Raw OCR confidence 0.12 → Final confidence 0.87
- Standard length (6 chars): +0.35
- Good balance (3 alpha, 3 digit): +0.35
- Spatial position (0.29, 0.81): +0.15
- Size ratio (0.023): +0.10
- **Total boost**: 0.95 → Boosted: 0.12 + 0.95*(1-0.12) = 0.956 (capped at 0.95)

#### `ocr.py` - Text Recognition

**Key Function**: `extract_ocr_tokens_by_object()`

Uses PaddleOCR to:
- Run OCR on cropped vehicle regions
- Filter by confidence threshold (default: 0.6)
- Normalize text (uppercase, alphanumeric only)
- Return structured OCRToken objects with bboxes

### `packages/classify/`

#### `intent.py` - Core Classification Logic

**Key Function**: `classify()`

```python
def classify(
    text: str, 
    vision: VisionResult, 
    db_path: str | None = None,
    plate_service = None,
) -> Classified
```

**Three-stage Classification**:

1. **Text Pattern Matching**:
   - Regex patterns → intent mapping
   - Entity extraction → intent tagging
   - Example: "help" keyword → neighbor_help intent

2. **Vision Signal Rules** (DB-driven):
   - Stored in `signal_rule` table
   - Match on evidence (source, feature, value patterns)
   - Example: `vision.vehicle_present = "true"` → delivery_scan +0.6

3. **Plate History Integration**:
   - Lookup past intents for detected plates
   - Weight by frequency and past confidence
   - Example: Plate seen 5x as "delivery" → boost delivery intent

4. **Signal Grouping**:
   - Group related signals with spatial scoping
   - Example: "delivery uniform" + "vehicle present" → delivery_arriving

**Output**: `Classified(intent, confidence, urgency, trace)`

#### `classify_and_log.py` - Orchestration & Persistence

**Main Function**: `classify_and_log()`

**Refactored Architecture** (clean separation):

```python
classify_and_log()
├─> classify()                          # Pure classification
├─> _link_plates_to_event()             # Plate persistence
├─> _update_scene_tracking()            # Scene state updates
├─> _save_visitor_snapshot()            # Snapshot management
└─> update_visitor_event_intent()       # Intent locking
```

**Helper Functions**:
- `_ensure_plate_sighting_schema()`: DB schema setup
- `_link_plates_to_event()`: Process plate reads, return HMAC mapping
- `_update_scene_tracking()`: Scene tracker updates, evidence injection
- `_save_visitor_snapshot()`: Conditional snapshot saving

**Key Insight**: Single `plate_service.upsert_plate_visit()` call per plate
- No redundant DB operations
- HMAC mapping reused for scene tracking

### `packages/scene/`

#### `scene_tracker.py` - Temporal Object Tracking

**Purpose**: Track vehicles and people across frames to detect arrivals/departures

**Key Class**: `SceneTracker`

```python
class SceneTracker:
    def __init__(self, *, iou_match_threshold=0.30, grace_period_s=6):
        # IoU threshold for bounding box matching
        # Grace period before marking object as exited
```

**Matching Strategy** (priority order):

1. **Strong Key Matching** (highest priority):
   - Vehicles: Match by `plate_hmac`
   - People: Match by `visitor_id`
   - Ensures same entity tracked even if moves

2. **IoU Matching** (fallback):
   - Calculate Intersection over Union of bboxes
   - Match if IoU >= threshold (default 30%)
   - Handles objects without strong identifiers

3. **Grace Period Handling**:
   - Don't mark exit immediately when not detected
   - Wait `grace_period_s` (default 6 seconds)
   - Prevents false exits from occlusion or detection gaps

**Evidence Generated**:

```python
# Per object type (vehicle, person):
Evidence("scene", "vehicle_entered", "1", 0.9)
Evidence("scene", "vehicle_exited", "1", 0.9)
Evidence("scene", "vehicle_still_present", "2", 0.8)
Evidence("scene", "vehicle_count", "2", 1.0)
Evidence("scene", "vehicle_present", "true", 0.9)
```

**Database Schema**:

```sql
CREATE TABLE scene_tracks (
    id INTEGER PRIMARY KEY,
    camera_id INTEGER,
    track_type TEXT,        -- 'vehicle' | 'person'
    key_kind TEXT,          -- 'plate' | 'visitor' | 'iou'
    track_key TEXT,         -- HMAC or temp UUID
    first_seen_ts INTEGER,
    last_seen_ts INTEGER,
    active INTEGER,         -- 1 = active, 0 = exited
    last_box TEXT,          -- JSON bbox
    raw_class TEXT,         -- 'car', 'truck', etc.
    color TEXT,
    last_event_id TEXT,
    UNIQUE(camera_id, track_key)
);
```

### `packages/data/`

#### `plate_service.py` - Plate Visit Management

**Key Functions**:

```python
def upsert_plate_visit(conn, raw_plate_text, camera_id, seen_ts):
    """
    Insert or update plate visit.
    Returns PlateVisitResult with plate_hmac.
    Privacy: stores HMAC, not raw text.
    """

def get_plate_intent_history(conn, raw_plate_text, limit=10):
    """
    Lookup past intents for a plate.
    Returns list of {intent, count, avg_conf, last_seen_ts}.
    Used to boost intent classification for known vehicles.
    """
```

**Privacy Model** (see ADR-00002):
- Raw plate text → SHA256 HMAC with secret salt
- Only HMAC stored in database
- Raw text never persisted
- HMAC allows matching without exposing PII

#### `visitor_memory.py` - Event & Identity Tracking

**Key Functions**:

```python
def create_visitor_event(conn, event_id, visitor_id, detected_ts_iso, 
                         intent, intent_conf, evidence):
    """
    Create visitor event (with or without visitor_id).
    Events can exist independently of identity (see ADR-00001).
    """

def update_visitor_event_intent(conn, event_id, intent, intent_conf, evidence):
    """
    Lock intent when confidence is high (>= threshold).
    Updates intent_locked flag to prevent future changes.
    """
```

**Schema Relationship**:

```
visitor_events
├─> visitor_id (nullable, FK to visitors)
├─> intent (classification result)
├─> intent_conf (0.0-1.0)
└─> intent_locked (boolean)

visitor_event_plate_sightings
├─> event_id (FK to visitor_events)
├─> plate_hmac (FK to plate_visitors)
├─> confidence (OCR confidence after boosting)
└─> object_id (vehicle SceneObject.object_id)
```

### `packages/policy/`

#### `apply.py` - Action Selection

**Key Function**: `choose_action(policies, context)`

Selects appropriate response based on:
- Classified intent
- Current mode (HOME, AWAY, SLEEP)
- Scene context (vehicle present, visitor known, etc.)

Returns action plan:
```python
{
    "speak": "Hello! One moment please.",
    "notify": "delivery_app",
    "unlock": False
}
```

---

## Key Design Patterns

### 1. Evidence-Based Architecture

**Pattern**: All decisions trace back to explicit Evidence objects

```python
@dataclass
class Evidence:
    source: str      # "vision", "ocr", "face", "scene", "plate_history"
    feature: str     # "vehicle_present", "plate_text", "visitor_id"
    value: str       # Feature value
    conf: float      # Confidence 0.0-1.0
    object_id: int | None  # Reference to SceneObject
```

**Benefits**:
- Transparent decision-making
- Traceable classification (see `classified.trace`)
- Debuggable and testable
- Supports multi-modal fusion

### 2. Configurable Heuristics

**Pattern**: All magic numbers exposed in config

```python
# Before (hard-coded):
if len(plate) == 6 and confidence > 0.6:
    boost = 0.3

# After (configurable):
if modifiers.min_length <= len(plate) <= modifiers.max_length:
    boost = modifiers.boost_standard_length
```

**Benefits**:
- Tunable without code changes
- A/B testing different thresholds
- Environment-specific configs
- Clear documentation of assumptions

### 3. Separation of Concerns

**Pattern**: Clean module boundaries with single responsibilities

```python
# Perception: WHAT is in the scene
vision_result = snapshot_and_detect(...)

# Classification: WHY are they here
classified = classify(vision=vision_result, ...)

# Persistence: RECORD the event
classify_and_log(..., vision=vision_result)

# Policy: HOW to respond
action = choose_action(classified.intent, ...)
```

**Benefits**:
- Easy to test in isolation
- Reusable components
- Clear data flow
- Reduced coupling

### 4. Privacy by Design

**Pattern**: Hash sensitive data at collection point

```python
# Never store raw plate text
raw_text = "ABC1234"
plate_hmac = hmac.sha256(raw_text + salt)
# Only store: plate_hmac

# Never store raw images
face_embedding = model.get_embedding(face_crop)
# Only store: embedding vector
```

**Benefits**:
- GDPR/privacy compliance
- Reduced attack surface
- Minimal PII exposure
- Reversibility not possible

### 5. Temporal Context

**Pattern**: Track state changes over time

```python
# Not just "vehicle present"
# But: "vehicle ENTERED", "vehicle STILL present", "vehicle EXITED"

# Scene tracker maintains:
- first_seen_ts
- last_seen_ts
- active flag
- Track continuity across frames
```

**Benefits**:
- Detect arrivals vs. stationary
- Trigger on state changes
- Reduce alert fatigue
- Understand dwell time

---

## Database Schema

### Core Tables

#### `visitor_events`
Primary event log for all detections.

```sql
CREATE TABLE visitor_events (
    event_id TEXT PRIMARY KEY,
    visitor_id TEXT,                  -- FK to visitors (nullable)
    detected_ts_iso TEXT,
    intent TEXT,
    intent_conf REAL,
    intent_locked INTEGER DEFAULT 0,  -- Boolean flag
    evidence_json TEXT,               -- JSON blob of evidence
    FOREIGN KEY(visitor_id) REFERENCES visitors(visitor_id)
);
```

#### `plate_visitors`
Plate visit history (privacy-safe).

```sql
CREATE TABLE plate_visitors (
    plate_hmac TEXT PRIMARY KEY,      -- SHA256 HMAC (not raw text!)
    first_seen_ts INTEGER,
    last_seen_ts INTEGER,
    visit_count INTEGER DEFAULT 1,
    camera_id INTEGER
);
```

#### `visitor_event_plate_sightings`
Links plates to events (M:N relationship).

```sql
CREATE TABLE visitor_event_plate_sightings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    plate_hmac TEXT NOT NULL,
    confidence REAL,
    camera_id INTEGER,
    object_id INTEGER,                -- SceneObject.object_id
    created_ts INTEGER NOT NULL,
    UNIQUE(event_id, plate_hmac),
    FOREIGN KEY(event_id) REFERENCES visitor_events(event_id)
);
```

#### `scene_tracks`
Temporal tracking of objects across frames.

```sql
CREATE TABLE scene_tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id INTEGER NOT NULL,
    track_type TEXT NOT NULL,         -- 'vehicle' | 'person'
    key_kind TEXT NOT NULL,           -- 'plate' | 'visitor' | 'iou'
    track_key TEXT NOT NULL,          -- HMAC, visitor_id, or temp UUID
    first_seen_ts INTEGER NOT NULL,
    last_seen_ts INTEGER NOT NULL,
    active INTEGER DEFAULT 1,         -- 1 = active, 0 = exited
    last_box TEXT,                    -- JSON: {"x1":..., "y1":...}
    raw_class TEXT,                   -- 'car', 'truck', etc.
    color TEXT,
    last_event_id TEXT,
    UNIQUE(camera_id, track_key)
);
```

#### `signal_rule`
Intent classification rules (data-driven).

```sql
CREATE TABLE signal_rule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    intent_name TEXT NOT NULL,
    source TEXT,                      -- Evidence source filter
    feature TEXT,                     -- Evidence feature filter
    value_pattern TEXT,               -- Pattern to match value
    is_regex INTEGER DEFAULT 0,
    weight REAL DEFAULT 0.5,
    urgency INTEGER DEFAULT 10,
    enabled INTEGER DEFAULT 1
);
```

### Indexes

```sql
-- Performance indexes
CREATE INDEX idx_veps_event ON visitor_event_plate_sightings(event_id);
CREATE INDEX idx_veps_plate ON visitor_event_plate_sightings(plate_hmac);
CREATE INDEX idx_scene_tracks_camera_active ON scene_tracks(camera_id, active);
CREATE INDEX idx_scene_tracks_type ON scene_tracks(track_type);
```

---

## Configuration System

### `config.json`

Central configuration for all tunable parameters.

```json
{
  "db_path": "data/doorbell.db",
  "redis_enabled": true,
  "cache_short_minutes": 5,
  "cache_medium_minutes": 90,
  
  "retention": {
    "save_visitor_snapshot": true,
    "gap_between_visits_seconds": 3600
  },
  
  "plate_modifiers": {
    "boost_standard_length": 0.35,
    "boost_acceptable_length": 0.20,
    "boost_good_balance": 0.35,
    "boost_weak_balance": 0.20,
    "boost_spatial_position": 0.15,
    "boost_size_ratio": 0.10,
    "max_confidence": 0.95,
    "expected_horizontal_range": [0.2, 0.8],
    "expected_vertical_range": [0.5, 1.0],
    "expected_size_ratio_range": [0.01, 0.05],
    "max_horizontal_gap": 2.0,
    "max_vertical_offset": 0.5,
    "min_component_len": 2,
    "max_component_len": 4,
    "min_candidate_len": 5,
    "max_candidate_len": 8
  }
}
```

### `AppConfig` Class

Type-safe configuration model.

```python
@dataclass
class AppConfig:
    db_path: str
    redis_host: str
    redis_port: int
    redis_enabled: bool
    retention: RetentionSettings
    plate_modifiers: PlateModifiers
    
    @classmethod
    def from_json_or_defaults(cls, path: str) -> AppConfig:
        # Load from file or use sensible defaults
```

### Environment-Specific Configs

```
config.json           # Development
config.prod.json      # Production
config.test.json      # Testing
```

---

## Testing & Development

### `tools/vision_harness.py`

Comprehensive testing harness for vision pipeline.

**Features**:
- Dataset iteration (folder-based test cases)
- Vision detection with full pipeline
- Plate extraction and validation
- Intent classification
- Scene tracking integration
- Evidence inspection
- Annotated output images

**Usage**:

```bash
# Run all test cases
python tools/vision_harness.py

# Run specific folder
python tools/vision_harness.py --dataset data/samples/delivery

# Enable debug mode
python tools/vision_harness.py --debug
```

**Test Case Structure**:

```
data/samples/
├── delivery/
│   ├── 1.jpg
│   └── 2.jpg
├── police/
│   └── 1.jpg
└── neighbor/
    ├── trusted_face.jpg
    └── unknown.jpg
```

Folder name becomes expected intent for validation.

### Development Workflow

1. **Add test case**: Drop image in appropriate folder
2. **Run harness**: `python tools/vision_harness.py`
3. **Inspect output**: Check evidence, trace, classification
4. **Tune config**: Adjust thresholds in `config.json`
5. **Re-run**: Validate improvements
6. **Commit**: Update ADRs if architectural change

---

## Extension Points

### Adding New Evidence Sources

1. Create new module in `packages/perception/`
2. Return `List[Evidence]` from detection function
3. Add to `VisionResult.evidence` in `snapshot_and_detect()`
4. Create signal rules in `signal_rule` table
5. Test with vision harness

### Adding New Intent Types

1. Add to `intent_def` table
2. Create `pattern_def` or `signal_rule` entries
3. Set urgency levels
4. Add to policy YAML for action mapping
5. Test classification with sample data

### Adding New Actions

1. Create handler in `packages/notifiers/` or `packages/tts/`
2. Add to `choose_action()` logic
3. Update policy templates
4. Test end-to-end flow

---

## Performance Considerations

### Caching Strategy

- **Short cache** (5 min): Transient detections
- **Medium cache** (90 min): Face embeddings
- **Long cache** (24 hr): Stable reference data

### Database Optimization

- Indexes on frequently queried columns
- Connection pooling for concurrent requests
- Periodic cleanup of old events (retention policy)

### Vision Pipeline

- YOLOv8 model size vs. accuracy tradeoff
- OCR only on vehicle crops (not full image)
- Face recognition only on person crops
- Batch processing when applicable

---

## Related Documentation

- [Demo Walkthrough](demo.md) - Quick feature demonstration
- [ADR-00001](adr/ADR-00001-event-without-visitor.md) - Events without visitor identity
- [ADR-00002](adr/ADR-00002-plate-privacy-hmac.md) - Plate privacy via HMAC
- [ADR-00003](adr/ADR-00003-plates-as-events-not-identity.md) - Plate as evidence, not identity
- [ADR-0004](adr/ADR-0004-vehicle-role-inference.md) - Vehicle role inference
- [ADR-0005](adr/ADR-0005-scene-awareness-temporal-tracking.md) - Scene awareness & tracking

---

## Glossary

**Evidence**: Structured observation from a sensor/detector (vision, OCR, face, scene)

**Intent**: Classified purpose of visitor (delivery, neighbor, authority, etc.)

**Signal**: A matching evidence → intent rule (stored in `signal_rule`)

**Track**: Temporal sequence of observations for same object across frames

**HMAC**: Hash-based Message Authentication Code (privacy-safe plate identifier)

**IoU**: Intersection over Union (bounding box overlap metric)

**Visitor**: Known person with stored face embedding and visit history

**Event**: Single detection occurrence (may or may not have visitor_id)

**Scene**: Current state of all tracked objects in camera view

---

**End of Architecture Document**

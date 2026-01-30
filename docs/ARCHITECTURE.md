# EchoBell Architecture

**Document Version**: 1.2  
**Last Updated**: January 3, 2026  
**Branch**: intent_tracking

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Core Architecture](#core-architecture)
3. [Data Flow](#data-flow)
4. [Module Breakdown](#module-breakdown)
5. [Key Design Patterns](#key-design-patterns)
6. [Database Schema](#database-schema)
7. [Configuration System](#configuration-system)
8. [Integrations](#integrations)
9. [Testing & Development](#testing--development)

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

3. Evidence Enrichment (PHASE 1 in classify_and_log)
   └─> BEFORE classification
       ├─> _link_plates_to_event()
       │   ├─> plate_service.upsert_plate_visit() - record visit to plate_visitors
       │   ├─> plate_service.is_plate_trusted() - check trusted_plates table
       │   │   └─> Returns {plate_hmac, label, enabled} if found
       │   ├─> Add trusted_plate evidence to vision.evidence
       │   │   └─> Evidence("plate_trust", "trusted_plate", label, 1.0)
       │   └─> Add trusted info to vehicle SceneObject.props
       │       └─> props["trusted_label"] = label
       ├─> _update_scene_tracking()
       │   ├─> SceneTracker.update() - track vehicles/people in scene_tracks
       │   ├─> Generate scene.* evidence (entered, exited, present, count)
       │   └─> Add scene evidence to vision.evidence
       └─> _link_people_to_vehicles()
           ├─> Check first_appearance_window (3 seconds)
           ├─> Match visitor_id from trusted_person table (via face recognition)
           ├─> Link people to vehicles they arrived in
           └─> Add person_linked.vehicle_plate evidence

4. Classification (PHASE 2 in classify_and_log)
   └─> classify() - with ENRICHED evidence
       ├─> Text pattern matching (regex, keywords, entities)
       ├─> Vision signal rules (vehicle, person, plate evidence)
       ├─> Trusted plate evidence (plate_trust.trusted_plate)
       ├─> Scene tracking evidence (scene.vehicle_entered, etc.)
       ├─> Person-vehicle linkage (person_linked.vehicle_plate)
       ├─> Plate history lookup (past intents for this vehicle)
       ├─> Signal grouping (co-occurrence within spatial scope)
       └─> Intent selection (weighted score aggregation)

5. Event Persistence (PHASE 3 in classify_and_log)
   └─> After classification
       ├─> create_visitor_event() - with classified intent
       ├─> Save snapshots (if retention policy allows)
       └─> update_visitor_event_intent() - lock if high confidence

6. Scene Tracking Details
   └─> SceneTracker.update()
       ├─> Match observations to existing tracks
       │   ├─> Strong key matching (plate_hmac, visitor_id) - PRIORITY
       │   ├─> IoU matching (bounding box overlap) - FALLBACK
       │   └─> Upgrade temp → plate_hmac when plate detected
       ├─> Create new tracks
       │   ├─> Use plate_hmac if available (stable identity)
       │   └─> Use temp:UUID otherwise (ephemeral)
       ├─> Mark exits (after 6s grace period without detection)
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
3. **Filter detections through camera shutters** (polygon-based ignore regions)
4. Analyze vehicle colors (K-means clustering on crops)
5. Run OCR on vehicle bounding boxes
6. Process plate candidates with configurable boosting
7. Run face recognition on person detections
8. Establish parent-child relationships (person in vehicle)
9. Return structured VisionResult with objects and evidence

> **Camera Shutters**: Polygon-based ignore regions that filter out detections before processing. Used to eliminate false positives (sky, neighbors, TV screens), protect privacy, and optimize performance. See [ADR-008](adr/ADR-008-camera-shutters.md) and [tools/shutter/README.md](../tools/shutter/README.md).

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

**Updated 3-Phase Architecture** (evidence enrichment → classification → persistence):

```python
classify_and_log()
├─> PHASE 1: Evidence Enrichment
│   ├─> _link_plates_to_event()         # Adds trusted_plate evidence
│   ├─> _update_scene_tracking()        # Adds scene.* evidence
│   ├─> _link_people_to_vehicles()      # Adds linkage evidence
│   └─> _add_visitor_intent_history()   # Adds cross-camera intent persistence
├─> PHASE 2: Classification
│   └─> classify()                      # With ENRICHED evidence
└─> PHASE 3: Persistence
    ├─> create_visitor_event()          # Event creation with camera_id
    ├─> _save_visitor_snapshot()        # Snapshot management
    └─> update_visitor_event_intent()   # Intent locking
```

**Critical Design Decision**: Evidence enrichment happens BEFORE classification
- Scene tracking adds `scene.vehicle_entered`, `scene.person_entered`
- Trusted plates add `plate_trust.trusted_plate=<label>`
- Person-vehicle linkage adds `person_linked.vehicle_plate=<hmac>`
- Visitor history adds `visitor_history.recent_intent=<intent>` (cross-camera persistence)
- Classifier sees complete evidence picture for accurate intent inference

**Helper Functions**:
- `_ensure_plate_sighting_schema()`: DB schema setup
- `_link_plates_to_event()`: Process plates, add trusted evidence, return HMAC mapping
- `_update_scene_tracking()`: Scene tracker updates, evidence injection
- `_link_people_to_vehicles()`: Person-vehicle association with first-appearance check
- `_add_visitor_intent_history()`: Cross-camera intent persistence via visitor_id lookup
- `_save_visitor_snapshot()`: Conditional snapshot saving

**Key Insights**:
- Single `plate_service.upsert_plate_visit()` call per plate (no redundant DB ops)
- HMAC mapping reused for scene tracking
- Trusted plate info added to BOTH vision.evidence AND vehicle SceneObject.props
- Scene tracking uses plate_hmac as primary vehicle identity
- Intent history enables cross-camera classification consistency
- Classification happens AFTER all enrichment for maximum accuracy
- Camera_id now tracked in visitor_events for journey analysis

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
    tags TEXT,              -- Space-separated keywords
    UNIQUE(camera_id, track_type, track_key)
);
```

**Cross-Camera Tracking** (ADR-0010):

Scene tracking is inherently per-camera (enforced by UNIQUE constraint), but 
EchoBell provides cross-camera person tracking via `visitor_id`:

```python
# Check if person is active anywhere
is_active = tracker.is_person_active_anywhere(visitor_id="vis_abc123", now_ts=ts)

# Get all cameras currently seeing this person
cameras = tracker.get_person_cameras(visitor_id="vis_abc123", now_ts=ts)
# Returns: [1, 2]  # Person visible on camera 1 and 2

# Get all active visitors across all cameras
visitors = tracker.get_active_visitors_all_cameras(now_ts=ts)
# Returns: {"vis_abc123": [1, 2], "vis_def456": [3]}
```

**Use Cases**:
- **Global presence detection**: "Is family member home?" (any camera)
- **Camera handoff**: Detect person moving between camera views
- **Policy decisions**: Scene-wide notification suppression if known person present
- **Journey tracking**: Monitor visitor path through multi-camera property

**Grace Period Handling**:
- Cross-camera queries respect the same `grace_period_s` (default 6 seconds)
- Person moving from camera 1 → camera 2 during handoff shows on both cameras
- Prevents false "person exited property" during brief camera transitions

### `packages/data/`

#### `plate_service.py` - Plate Visit Management

**Key Functions**:

```python
def upsert_plate_visit(conn, raw_plate_text, camera_id, seen_ts):
    """
    Insert or update plate visit.
    Returns PlateRepeatResult with plate_hmac, is_repeat, visit_count.
    Privacy: stores HMAC, not raw text.
    """

def is_plate_trusted(conn, raw_plate_text):
    """
    Check if a plate is in the trusted_plates table.
    Returns dict with {plate_hmac, label, enabled} or None.
    Used to generate trusted_plate evidence for classification.
    """

def add_trusted_plate(conn, raw_plate_text, label, enabled=True, notes=None):
    """
    Add/update a trusted plate by raw text.
    Stores only plate_hmac + label in trusted_plates table.
    Returns plate_hmac or None if invalid.
    """

def get_plate_intent_history(conn, raw_plate_text, limit=10):
    """
    Lookup past intents for a plate.
    Returns list of {intent, count, avg_conf}.
    Used to boost intent classification for known vehicles.
    """
```

**Privacy Model** (see ADR-00002):
- Raw plate text → SHA256 HMAC with secret salt (via `plate_hmac_hex()`)
- Only HMAC stored in database (both `plate_visitors` and `trusted_plates`)
- Raw text never persisted
- HMAC allows matching without exposing PII
- Trusted plates identified by HMAC, label stored alongside

**Database Tables**:
- `plate_visitors`: All seen plates with visit counts
- `trusted_plates`: Known vehicles (family, delivery services, etc.)
- `visitor_event_plate_sightings`: Links plates to specific events

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

EchoBell's policy engine is a **declarative rule-based system** that translates evidence into actions. Policies can be managed via **YAML files** (for version control) or **REST API** (for dynamic updates).

#### Architecture Overview

```
Evidence Collection → Policy Evaluation → Action Execution
       ↓                      ↓                   ↓
  Vision, OCR,          Match conditions     Telegram, TTS,
  Scene, Trust         against policies      Webhooks, etc.
```

#### `evaluator.py` - Policy Evaluation Engine

**Key Class**: `PolicyEvaluator`

```python
evaluator = PolicyEvaluator(
    conn=conn,
    policy_file="config/policy_rules.yaml",  # Optional, for YAML-based
    use_database=True  # Load from database instead of YAML
)

matches = evaluator.evaluate_all(
    evidence=[...],  # List of Evidence objects
    context={         # Runtime context
        "camera_id": 1,
        "track_key": "plate_abc123",
        "track_duration_seconds": 300,
        "timestamp": 1706112000
    }
)
```

**Returns**: List of `PolicyMatch` objects sorted by priority (highest first)

#### Policy Model

A policy consists of:

1. **Metadata**:
   - `id` - Unique identifier (e.g., "loitering_alert")
   - `name` - Human-readable name
   - `description` - What the policy does
   - `enabled` - Active/inactive flag
   - `priority` - Evaluation order (0-100, higher = first)

2. **Conditions** - Boolean logic tree:
   - `all` (AND) - All conditions must match
   - `any` (OR) - At least one condition must match
   - `not` (NOT) - Condition must NOT match

3. **Actions** - What to execute when conditions match:
   - `telegram` - Send message via Telegram Bot API
   - `speak` - Text-to-speech announcement
   - `webhook` - HTTP request to external service

4. **Variables** (optional) - Dynamic values for message templates

#### Condition Operators

**Evidence Matching**:
- `evidence_exists` - Check if evidence with source/feature exists
- `evidence_missing` - Inverse of evidence_exists
- `evidence_value_eq` - Evidence value equals expected value
- `evidence_value_gt` / `evidence_value_lt` - Numeric comparisons
- `evidence_value_contains` - String substring match

**Trust Checks**:
- `trust_check` - Check if person/vehicle is trusted
  - `check_type: "trusted_person"` - Known individual
  - `check_type: "trusted_plates"` - Known vehicle

**Temporal Conditions**:
- `track_duration_gt` / `track_duration_lt` - How long object has been present
- `time_between` - Current time within window (e.g., "22:00" to "06:00")
- `day_of_week` - Specific days (e.g., ["friday", "saturday"])

**Alert Management**:
- `no_recent_alert` - No alert sent recently (spam prevention)
- `alert_sent_within` - Alert was sent within timeframe (for escalation)

#### Example Policy (YAML)

```yaml
# config/policy_rules.yaml
policies:
  - id: nighttime_loitering_alert
    name: "Nighttime Loitering Alert"
    description: "Alert if unknown person loiters at night (>5 min)"
    enabled: true
    priority: 90
    
    conditions:
      all:  # AND logic
        - time_between:
            start: "22:00"
            end: "06:00"
        - track_duration_gt:
            track_type: person
            duration_s: 300  # 5 minutes
        - not:  # NOT logic
            trust_check:
              check_type: trusted_person
        - no_recent_alert:  # Prevent spam
            track_type: person
            within_seconds: 600
    
    actions:
      - type: telegram
        message: "⚠️ Person loitering for {duration_minutes} min at night"
        priority: urgent
      - type: speak
        text: "You are being recorded. Please leave the premises."
    
    variables:
      duration_minutes: "{db.SELECT CAST((? - first_seen_ts) / 60 AS INTEGER) FROM scene_tracks WHERE track_key = ?}"
```

#### Example Policy (Database/API)

```python
# Via REST API
import requests

policy = {
    "id": "weekend_party_mode",
    "name": "Weekend Party Mode",
    "description": "Reduce alerts on weekend nights",
    "enabled": True,
    "priority": 95,
    "conditions": {
        "all": [
            {"day_of_week": {"days": ["friday", "saturday"]}},
            {"time_between": {"start": "20:00", "end": "02:00"}}
        ]
    },
    "actions": [
        {
            "type": "telegram",
            "message": "🎉 Guest arriving (party mode active)",
            "priority": "low"
        }
    ]
}

response = requests.post(
    "http://localhost:8000/policies/",
    json=policy
)
```

#### `executor.py` - Action Execution

**Key Class**: `ActionExecutor`

Uses a **plugin-based action handler registry** for extensible action execution. Actions are dispatched to registered handlers via `ActionRegistry`.

```python
executor = ActionExecutor(conn=conn)

results = await executor.execute_actions(
    actions=[
        {"type": "telegram", "message": "Alert!", "priority": "urgent"},
        {"type": "speak", "text": "Hello!"},
        {"type": "webhook", "url": "http://...", "method": "POST"}
    ],
    variables={
        "vehicle_color": "white",
        "duration_minutes": "5"
    },
    context={
        "camera_id": 1,
        "track_key": "plate_abc123"
    }
)

# List available actions
print(executor.list_available_actions())
# ['telegram', 'speak', 'webhook', 'log', ...]
```

**Features**:
- **Plugin architecture**: Action handlers are independent classes
- **Auto-discovery**: Handlers register via `@register_action_handler` decorator
- **Extensible**: Add custom actions without modifying core code
- **Variable substitution**: `{variable}` placeholders in messages/payloads
- **Alert history**: Records to `alert_history` table for spam prevention
- **Error handling**: Graceful degradation on action failures

**Architecture**:
```
ActionExecutor → ActionRegistry.get_handler(type) → Handler.execute()
```

See [ACTION_HANDLERS.md](ACTION_HANDLERS.md) for creating custom action handlers.

#### `action_handlers.py` - Action Handler Registry

**Purpose**: Extensible plugin system for policy actions

**Key Components**:

1. **ActionHandler Protocol** - Interface all handlers must implement:
```python
class ActionHandler(Protocol):
    def __init__(self, conn: sqlite3.Connection): ...
    async def execute(self, action, variables, context) -> Dict[str, Any]: ...
```

2. **ActionRegistry** - Global registry mapping action types to handler classes:
```python
@register_action_handler("my_action")
class MyActionHandler:
    async def execute(self, action, variables, context):
        return {"success": True, "action_type": "my_action"}
```

3. **Built-in Handlers**:
   - `telegram` - Send Telegram message via Bot API
   - `speak` - Text-to-speech announcement
   - `webhook` - HTTP request (GET/POST/PUT) to external services
   - `log` - Console logging (for debugging)

4. **Helper Functions**:
   - `substitute_variables(text, vars)` - Replace `{placeholders}`
   - `record_alert_history(...)` - Log to `alert_history` table

**Custom Handler Example**:
```python
from packages.policy.action_handlers import register_action_handler

@register_action_handler("sms")
class SMSActionHandler:
    def __init__(self, conn):
        self.conn = conn
    
    async def execute(self, action, variables, context):
        # Send SMS via Twilio, etc.
        return {"success": True, "action_type": "sms"}
```

See [ACTION_HANDLERS.md](ACTION_HANDLERS.md) for complete documentation and examples.

#### `apply.py` - Integration Layer

**Key Function**: `evaluate_policies()`

```python
from packages.policy.apply import evaluate_policies

# Call after classification
policy_results = await evaluate_policies(
    evidence=vision.evidence,  # All collected evidence
    context={
        "camera_id": camera_id,
        "track_key": track_key,
        "track_duration_seconds": 300,
        "timestamp": int(time.time())
    },
    conn=conn
)

# Returns: List of executed actions with results
```

#### Database Schema

**`policy_rules` table** - Stores policies as JSON:

```sql
CREATE TABLE policy_rules (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    priority INTEGER NOT NULL DEFAULT 50,
    conditions_json TEXT NOT NULL,     -- JSON condition tree
    actions_json TEXT NOT NULL,        -- JSON action array
    variables_json TEXT,               -- JSON variable definitions
    created_ts INTEGER NOT NULL,
    updated_ts INTEGER NOT NULL,
    created_by TEXT DEFAULT 'system',  -- 'api', 'yaml_import', 'user'
    tags TEXT,                         -- Space-separated tags
    version INTEGER DEFAULT 1          -- Optimistic locking
);
```

**`policy_executions` table** - Audit trail:

```sql
CREATE TABLE policy_executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_id TEXT NOT NULL,
    event_id TEXT,
    track_key TEXT,
    track_type TEXT,
    camera_id INTEGER,
    matched_conditions TEXT,    -- JSON: which conditions matched
    executed_actions TEXT,      -- JSON: actions executed
    execution_ts INTEGER NOT NULL,
    success INTEGER DEFAULT 1,
    error_message TEXT,
    FOREIGN KEY(policy_id) REFERENCES policy_rules(id)
);
```

#### Managing Policies

**Option 1: YAML Files** (Version-controlled, deployment-time)

```yaml
# config/policy_rules.yaml
policies:
  - id: my_policy
    name: "My Policy"
    enabled: true
    priority: 80
    conditions: {...}
    actions: [...]
```

**Load YAML policies**:
```python
evaluator = PolicyEvaluator(
    conn=conn,
    policy_file="config/policy_rules.yaml",
    use_database=False  # Use YAML
)
```

**Option 2: REST API** (Dynamic, runtime updates)

```bash
# List policies
curl http://localhost:8000/policies/

# Create policy
curl -X POST http://localhost:8000/policies/ \
  -H "Content-Type: application/json" \
  -d '{...policy JSON...}'

# Update policy
curl -X PATCH http://localhost:8000/policies/my_policy \
  -d '{"enabled": false}'

# Delete policy
curl -X DELETE http://localhost:8000/policies/my_policy
```

**Option 3: Database Service** (Programmatic)

```python
from packages.policy.policy_service import PolicyRulesService

service = PolicyRulesService(db_path="data/echoBell.db")

# Create
service.create_policy(
    policy_id="my_policy",
    name="My Policy",
    conditions={...},
    actions=[...]
)

# Update
service.update_policy(
    policy_id="my_policy",
    enabled=False
)

# Delete
service.delete_policy("my_policy")
```

#### Migration: YAML → Database

```python
# One-time import
from packages.policy.policy_service import PolicyRulesService
import yaml

with open("config/policy_rules.yaml") as f:
    config = yaml.safe_load(f)

service = PolicyRulesService("data/echoBell.db")
service.import_from_yaml(
    yaml_policies=config['policies'],
    overwrite=True  # Update existing
)

# Then switch evaluator to database mode
evaluator = PolicyEvaluator(conn=conn, use_database=True)
```

#### Variable System

Policies support dynamic variables with these sources:

1. **Evidence values**: `{vehicle_color}`, `{plate_text}`, `{confidence}`
2. **Context values**: `{camera_id}`, `{timestamp}`, `{track_key}`
3. **Database queries**: `{db.SELECT COUNT(*) FROM scene_tracks WHERE active=1}`
4. **Environment variables**: `{env.HOME_MODE}`
5. **Calculated values**: `{duration_minutes}` (from track duration)

**Usage in actions**:
```yaml
actions:
  - type: telegram
    message: "Unknown {vehicle_color} {vehicle_type} at camera {camera_id}"
  - type: webhook
    url: "http://home-assistant:8123/api/trigger"
    payload:
      entity: "alert.driveway"
      confidence: "{confidence}"
```

#### Best Practices

1. **Priority Management**:
   - 90-100: Critical/urgent policies (nighttime alerts, security)
   - 70-89: High priority (unknown vehicles, loitering)
   - 50-69: Normal priority (known visitors, deliveries)
   - 10-49: Low priority (informational, logging)

2. **Spam Prevention**:
   - Always use `no_recent_alert` for repeated conditions
   - Set appropriate `within_seconds` thresholds

3. **Escalation Patterns**:
   ```yaml
   # First alert
   - id: loitering_initial
     conditions:
       - track_duration_gt: {duration_s: 300}
       - no_recent_alert: {within_seconds: 600}
   
   # Escalation alert
   - id: loitering_escalation
     conditions:
       - track_duration_gt: {duration_s: 600}
       - alert_sent_within: {within_seconds: 600}  # Previous alert sent
   ```

4. **Testing**:
   - Test policies with sample evidence
   - Use `enabled: false` to disable without deletion
   - Check execution history via API

5. **Version Control**:
   - Store YAML policies in git
   - Use `created_by` field to track origin
   - Monitor `policy_executions` for audit trail

#### API Endpoints

The policy-server exposes these endpoints (see `docs/POLICY_API.md`):

- `GET /policies/` - List all policies
- `POST /policies/` - Create policy
- `PATCH /policies/{id}` - Update policy
- `DELETE /policies/{id}` - Delete policy
- `POST /policies/{id}/enable` - Enable policy
- `POST /policies/{id}/disable` - Disable policy
- `GET /policies/{id}/history` - Execution history
- `POST /policies/import-yaml` - Import from YAML

See **[Policy API Documentation](POLICY_API.md)** for complete reference.

---

## Trust System

EchoBell includes a comprehensive trust system for identifying known vehicles and people to make intelligent policy decisions.

### Trust Registries

#### 1. **Trusted Plates** (`trusted_plates` table)

Identifies known vehicles by license plate HMAC.

```sql
CREATE TABLE trusted_plates (
  plate_hmac   TEXT PRIMARY KEY,      -- Privacy-safe HMAC of plate text
  label        TEXT NOT NULL,         -- "Wife's Car", "Delivery Van", "Neighbor"
  created_ts   INTEGER NOT NULL,
  enabled      INTEGER NOT NULL DEFAULT 1,
  notes        TEXT
);
```

**Usage Flow**:
1. Edge captures vehicle → OCR extracts plate text (e.g., "ABC1234")
2. `plate_service.is_plate_trusted(conn, "ABC1234")` called during evidence enrichment
3. If found: Returns `{plate_hmac: "...", label: "Wife's Car", enabled: True}`
4. Adds evidence: `Evidence("plate_trust", "trusted_plate", "Wife's Car", 1.0)`
5. Policy engine uses this evidence for decisions

**Management**:
```python
# Add trusted plate
plate_service.add_trusted_plate(
    conn, 
    raw_plate_text="ABC1234",
    label="Wife's Car",
    enabled=True,
    notes="2019 Honda Accord, white"
)

# Check if plate is trusted
trust_info = plate_service.is_plate_trusted(conn, "ABC1234")
# Returns: {"plate_hmac": "a3f2...", "label": "Wife's Car", "enabled": True}
```

#### 2. **Trusted People** (`trusted_person` + `trusted_person_embedding` tables)

Identifies known individuals via facial recognition.

```sql
CREATE TABLE trusted_person (
    trusted_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,       -- "John Doe", "Jane Smith"
    label TEXT,                      -- "family", "neighbor", "delivery_driver"
    created_ts INTEGER NOT NULL,
    updated_ts INTEGER,
    active INTEGER DEFAULT 1
);

CREATE TABLE trusted_person_embedding (
    embedding_id INTEGER PRIMARY KEY AUTOINCREMENT,
    trusted_id INTEGER NOT NULL,
    embedding_type TEXT NOT NULL,   -- 'face', 'body'
    model_name TEXT NOT NULL,       -- 'insightface', 'facenet'
    embedding_dim INTEGER NOT NULL,
    embedding_blob BLOB NOT NULL,   -- Serialized embedding vector
    created_ts INTEGER NOT NULL,
    quality_score REAL DEFAULT 1.0,
    FOREIGN KEY (trusted_id) REFERENCES trusted_person(trusted_id)
);
```

**Usage Flow**:
1. Edge captures person → Face recognition extracts embedding
2. Compare embedding against `trusted_person_embedding` table
3. If match found (similarity > threshold): Lookup `trusted_person.name`
4. Adds evidence: `Evidence("face", "visitor_id", "vis_abc123", 0.95)`
5. Cross-reference with `scene_tracks` to track person movement
6. Policy engine knows "family member home" vs "unknown person"

#### 3. **Known Visitors** (`known_visitors` table)

Tracks visitor patterns over time (frequency, recency, behavior).

```sql
CREATE TABLE known_visitors (
    visitor_id TEXT PRIMARY KEY,
    first_seen_ts INTEGER NOT NULL,
    last_seen_ts INTEGER NOT NULL,
    visit_count_total INTEGER NOT NULL DEFAULT 1,
    visit_count_7d INTEGER NOT NULL DEFAULT 1,
    visit_count_30d INTEGER NOT NULL DEFAULT 1,
    confidence_score REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'active',
    intent_last TEXT,
    intent_last_ts INTEGER,
    notes TEXT
);
```

**Usage**: Build behavioral profiles for recurring visitors (e.g., "delivery driver seen 50x in last 30 days").

### Trust Flow in Evidence Enrichment

```
Edge Capture → Vision Detection
    │
    ├─> Vehicle detected + OCR extracts "ABC1234"
    │   └─> _link_plates_to_event()
    │       ├─> upsert_plate_visit() → Record in plate_visitors
    │       ├─> is_plate_trusted("ABC1234") → Check trusted_plates
    │       │   └─> Found: label="Wife's Car"
    │       └─> Add Evidence("plate_trust", "trusted_plate", "Wife's Car", 1.0)
    │
    ├─> Person detected + Face recognition extracts embedding
    │   └─> Face matching against trusted_person_embedding
    │       ├─> Similarity > 0.8 → Match found (trusted_id=5, name="John Doe")
    │       └─> Add Evidence("face", "visitor_id", "vis_john_doe", 0.92)
    │
    └─> Classification with ENRICHED evidence
        ├─> "Wife's Car" + "person_linked.vehicle_plate" → family_arriving
        ├─> Unknown plate + loitering → suspicious_activity
        └─> "Delivery Van" + vehicle_entered → delivery_arriving
```

### Trust-Based Policy Examples

**Policy 1: Unknown Vehicle Alert**
```python
# Condition: Vehicle detected, plate NOT in trusted_plates
if vehicle_present and not trusted_plate_evidence:
    actions = ["telegram_alert", "speak_greeting"]
    message = f"Unknown {color} {vehicle_type} pulled up"
```

**Policy 2: Trusted Person Silent Entry**
```python
# Condition: Person with visitor_id matching trusted_person
if visitor_id in trusted_person_ids:
    actions = ["telegram_notification"]  # Quiet notification only
    message = f"{person_name} arrived home"
    speak = False  # Don't announce arrival
```

**Policy 3: Delivery Van Recognition**
```python
# Condition: Plate matches trusted_plates with label="Delivery Van"
if trusted_plate_label == "Delivery Van":
    actions = ["speak_instruction"]
    message = "Please leave package by the door. Thank you!"
```

### Privacy Guarantees

- **Plate HMACs**: Raw plate text never stored, only HMAC
- **Face Embeddings**: Raw images not saved, only embedding vectors
- **Trust Labels**: Human-readable labels for known entities
- **Revocability**: Can disable trusted entries (`enabled=0`) without deletion

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
    camera_id INTEGER,                -- Which camera detected this event
    FOREIGN KEY(visitor_id) REFERENCES visitors(visitor_id),
    FOREIGN KEY(camera_id) REFERENCES camera(id)
);
```

**Purpose**: Tracks visitor journey across cameras, enables cross-camera analysis.

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
    tags TEXT,                        -- Space-separated keywords (e.g., "suspicious loitering")
    UNIQUE(camera_id, track_key)
);
```

**Tags Field** (Future Expansion):
- Space-separated keywords for track classification
- Examples: `"suspicious loitering"`, `"expected delivery"`, `"priority vip"`, `"trusted neighbor"`
- Can be set via `SceneTracker.update_tags(conn, track_id=..., tags="...")`
- Enables filtering and querying by behavioral/contextual markers


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

#### `trusted_plates`
Known vehicles for trust-based policy decisions.

```sql
CREATE TABLE trusted_plates (
    plate_hmac TEXT PRIMARY KEY,      -- Privacy-safe HMAC
    label TEXT NOT NULL,              -- "Wife's Car", "Delivery Van"
    created_ts INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    notes TEXT
);
```

#### `trusted_person`
Known individuals for facial recognition.

```sql
CREATE TABLE trusted_person (
    trusted_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    label TEXT,                       -- "family", "neighbor", "delivery_driver"
    created_ts INTEGER NOT NULL,
    updated_ts INTEGER,
    active INTEGER DEFAULT 1
);
```

#### `alert_history`
Tracks alerts sent to prevent spam and enable escalation.

```sql
CREATE TABLE alert_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id TEXT NOT NULL,
    track_key TEXT NOT NULL,          -- plate_hmac, visitor_id, or temp UUID
    track_type TEXT NOT NULL,         -- 'vehicle' or 'person'
    policy_id TEXT,                   -- Which policy triggered alert
    alert_type TEXT NOT NULL,         -- 'telegram', 'speak', 'sms', 'webhook'
    message TEXT,
    priority TEXT DEFAULT 'normal',   -- 'low', 'normal', 'urgent'
    sent_ts INTEGER NOT NULL,
    success INTEGER DEFAULT 1,
    error_message TEXT,
    FOREIGN KEY(camera_id) REFERENCES camera(id)
);
```

**Usage Example**:
```python
# Check if alerted recently (within 5 minutes)
recent_alert = conn.execute("""
    SELECT sent_ts FROM alert_history
    WHERE track_key = ? AND track_type = 'person'
    AND sent_ts > ?
    ORDER BY sent_ts DESC LIMIT 1
""", (track_key, now_ts - 300)).fetchone()

if recent_alert:
    # Escalate: "Still here after 5 minutes"
    send_urgent_alert()
```

### Indexes

```sql
-- Performance indexes
CREATE INDEX idx_veps_event ON visitor_event_plate_sightings(event_id);
CREATE INDEX idx_veps_plate ON visitor_event_plate_sightings(plate_hmac);
CREATE INDEX idx_scene_tracks_camera_active ON scene_tracks(camera_id, active);
CREATE INDEX idx_scene_tracks_type ON scene_tracks(track_type);
CREATE INDEX idx_alert_history_track_time ON alert_history(track_key, track_type, sent_ts DESC);
CREATE INDEX idx_trusted_plates_enabled ON trusted_plates(enabled);
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
    "gap_between_visits_seconds": 3600,
    "intent_persistence_window_s": 3600,  // Cross-camera intent persistence (1 hour)
    "scene_tracking_grace_period_s": 6     // Grace period for scene tracking (seconds)
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

## Integrations

### Telegram Notifications

**Location**: `packages/integrations/telegram.py`

EchoBell supports sending alerts and snapshots to Telegram via the Bot API.

**Setup**:

1. **Create a Telegram bot**:
   - Message [@BotFather](https://t.me/BotFather) on Telegram
   - Use `/newbot` command and follow instructions
   - Save the bot token (e.g., `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`)

2. **Get your chat ID**:
   - Message [@userinfobot](https://t.me/userinfobot)
   - It will reply with your user ID
   - For groups: Add bot to group, then use `https://api.telegram.org/bot<TOKEN>/getUpdates`

3. **Configure environment variables**:
   ```bash
   # PowerShell
   $env:TELEGRAM_BOT_TOKEN = "your_bot_token_here"
   $env:TELEGRAM_CHAT_ID = "your_chat_id_here"
   $env:TELEGRAM_ENABLED = "true"  # Optional, defaults to true
   
   # Linux/Mac
   export TELEGRAM_BOT_TOKEN="your_bot_token_here"
   export TELEGRAM_CHAT_ID="your_chat_id_here"
   ```

**Usage**:

```python
from packages.integrations.telegram import load_telegram_config, TelegramNotifier

# Load config from environment
config = load_telegram_config()
if config:
    notifier = TelegramNotifier(config)
    
    # Send text message
    notifier.send_message("🚨 Urgent delivery at front door!")
    
    # Send photo with caption
    notifier.send_photo(
        photo_path="snapshots/event_123.jpg",
        caption="Delivery person detected"
    )
```

**Features**:
- **Automatic retry** on rate limits (429 errors)
- **Configurable timeout** (default 10s)
- **Enable/disable** via environment variable
- **Graceful degradation** if not configured

**Testing**:

```bash
# Set credentials
$env:TELEGRAM_BOT_TOKEN = "your_token"
$env:TELEGRAM_CHAT_ID = "your_chat_id"

# Run integration test
pytest tests/test_telegram_integration.py -v -s
```

See `tests/test_telegram_integration.py` for examples.

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
- [Policy API Reference](POLICY_API.md) - REST API for dynamic policy management
- [Policy Integration Summary](POLICY_INTEGRATION_SUMMARY.md) - Setup guide and examples
- [Policy Reference](POLICY_REFERENCE.md) - Condition operators and policy syntax quick reference
- [Action Handlers](ACTION_HANDLERS.md) - Creating custom action handlers (plugin system)
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

**Policy**: Declarative rule that maps conditions (evidence patterns) to actions

**Condition**: Boolean expression evaluated against evidence (e.g., `evidence_exists`, `time_between`)

**Action**: Executable response when policy conditions match (telegram, speak, webhook)

**HMAC**: Hash-based Message Authentication Code (privacy-safe plate identifier)

**IoU**: Intersection over Union (bounding box overlap metric)

**Visitor**: Known person with stored face embedding and visit history

**Event**: Single detection occurrence (may or may not have visitor_id)

**Scene**: Current state of all tracked objects in camera view

**Trust**: System for identifying known vehicles (plates) and people (faces) for policy decisions

**Escalation**: Policy pattern where repeated conditions trigger increasingly urgent actions

---

**End of Architecture Document**

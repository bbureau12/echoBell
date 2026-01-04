# ADR-0010: Cross-camera person tracking via visitor_id

Date: 2026-01-03  
Status: Accepted

## Context

EchoBell's `SceneTracker` maintains temporal state of objects (vehicles, people) 
across video frames to detect arrivals/departures and generate scene evidence. 
The `scene_tracks` table enforces per-camera tracking:

```sql
CREATE TABLE scene_tracks (
    ...
    camera_id INTEGER,
    track_type TEXT,        -- 'vehicle' | 'person'
    track_key TEXT,         -- visitor_id or plate_hmac
    ...
    UNIQUE(camera_id, track_type, track_key)
);
```

This design works well for single-camera scenarios:
- Person appears on camera 1 → `scene.person_entered` evidence generated
- Person exits camera 1 view → `scene.person_exited` after grace period
- Vehicle arrives → tracked by `plate_hmac`, vehicle-person linkage created

**Problem**: Multi-camera properties need **global presence detection**:

### Scenario 1: Camera handoff detection
A family member walks from driveway (camera 1) to front door (camera 2):
- Camera 1: Person detected, `visitor_id = vis_abc123`
- Camera 2: Same person detected 10 seconds later, ReID matches → same `visitor_id`
- **Question**: "Is this person currently active anywhere on the property?"
- **Per-camera tracking limitation**: Must query each camera separately

### Scenario 2: Scene-wide policy decisions
Policy rule: "Suppress visitor notifications if any known family member is present on property"
- Family member detected on camera 3 (garage)
- Delivery person approaches camera 1 (front door)
- **Need**: Check if ANY camera sees a known person before sending notifications
- **Current limitation**: No single query for "is person X active anywhere?"

### Scenario 3: Real-time property inventory
Get a snapshot of all people currently visible on the property:
- "Who is on the property right now?"
- "How many people are currently visible across all cameras?"
- "Which cameras can see person X?"
- **Need**: Global visitor inventory showing all active people and their locations
- **Current limitation**: Must manually query and aggregate each camera's tracks

The fundamental issue: `visitor_id` provides **identity continuity** across cameras 
(via ReID facial embeddings), but scene tracking is **per-camera only**. There's 
no built-in way to query "is visitor X active on ANY camera?"

## Decision

Add three new cross-camera query methods to `SceneTracker` that aggregate 
person tracking across all cameras using `visitor_id` as the key:

### 1. `is_person_active_anywhere(visitor_id, now_ts)`

Check if a person is currently active on ANY camera:

```python
is_active = tracker.is_person_active_anywhere(
    visitor_id="vis_abc123",
    now_ts=time.time()
)
# Returns: True if person is active on any camera, False otherwise
```

**SQL Implementation**:
```sql
SELECT 1 FROM scene_tracks
WHERE track_type = 'person'
  AND track_key = ?  -- visitor_id
  AND active = 1
  AND last_seen_ts >= ?  -- now_ts - grace_period_s
LIMIT 1
```

**Use case**: Policy decisions, presence detection

### 2. `get_person_cameras(visitor_id, now_ts)`

Get list of all cameras currently seeing a person:

```python
cameras = tracker.get_person_cameras(
    visitor_id="vis_abc123",
    now_ts=time.time()
)
# Returns: [1, 2] if person visible on cameras 1 and 2
# Returns: [] if person not active anywhere
```

**SQL Implementation**:
```sql
SELECT camera_id FROM scene_tracks
WHERE track_type = 'person'
  AND track_key = ?  -- visitor_id
  AND active = 1
  AND last_seen_ts >= ?  -- now_ts - grace_period_s
ORDER BY camera_id
```

**Use case**: Journey tracking, camera handoff detection

### 3. `get_active_visitors_all_cameras(now_ts)`

Get mapping of all active visitors to their camera locations:

```python
visitors = tracker.get_active_visitors_all_cameras(now_ts=time.time())
# Returns: {
#     "vis_abc123": [1, 2],  # Visible on cameras 1 and 2
#     "vis_def456": [3]       # Visible on camera 3 only
# }
```

**SQL Implementation**:
```sql
SELECT track_key, camera_id FROM scene_tracks
WHERE track_type = 'person'
  AND active = 1
  AND last_seen_ts >= ?  -- now_ts - grace_period_s
ORDER BY track_key, camera_id
```

**Use case**: Scene-wide presence overview, multi-visitor tracking

## Implementation Details

### Grace Period Consistency

All cross-camera methods respect the same `grace_period_s` used for single-camera 
tracking (default: 6 seconds). This enables **camera handoff detection**:

```python
# T+0s: Person on camera 1
tracker.update_from_vision(camera_id=1, vision=..., now_ts=100)
tracker.get_person_cameras("vis_123", 100)  # [1]

# T+3s: Person appears on camera 2 (during handoff)
tracker.update_from_vision(camera_id=2, vision=..., now_ts=103)
tracker.get_person_cameras("vis_123", 103)  # [1, 2] - both cameras

# T+8s: Person on camera 2 only (camera 1 expired after grace period)
tracker.get_person_cameras("vis_123", 108)  # [2]
```

The grace period prevents false "person exited property" events during brief 
camera transitions.

### Database Schema (unchanged)

The `UNIQUE(camera_id, track_type, track_key)` constraint remains:
- Same person can have ONE track per camera (prevents duplicate entries)
- Different cameras can track same person simultaneously (enables handoff)
- Cross-camera methods aggregate via GROUP BY or multiple row results

No schema migration required - feature uses existing table structure.

### visitor_id as Strong Key

Person tracking uses `visitor_id` (from ReID) as the `track_key`:
- **Vehicles**: `track_key = plate_hmac` (per-camera only, vehicles don't move between cameras)
- **People**: `track_key = visitor_id` (cross-camera tracking via ReID)
- **Fallback**: IoU-based matching assigns temporary UUID (per-camera only)

Only people with `visitor_id` (successful ReID match) support cross-camera queries.

## Consequences

### Pros

1. **Simple API**: Three methods cover all cross-camera use cases
2. **Backward compatible**: Existing per-camera tracking unchanged
3. **No schema changes**: Uses existing `scene_tracks` table structure
4. **Grace period aware**: Consistent temporal semantics across all queries
5. **Testable**: Easily verified with synthetic data (no camera hardware needed)
6. **Performance**: Simple SQL queries with indexed lookups

### Cons

1. **People only**: Cross-camera tracking requires `visitor_id` from ReID
   - Vehicles tracked per-camera only (reasonable - vehicles don't teleport)
   - People without face matches (IoU-only) remain per-camera
2. **No journey history**: Returns current state, not historical path
   - Could add `get_visitor_journey()` in future if needed
3. **Database dependency**: All cross-camera state in SQLite
   - Fine for single-node deployment, would need rethinking for distributed

### Security & Privacy

- **No new PII**: Uses existing `visitor_id` (already privacy-sensitive)
- **No face image storage**: Cross-camera tracking uses embeddings only
- **Audit trail**: All tracking events logged with timestamps
- **Configurable retention**: Grace period limits temporal window

### Use Cases Enabled

1. **Policy engine**: "Suppress notifications if family home"
   ```python
   for visitor_id in known_family_visitor_ids:
       if tracker.is_person_active_anywhere(visitor_id, now_ts):
           return suppress_notification  # Family home, don't alert
   ```

2. **Journey analysis**: "Track visitor path through property"
   ```python
   cameras = tracker.get_person_cameras(visitor_id, now_ts)
   if 1 in cameras and 3 in cameras:
       logger.info("Visitor moved from driveway to front door")
   ```

3. **Scene-wide presence**: "Who's on the property right now?"
   ```python
   visitors = tracker.get_active_visitors_all_cameras(now_ts)
   total_people = len(visitors)
   camera_coverage = max(len(cams) for cams in visitors.values())
   ```

## Testing Strategy

Created `tests/test_cross_camera_tracking.py` with 16 tests covering:

1. **Single camera tracking** (baseline)
2. **Cross-camera person tracking** (camera handoff scenarios)
3. **Multiple visitors, multiple cameras** (scene-wide aggregation)
4. **Grace period behavior** (temporal edge cases)
5. **Edge cases** (no visitor_id, expired tracks, single visitor multi-camera)

All tests use synthetic data (bounding boxes, visitor IDs, timestamps) - no 
camera hardware or face images required.

## Example Usage

See `examples/cross_camera_tracking_usage.py` for comprehensive demonstration:

```python
from packages.scene.scene_tracker import SceneTracker
from packages.perception.vision import Vision, SceneObject
import time

tracker = SceneTracker()
ts = time.time()

# Scenario 1: Person on camera 1
vision = Vision(objects=[
    SceneObject(object_id="1", label="person", box=[100,100,200,200],
                props={"visitor_id": "vis_family_001"})
])
tracker.update_from_vision(camera_id=1, vision=vision, now_ts=ts)

# Check presence
is_active = tracker.is_person_active_anywhere("vis_family_001", ts)
cameras = tracker.get_person_cameras("vis_family_001", ts)
print(f"Family member active: {is_active}, cameras: {cameras}")
# Output: Family member active: True, cameras: [1]

# Scenario 2: Camera handoff (person moves to camera 2)
vision2 = Vision(objects=[
    SceneObject(object_id="2", label="person", box=[150,150,250,250],
                props={"visitor_id": "vis_family_001"})
])
tracker.update_from_vision(camera_id=2, vision=vision2, now_ts=ts+3)

cameras = tracker.get_person_cameras("vis_family_001", ts+3)
print(f"During handoff, cameras: {cameras}")
# Output: During handoff, cameras: [1, 2]

# Scenario 3: Scene-wide presence
all_visitors = tracker.get_active_visitors_all_cameras(ts+3)
print(f"All visitors: {all_visitors}")
# Output: All visitors: {'vis_family_001': [1, 2]}

# Policy decision
if tracker.is_person_active_anywhere("vis_family_001", ts+3):
    print("Family member home - suppress visitor notification")
```

## Alternatives Considered

### Alternative 1: Camera-agnostic tracking (rejected)

Remove `camera_id` from UNIQUE constraint, track globally:
```sql
UNIQUE(track_type, track_key)  -- No camera_id
```

**Rejected because**:
- Breaks per-camera scene state (can't track person on camera 1 AND camera 2)
- Would need complex "last seen camera" logic
- Loses camera handoff detection capability

### Alternative 2: Separate cross-camera tracking table (rejected)

Create `visitor_global_presence` table:
```sql
CREATE TABLE visitor_global_presence (
    visitor_id TEXT PRIMARY KEY,
    cameras TEXT,  -- JSON array: [1, 2, 3]
    last_seen_ts INTEGER
);
```

**Rejected because**:
- Duplicates data from `scene_tracks`
- Requires complex synchronization logic
- More code, more failure modes
- Cross-camera methods can derive this via simple SQL GROUP BY

### Alternative 3: In-memory aggregation layer (rejected)

Keep per-camera tracking in DB, aggregate in Python:
```python
def is_person_active_anywhere(visitor_id):
    for camera_id in all_cameras:
        if tracker.is_person_active(camera_id, visitor_id):
            return True
    return False
```

**Rejected because**:
- Slower (N camera queries vs 1 cross-camera query)
- Requires maintaining camera list
- SQL is designed for aggregation - use it

## Future Enhancements

1. **Journey history**: Add `get_visitor_journey(visitor_id, time_window)` 
   - Return ordered list of cameras visited
   - Enable path analysis: "Most common entry point?"

2. **Multi-person scene analysis**: 
   - "How many people in driveway area?" (cameras 1, 2, 3)
   - Group cameras into zones, count active visitors per zone

3. **Vehicle cross-camera tracking**:
   - If plate visible on multiple cameras (large property)
   - Currently per-camera only (reasonable default)

## References

- ADR-0007: Cross-camera intent persistence via visitor history
- ADR-0006: Scene awareness entity association (person-vehicle linkage)
- ADR-0005: Scene awareness temporal tracking (SceneTracker design)
- `packages/scene/scene_tracker.py`: Implementation
- `tests/test_cross_camera_tracking.py`: Test suite (16 tests)
- `examples/cross_camera_tracking_usage.py`: Usage examples

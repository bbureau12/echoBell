# Scene Context for Policy Evaluation

## Problem Statement

**Scenario**: AC technician arrives and stays for an hour. 40 minutes later, fire department shows up.

**Challenge**: How do policies detect "authority arrived WHILE technician present"?

## Solution: Scene Context Queries

### Design Decision

**Keep event-per-arrival** (simple, clean) BUT **query scene state** for policy evaluation.

```
Event 1 (T+0:00): technician_visit, urgency=30
Event 2 (T+0:40): authority_urgent, urgency=90

Scene State (T+0:40):
  - Vehicle 1: technician_visit (active)
  - Vehicle 2: authority_urgent (active)
  
Policy sees BOTH → ESCALATE
```

### Implementation

Created `packages/scene/scene_context.py` with three key functions:

#### 1. `get_active_scene_intents()`

Gets all intents for entities **currently present** (within grace period):

```python
active_intents = get_active_scene_intents(
    conn,
    camera_id=1,
    now_ts=now_ts,
)

# Returns:
[
    ActiveIntent(
        intent='authority_urgent', 
        urgency=90, 
        camera_id=1,
        track_type='vehicle',
        ...
    ),
    ActiveIntent(
        intent='technician_visit', 
        urgency=30,
        camera_id=1,
        track_type='vehicle',
        ...
    )
]
```

#### 2. `get_scene_urgency_level()`

Returns highest urgency + description:

```python
urgency, desc, intents = get_scene_urgency_level(conn, camera_id=1, now_ts=now_ts)

# Returns:
# (90, "URGENT: Authority Urgent", ["authority_urgent", "technician_visit"])

# OR for normal scenes:
# (30, "normal", ["technician_visit"])

# OR for complex scenes:
# (40, "COMPLEX: 3 concurrent visitors", [...])
```

#### 3. `check_concurrent_intents()`

Checks if specific intents are **simultaneously active**:

```python
is_escalation = check_concurrent_intents(
    conn,
    camera_id=1,
    now_ts=now_ts,
    required_intents=["authority_urgent", "technician_visit"],
)

# Returns: True (both are present)
```

### How It Works

```sql
-- Joins scene_tracks (who's present) with visitor_events (their intents)

SELECT ve.intent_inferred, ve.urgency, ve.camera_id, st.track_key, st.track_type
FROM scene_tracks st
LEFT JOIN visitor_event_plate_sightings veps ON st.track_key = veps.plate_hmac
LEFT JOIN visitor_events ve ON veps.event_id = ve.event_id
WHERE st.camera_id = ?
  AND st.active = 1
  AND st.last_seen_ts >= ?  -- Within grace period (6 seconds)
  AND ve.intent_inferred IS NOT NULL
```

**Key insight**: Scene tracks persist WHO'S THERE, events record WHAT THEY WANT, camera_id tracks WHERE.

### Policy Example

```python
from packages.scene.scene_context import get_active_scene_intents, check_concurrent_intents

def evaluate_policy(conn, camera_id, now_ts):
    # Get current scene state
    active_intents = get_active_scene_intents(conn, camera_id, now_ts)
    
    # Rule: Authority + anyone else = escalate
    if check_concurrent_intents(conn, camera_id, now_ts, 
                                 ["authority_urgent", "technician_visit"]):
        return {
            "action": "ESCALATE_IMMEDIATELY",
            "reason": "Fire dept arrived while technician on site",
            "urgency": 95,
        }
    
    # Rule: Multiple service providers = notify
    service_count = sum(1 for ai in active_intents 
                       if ai.intent in ["technician_visit", "delivery", "maintenance"])
    if service_count > 1:
        return {
            "action": "NOTIFY",
            "reason": f"{service_count} service providers on site",
            "urgency": 40,
        }
    
    # Normal case
    return {"action": "LOG", "urgency": max(ai.urgency for ai in active_intents)}
```

## Benefits

✅ **Simple event model**: One event per arrival (no merging/updating)  
✅ **Scene awareness**: Policies see complete current state  
✅ **Concurrent intents**: Detect "A + B both present"  
✅ **Temporal reasoning**: "High urgency arrived WHILE low urgency present"  
✅ **No refactoring**: Works with existing classify_and_log flow  

## Usage in Your Scenario

```python
# T+0:00 - Technician arrives
classify_and_log(...)  # Creates event_1: technician_visit

# T+0:40 - Fire dept arrives  
classify_and_log(...)  # Creates event_2: authority_urgent

# Policy evaluation:
policy = evaluate_policy(conn, camera_id=1, now_ts=now)

# Result:
{
    "action": "ESCALATE_IMMEDIATELY",
    "reason": "Fire department arrived while technician on site",
    "notify": ["homeowner", "emergency_contact"],
    "urgency": 95
}
```

## Files Created

- `packages/scene/scene_context.py` - Core scene query functions
- `examples/scene_context_usage.py` - Example policy using scene context

## Next Steps

1. **Integrate into policy engine**: Update `packages/policy/apply.py` to use scene context
2. **Add to orchestrator**: Call `get_scene_urgency_level()` after classify_and_log
3. **Create policy rules**: Define specific concurrent intent combinations
4. **Add tests**: Test multi-entity scenarios

## Cross-Camera Intent Persistence

**Problem**: Person exits fire truck at camera 1 (driveway), then walks to camera 2 (front door). Should they still be classified as "authority_urgent" at the door?

**Solution**: Visitor intent history enrichment (PHASE 1d in `classify_and_log.py`)

### Implementation

When classifying a person at **any camera**, check their recent intent history:

```python
# In classify_and_log.py PHASE 1d
_add_visitor_intent_history(
    conn,
    vision=vision,
    now_ts=now_ts,
    intent_persistence_window_s=retention.intent_persistence_window_s,  # Default: 3600s = 1 hour
)
```

### How It Works

1. **Camera 1 (Driveway) - T+0:00**:
   - Fire truck + person detected together
   - Person-vehicle link created (same-camera proximity)
   - Intent classified: `"authority_urgent"` (person linked to fire truck)
   - `visitor_id` assigned via ReID: `"vis_abc123"`
   - Event stored in database

2. **Camera 2 (Front Door) - T+0:20** (20 seconds later):
   - Person detected at door
   - ReID matches face → SAME `visitor_id = "vis_abc123"`
   - **Intent history query**: Find most recent intent for this visitor_id
   - Result: `"authority_urgent"` (20 seconds ago, within 1-hour window)
   - Evidence added: `visitor_history.recent_intent = "authority_urgent"`
   - Classification: Authority at door (intent persisted!)

### Configuration

Set in `RetentionSettings`:

```python
from packages.common.config_models import RetentionSettings

retention = RetentionSettings(
    intent_persistence_window_s=3600  # 1 hour (default)
)
```

**Time window reasoning**:
- **Too short** (e.g., 60s): Person might walk slowly, intent lost
- **Too long** (e.g., 24 hours): Off-duty return gets stale intent
- **1 hour**: Reasonable for "same visit" across multiple cameras

### Audit Trail

Even though intent is carried forward, **full evidence chain is preserved**:

```sql
-- Trace why person was flagged as authority at door
SELECT ve.event_id, ve.camera_id, ve.intent_inferred, ve.detected_ts, vel.relation, vel.object_key
FROM visitor_events ve
LEFT JOIN visit_entity_links vel ON ve.event_id = vel.visit_id
WHERE ve.visitor_id = 'vis_abc123'
ORDER BY ve.detected_ts;

-- Results:
-- event_A | camera_1 | authority_urgent | 2024-01-01 09:00:00 | arrived_with_vehicle | plate:FIRE123...
-- event_B | camera_2 | authority_urgent | 2024-01-01 09:00:20 | NULL                 | NULL
```

You can always trace back: "Person at door (camera 2) was linked to fire truck at driveway (camera 1) 20 seconds earlier."

## Alternative: Event-Level Metadata (Not Recommended)

You could add scene metadata to events:

```python
event.scene_complexity = len(active_tracks)
event.concurrent_intents = ["technician_visit"]  # others already present
```

**Why we didn't do this**:
- Duplicates data (scene_tracks already has this)
- Harder to query ("show me all active intents")
- Event creation time != scene query time
- Would need to update old events when new entities arrive

**Scene context queries** are cleaner and more flexible.

## Future: Scene Track Tags

The `scene_tracks` table now includes a `tags` field for future expansion.

### Purpose
Allow policies to mark tracks with behavioral/contextual labels:

```python
# After detecting suspicious behavior
tracker.update_tags(conn, track_id=123, tags="suspicious loitering")

# After recognizing expected visitor
tracker.update_tags(conn, track_id=456, tags="expected delivery priority")

# Clearing tags
tracker.update_tags(conn, track_id=789, tags=None)
```

### Use Cases
- **Behavioral tracking**: Mark tracks that linger too long, return frequently, etc.
- **Priority handling**: Tag VIP visitors or emergency services
- **Trust levels**: Mark trusted neighbors, known delivery personnel
- **State management**: Track "awaiting_response", "engaged_conversation", etc.

### Query Examples
```sql
-- Find all suspicious tracks
SELECT * FROM scene_tracks 
WHERE active=1 AND tags LIKE '%suspicious%';

-- Find priority/VIP tracks
SELECT * FROM scene_tracks 
WHERE active=1 AND tags LIKE '%priority%';
```

### Implementation Notes
- Tags are **space-separated keywords** (e.g., `"suspicious loitering"`)
- **Not hierarchical** (no namespacing yet)
- **Nullable** (most tracks won't have tags)
- Can be updated at any time via `SceneTracker.update_tags()`
- Consider future structured format (JSON) if complexity grows

## Package Tracking & Person Linkage

The system now tracks packages and automatically links them to people when packages **first appear inside a person's bounding box**.

### Constraints

**Package must be NEW** - Only linked when first_seen_ts is within 3 seconds (configurable)

**Package must be INSIDE person bbox** - All four corners of package bbox must be within person bbox

**Package must be SMALLER** - Package area must be less than person area (prevents false positives)

### Use Cases

**Delivery Detection**:
```python
# Person arrives WITH package (carrying_package link exists)
# → Classified as "delivery_person"

# Person arrives WITHOUT package, picks up existing package
# → No carrying_package link
# → Classified as "porch_pirate"
```

**Evidence Generated**:
```python
Evidence("scene", "link.carrying_package", "package:42", conf=0.85, object_id=person_id)
Evidence("scene", "link_conf.carrying_package", "0.850", conf=1.0, object_id=person_id)
```

### Confidence Calculation

```python
containment = intersection_area(pkg_box, person_box) / pkg_area
final_conf = containment * person_detector_conf * package_detector_conf
```

Higher confidence when:
- Package is well-centered inside person bbox
- Both detectors have high confidence
- Package size is reasonable relative to person

### Database Schema

Packages stored in `scene_tracks`:
```sql
track_type = 'package'
key_kind = 'iou'          -- No stable key (like temp person tracks)
track_key = 'temp:UUID'   -- Temporary UUID
```

Links stored in `visit_entity_links`:
```sql
relation = 'carrying_package'
subject_type = 'person'
object_type = 'package'
confidence = 0.0-1.0
```

### Future Enhancements

- Track package **state changes** (picked_up, put_down, stolen)
- Multi-frame tracking (verify package stays with person)
- Package size estimation (small_box, large_box, envelope)
- Package direction tracking (arriving_with vs leaving_with)

## Package Pickup Detection

The system now detects when someone **picks up a package that was already on the ground**, distinguishing between delivery and theft scenarios.

### Detection Logic

**3-Stage Process**:

1. **Package existed BEFORE person** - Package first_seen_ts < Person first_seen_ts
2. **Package enters person's bbox** - Package becomes fully contained
3. **Dwell time threshold** - Package stays in bbox for 2+ seconds

### State Tracking via Tags

The system uses `scene_tracks.tags` to track containment state:

```python
# First frame: Package enters person bbox
tags = "contained_by:visitor_abc123 contained_since:1735689234"

# Subsequent frames: Check dwell time
dwell_time = now_ts - contained_since
if dwell_time >= 2:
    # PICKUP DETECTED!
    create_link(relation="picked_up_package")
```

### Use Cases

**Scenario 1: Delivery Person**
```python
# Person arrives WITH package (t=0)
→ Package first_seen = 0, Person first_seen = 0
→ Package DOES NOT predate person
→ Relation: "carrying_package" (NOT picked_up_package)
→ Intent: "delivery_person"
```

**Scenario 2: Porch Pirate**
```python
# Package left at door (t=0)
# Person arrives (t=60)
# Person approaches, package enters bbox (t=65)
# Package remains in bbox (t=67, 2s dwell)
→ Package first_seen = 0 < Person first_seen = 60
→ Dwell time = 2+ seconds
→ Relation: "picked_up_package"
→ Intent: "porch_pirate" or "suspicious"
```

**Scenario 3: Homeowner Retrieving Package**
```python
# Package left at door (t=0)
# Homeowner arrives (t=120)
# Homeowner picks up package (t=122)
→ Package predates person
→ Relation: "picked_up_package"
→ But visitor_id matches trusted_person
→ Intent: "resident_return" (not suspicious)
```

### Evidence Generated

```python
# Initial carrying (delivery)
Evidence("scene", "link.carrying_package", "package:42", conf=0.85, object_id=person_id)

# Pickup detection (potential theft)
Evidence("scene", "link.picked_up_package", "package:42", conf=0.78, object_id=person_id)
Evidence("scene", "link_conf.picked_up_package", "0.780", conf=1.0, object_id=person_id)
```

### Confidence Calculation

```python
containment = intersection_area(pkg, person) / pkg_area
time_factor = min(1.0, dwell_time / (min_dwell * 2))  # Caps at 2x threshold
final_conf = containment * person_conf * pkg_conf * time_factor
```

Higher confidence when:
- Package well-centered in person bbox
- Person stable (not just walking past)
- Longer dwell time = more intentional action
- High detector confidences

### Metadata Stored

```sql
-- visit_entity_links table
relation = 'picked_up_package'
object_meta_json = {
    "package_age_s": 120,        -- Package was there 2 minutes
    "dwell_time_s": 3,           -- Held for 3 seconds
    "containment": 0.92          -- Well-contained in bbox
}
subject_meta_json = {
    "person_age_s": 7,           -- Person appeared 7s ago
    "person_conf": 0.95
}
```

### Classification Rules

**Intent Classifier can now detect**:

```python
# Delivery scenario
if has_evidence("link.carrying_package"):
    intent = "delivery_person"

# Theft scenario  
elif has_evidence("link.picked_up_package") and not is_trusted(visitor_id):
    intent = "porch_pirate"

# Homeowner retrieving own package
elif has_evidence("link.picked_up_package") and is_trusted(visitor_id):
    intent = "resident_return"
```

### Implementation Notes

- **Dwell time** prevents false positives from people just walking past
- **Package age check** ensures we don't flag delivery people as thieves
- **Tags persistence** tracks containment across frames without extra tables
- **Multi-frame tracking** naturally emerges from scene_tracker updates
- **Cleanup** happens when person exits (scene_tracker marks inactive)

## Package Drop-Off Detection

The system detects when someone **drops off a package** (delivery scenario) by tracking separation events.

### Detection Logic

**3-Stage Process**:

1. **Package was being carried** - Has "carrying_package" link from initial detection
2. **Package separates from person** - Exits person's bounding box
3. **Separation persists** - Package stays outside bbox for 2+ seconds

### State Tracking via Tags

```python
# Initially: Package in person bbox
tags = ""  # or previous state

# First frame: Package exits person bbox
tags = "separated_from:visitor_abc123 separated_since:1735689234"

# Subsequent frames: Check separation time
separation_time = now_ts - separated_since
if separation_time >= 2:
    # DROP-OFF DETECTED!
    create_link(relation="dropped_off_package")
```

### Scenarios

**Scenario 1: Delivery Person**
```python
# Person arrives WITH package (t=0)
→ Link created: "carrying_package"

# Person walks to door (t=5)
→ Package still in bbox, no change

# Person sets down package (t=8)
→ Package exits bbox
→ Tags: "separated_from:visitor_abc separated_since:8"

# Package remains on ground (t=10, 2s separation)
→ Link created: "dropped_off_package"
→ Intent: "delivery_person" (both carrying + dropped_off)
```

**Scenario 2: Person Just Holding Package**
```python
# Person arrives WITH package (t=0)
→ Link: "carrying_package"

# Person adjusts grip, package briefly outside bbox (t=3)
→ Tags: "separated_from:visitor_abc separated_since:3"

# Person still holding, package back in bbox (t=4)
→ Tags cleared (< 2s separation)
→ No drop-off link (temporary separation)
```

**Scenario 3: Person Leaves After Delivery**
```python
# Person drops package (t=10)
→ Link: "dropped_off_package"

# Person walks away, exits scene (t=15)
→ Person track marked inactive
→ Package track still active (on ground)
→ Evidence persists in visit_entity_links
```

### Evidence Generated

```python
# Person arrives WITH package
Evidence("scene", "link.carrying_package", "package:42", conf=0.85, object_id=person_id)

# Person drops off package
Evidence("scene", "link.dropped_off_package", "package:42", conf=0.82, object_id=person_id)
Evidence("scene", "link_conf.dropped_off_package", "0.820", conf=1.0, object_id=person_id)
```

### Confidence Calculation

```python
# Distance from person (normalized by person width)
norm_distance = distance(pkg_center, person_center) / person_width
distance_factor = max(0.0, 1.0 - (norm_distance / max_separation_distance))

# Time factor (higher confidence with longer separation)
time_factor = min(1.0, separation_time / (min_separation * 2))

final_conf = distance_factor * person_conf * pkg_conf * time_factor
```

Higher confidence when:
- Package close to person (recently dropped, not thrown)
- Longer separation time (more confident it's intentional)
- Package stationary (not being moved)
- High detector confidences

### Classification Examples

**Complete Delivery Workflow**:
```python
# Step 1: Person arrives with package
if has_evidence("link.carrying_package"):
    partial_intent = "possibly_delivery"

# Step 2: Person drops package
if has_evidence("link.dropped_off_package"):
    intent = "delivery_person"  # CONFIRMED delivery
    
# Step 3: Person leaves
if person_exited and has_evidence("link.dropped_off_package"):
    intent = "delivery_complete"
```

**Differentiate Scenarios**:
```python
# Delivery person (both links)
if "link.carrying_package" and "link.dropped_off_package":
    intent = "delivery_person"

# Porch pirate (pickup but no drop-off)
elif "link.picked_up_package" and not "link.dropped_off_package":
    intent = "porch_pirate"

# Package recipient (pickup existing package)
elif "link.picked_up_package" and is_trusted(visitor_id):
    intent = "resident_return"

# Person just holding package (carrying but hasn't dropped yet)
elif "link.carrying_package" and not "link.dropped_off_package":
    intent = "visitor_with_package"  # Wait to see what they do
```

### Metadata Stored

```sql
-- visit_entity_links table
relation = 'dropped_off_package'
object_meta_json = {
    "separation_time_s": 3,      -- Separated for 3 seconds
    "norm_distance": 1.2,        -- 1.2x person width away
    "package_age_s": 15,         -- Package existed 15s
    "package_conf": 0.93
}
subject_meta_json = {
    "person_age_s": 15,          -- Person in scene 15s
    "person_conf": 0.95
}
```

### Full Package Lifecycle

The system now tracks complete package journeys:

```
┌─────────────────────────────────────────────────────────┐
│ Package Lifecycle Tracking                              │
├─────────────────────────────────────────────────────────┤
│                                                          │
│ 1. ARRIVAL (carrying_package)                           │
│    • Person enters WITH package                         │
│    • Package inside person bbox                         │
│    • Link: carrying_package                             │
│                                                          │
│ 2. DROP-OFF (dropped_off_package)                       │
│    • Package exits person bbox                          │
│    • Separation persists 2+ seconds                     │
│    • Link: dropped_off_package                          │
│    • Intent: delivery_person                            │
│                                                          │
│ 3. WAITING                                              │
│    • Package on ground (stationary)                     │
│    • Person may leave scene                             │
│    • Package track remains active                       │
│                                                          │
│ 4. PICKUP (picked_up_package)                           │
│    • New person approaches                              │
│    • Package enters new person bbox                     │
│    • Dwell time 2+ seconds                              │
│    • Link: picked_up_package                            │
│    • Intent: porch_pirate OR resident_return            │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### Implementation Notes

- **Separation distance** prevents false positives from packages just outside bbox edge
- **Requires prior carrying link** - Only tracks drop-offs for packages that were carried
- **Tags track state** - No additional tables needed
- **Person may leave** - Link created even if person exits after dropping
- **Multi-package support** - Each package tracked independently

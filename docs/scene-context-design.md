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

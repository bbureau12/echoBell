# ADR-0009: Scene context queries for concurrent intent detection

Date: 2026-01-01  
Status: Accepted

## Context

EchoBell creates **one event per arrival** (ADR-0001). When multiple entities
are present simultaneously, multiple events exist in the database:

**Scenario**: AC technician arrives at T+0:00, stays for an hour. At T+0:40,
fire department arrives.

**Event structure**:
- Event A (T+0:00): `intent=technician_visit`, `urgency=30`
- Event B (T+0:40): `intent=authority_urgent`, `urgency=90`

**Policy requirement**: "If fire department arrives WHILE technician is present,
escalate immediately (possible emergency)."

**Problem**: How does the policy engine detect "both are present NOW"?

### Naive Approaches (NOT chosen)

**Option 1: Event merging**
- Merge Event A and Event B into combined event
- **Rejected**: 
  - When to merge? (How long to wait for more arrivals?)
  - How to represent multi-intent events? (Array of intents?)
  - Loses per-entity granularity
  - Complex state management
  - Hard to query ("show me all deliveries")

**Option 2: Event metadata**
- Add `event.concurrent_intents = ["technician_visit"]` to Event B
- **Rejected**:
  - Metadata written at creation time, but scene changes dynamically
  - Would need to update old events when new entities arrive
  - Duplicates data already in scene_tracks
  - Query complexity: "Find all events with concurrent X" is awkward

**Option 3: Real-time event aggregation**
- Query recent events within time window during policy evaluation
- **Rejected**:
  - Time window is arbitrary (5 minutes? 1 hour?)
  - Doesn't account for actual presence (entity might have left)
  - No connection to scene_tracks (ignores enter/exit signals)

## Decision

EchoBell uses **scene context queries** to determine concurrent intents.

**Key insight**: `scene_tracks` already knows who's currently present. Events
record what they wanted. Join them for policy evaluation.

### Architecture

**Separation of concerns**:
- **Events**: Record what happened (arrival, classification) ✓ Simple
- **Scene tracks**: Record who's present (active objects) ✓ Authoritative
- **Scene context queries**: Join events + tracks for policy decisions ✓ Flexible

**New module**: `packages/scene/scene_context.py`

### API

**1. Get active scene intents**
```python
def get_active_scene_intents(
    conn,
    camera_id: int,
    now_ts: int,
    grace_period_s: int = 6,
) -> list[ActiveIntent]:
    """Get all intents for entities currently present."""
```

Returns:
```python
[
    ActiveIntent(
        intent="authority_urgent",
        urgency=90,
        track_type="vehicle",
        camera_id=1,
        ...
    ),
    ActiveIntent(
        intent="technician_visit", 
        urgency=30,
        track_type="vehicle",
        camera_id=1,
        ...
    )
]
```

**2. Get scene urgency level**
```python
def get_scene_urgency_level(
    conn,
    camera_id: int,
    now_ts: int,
) -> tuple[int, str, list[str]]:
    """Get highest urgency + description for current scene."""
```

Returns:
```python
(90, "URGENT: Authority Urgent", ["authority_urgent", "technician_visit"])
# OR
(40, "COMPLEX: 2 concurrent visitors", ["delivery", "neighbor_help"])
# OR
(30, "normal", ["technician_visit"])
```

**3. Check concurrent intents**
```python
def check_concurrent_intents(
    conn,
    camera_id: int,
    now_ts: int,
    required_intents: list[str],
) -> bool:
    """Check if ALL required intents are simultaneously active."""
```

Example:
```python
if check_concurrent_intents(
    conn, camera_id=1, now_ts=now,
    required_intents=["authority_urgent", "technician_visit"]
):
    # Both fire dept AND technician present → ESCALATE
    notify_emergency_contact()
```

### SQL Implementation

```sql
-- Join active tracks with their most recent events
SELECT 
    ve.intent_inferred,
    ve.urgency,
    ve.camera_id,
    st.track_key,
    st.track_type
FROM scene_tracks st
LEFT JOIN visitor_event_plate_sightings veps 
    ON st.track_key = veps.plate_hmac 
    AND st.track_type = 'vehicle'
LEFT JOIN visitor_events ve 
    ON veps.event_id = ve.event_id
WHERE st.camera_id = ?
  AND st.active = 1              -- Currently present
  AND st.last_seen_ts >= ?       -- Within grace period
  AND ve.intent_inferred IS NOT NULL
```

**Key filters**:
- `active = 1`: Entity hasn't exited
- `last_seen_ts >= cutoff`: Seen within grace period (6 seconds)
- Join with events to get classified intent

## Consequences

### Pros
- **Simple event model**: One event per arrival (no merging complexity)
- **Authoritative presence**: Scene tracks are source of truth for "who's here"
- **Flexible queries**: Policy can ask "any authority present?" or "multiple
  deliveries?" without changing event structure
- **Real-time**: Queries reflect current scene state, not stale metadata
- **No event updates**: Old events stay immutable, queries provide fresh view
- **Reusable**: Same query mechanism works for any intent combination

### Cons
- **Query overhead**: Policy evaluation requires database queries
- **Grace period sensitivity**: Too short = false exits, too long = stale presence
- **Camera-scoped**: Each camera has independent scene state (intentional)

### Mitigations
- **Query optimization**: Indexed queries on `scene_tracks(active, last_seen_ts)`
- **Caching potential**: Scene state changes slowly (seconds), could cache
- **Grace period tuning**: Default 6s works for most scenarios, configurable
  if needed

## Use Cases

### Policy: Authority + Service = Escalate
```python
active_intents = get_active_scene_intents(conn, camera_id, now_ts)

if check_concurrent_intents(conn, camera_id, now_ts, 
                           ["authority_urgent", "technician_visit"]):
    return {
        "action": "ESCALATE_IMMEDIATELY",
        "reason": "Fire department arrived while technician on site",
        "urgency": 95
    }
```

### Policy: Multiple Deliveries = Notify
```python
delivery_intents = [ai for ai in active_intents 
                   if ai.intent in ["delivery", "package_drop"]]

if len(delivery_intents) >= 2:
    return {
        "action": "NOTIFY",
        "reason": f"{len(delivery_intents)} delivery vehicles present",
        "urgency": 35
    }
```

### Policy: Scene Complexity Alert
```python
urgency, desc, intents = get_scene_urgency_level(conn, camera_id, now_ts)

if len(intents) > 2:
    return {
        "action": "ALERT",
        "reason": f"Complex scene: {len(intents)} concurrent visitors",
        "urgency": urgency
    }
```

## Relationship to Other ADRs

**ADR-0001 (Events without visitor_id)**:
- Events can be vehicle-only
- Scene context joins work for both person and vehicle tracks
- Query handles `visitor_id` (people) and `plate_hmac` (vehicles) separately

**ADR-0005 (Scene awareness temporal tracking)**:
- Scene tracks provide the "who's present" foundation
- Scene context queries consume scene track state
- Complementary: ADR-0005 maintains state, ADR-0009 queries it

**ADR-0006 (Entity association)**:
- Person-vehicle links influence individual event classification
- Scene context queries can detect "multiple linked pairs present"
- Both operate at visit scope but different purposes

**ADR-0007 (Cross-camera intent persistence)**:
- Intent persists via visitor_id across cameras
- Scene context is camera-specific (intentional isolation)
- Could extend to multi-camera scene queries (future)

## Implementation Notes

### Camera Isolation

Scene context is **camera-scoped** by design:
- Each camera has independent `scene_tracks`
- Queries filter by `camera_id`
- Prevents false concurrency from different locations

**Rationale**: "Technician at back door" + "Delivery at front door" are
different scenarios than both at same location.

**Future**: Could add multi-camera scene fusion if needed (e.g., "person seen
at camera 1 then camera 2" for journey tracking).

### Grace Period

Default 6 seconds matches scene tracker grace period:
- Object not detected for <6s: Still considered present (occlusion tolerance)
- Object not detected for >6s: Marked as exited

Scene context uses same threshold for consistency.

### Urgency Calculation

`get_scene_urgency_level()` returns **max urgency**:
- Single intent: Returns its urgency
- Multiple intents: Returns highest urgency (most critical entity)
- Empty scene: Returns (0, "empty scene", [])

**Design choice**: Policies care about highest risk, not average risk.

### Event-Track Matching

**For vehicles**: Match via `plate_hmac`
```
scene_tracks.track_key (plate_hmac) 
  → visitor_event_plate_sightings.plate_hmac 
  → visitor_events.event_id
```

**For people**: Match via `visitor_id`
```
scene_tracks.track_key (visitor_id)
  → visitor_events.visitor_id
```

Query uses UNION to handle both cases.

## Alternative Design: Event-Per-Scene-State

**Not chosen**: Create new event whenever scene state changes:
- Technician arrives → Event A
- Fire dept arrives → Event B (new)
- Combined state → Event C (merged state)

**Why rejected**:
- Event explosion (every scene change = new event)
- Hard to query ("find all delivery events") when some are merged
- Loses individual entity events
- Complex to implement (when to merge? when to split?)

**Chosen approach is simpler**: Keep events simple (per-arrival), query scene
state on-demand.

## Future Enhancements

**Potential additions**:
- **Cross-camera scene queries**: "Person at camera 1 AND vehicle at camera 2"
- **Temporal scene queries**: "Intent X for longer than Y minutes"
- **Scene history**: "How long has this combination been active?"
- **Scene patterns**: "This intent combination occurs every Tuesday at 10am"

**Not implemented** (keeping initial version simple):
- Single-camera scene context only
- Binary presence (active=1 or active=0)
- No duration tracking in scene context layer (available via track timestamps)

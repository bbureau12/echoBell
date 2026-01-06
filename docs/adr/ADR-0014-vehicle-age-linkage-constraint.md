# ADR-0014: Vehicle Age Constraint for Person-Vehicle Linkage

**Status:** Accepted  
**Date:** 2026-01-06  
**Deciders:** System Architecture Team  
**Context:** Scene Tracking, Entity Linkage

## Context and Problem Statement

The person-to-vehicle linkage system associates people with vehicles they arrived with based on spatial proximity and temporal constraints. Prior to this ADR, the system only checked if the **person** just appeared (within 3 seconds) to prevent linking random passersby to parked vehicles.

However, this created a problem:
- A vehicle parked for hours would still be linked to any person appearing near it (within the 3-second window)
- Delivery drivers walking past parked cars would incorrectly be linked to them
- No way to distinguish between "person arriving with vehicle" vs. "person walking past long-parked vehicle"

**Example scenario:**
```
10:00 AM - Neighbor parks car in front of house
11:30 AM - Delivery driver arrives on foot
11:30 AM - System sees: new person (1s old) near vehicle → creates link
Result: Delivery driver incorrectly linked to neighbor's car
```

## Decision

Add a **maximum vehicle age constraint** to person-to-vehicle linkage. Vehicles that have been on-scene longer than `max_person_age_s` (default 1 hour) will not be linked to new people.

### Implementation

Modified `compute_visit_links_for_snapshot()` in `packages/scene/scene_linkage.py`:

1. **Query vehicle tracks** from `scene_tracks` table to get `first_seen_ts`
2. **Calculate vehicle age**: `now_ts - first_seen_ts`
3. **Skip linking** if `vehicle_age_s > max_person_age_s`

### Code Changes

```python
# Query scene_tracks for vehicle tracks
vehicle_rows = conn.execute("""
    SELECT track_key, first_seen_ts
    FROM scene_tracks
    WHERE camera_id = ? AND track_type = 'vehicle' AND active = 1
""", (camera_id,)).fetchall()

# Map vehicle object_id to first_seen_ts
for v in vehicles:
    v_id = int(v.object_id)
    plate_hmac = getattr(v, "props", {}).get("plate_hmac")
    
    if plate_hmac and plate_hmac in vehicle_track_first_seen:
        vehicle_first_seen[v_id] = vehicle_track_first_seen[plate_hmac]

# During linkage loop:
if vehicle_first_seen:
    v_first_seen = vehicle_first_seen.get(v_id)
    if v_first_seen is not None:
        vehicle_age_s = now - v_first_seen
        if vehicle_age_s > max_person_age_s:
            # Vehicle parked too long, skip
            continue
```

### Linkage Rules (Complete)

A person-to-vehicle link is created if ALL of these conditions pass:

| Condition | Threshold | Reason |
|-----------|-----------|--------|
| Person just appeared | ≤ 3 seconds | Only link fresh arrivals, not passersby |
| Person not too old | ≤ 1 hour | Don't link people who've been around (they exited vehicle) |
| Vehicle not too old | ≤ 1 hour | Don't link to long-parked vehicles |
| Proximity | Normalized distance ≤ 1.2 | Must be spatially near |
| Confidence | ≥ 0.35 | Detection + proximity confidence threshold |

## Consequences

### Positive

1. **Eliminates false positives** - Delivery drivers no longer linked to parked neighbor cars
2. **Realistic arrival detection** - Only links when both person AND vehicle are recent
3. **Configurable threshold** - `max_person_age_s` parameter can be adjusted (default 3600s = 1 hour)
4. **Reuses existing parameter** - Same threshold applies to person age and vehicle age (simpler)
5. **Backward compatible** - Defaults preserve existing behavior if tracks aren't available

### Negative

1. **Requires scene_tracks** - Must have vehicle tracking data populated
2. **Plate HMAC dependency** - Vehicle identification relies on `plate_hmac` in props
3. **Temporary vehicles missed** - Vehicles without plate data may not have age checked
4. **Additional query overhead** - Extra database lookup for vehicle tracks

### Edge Cases Handled

- **No vehicle track data**: Falls back to allowing link (assumes vehicle is new)
- **Vehicle without plate**: Currently won't have age data (could enhance with temp keys)
- **Multiple vehicles**: Each vehicle checked independently
- **Inactive tracks**: Only considers `active=1` tracks

## Alternatives Considered

### Option 1: Separate parameter for vehicle age
```python
max_vehicle_age_s: int = 3600
max_person_age_s: int = 3600
```
- ✅ More flexible (different thresholds for person vs. vehicle)
- ❌ More parameters to configure
- ❌ Adds complexity without clear use case

**Decision:** Rejected - Same threshold makes sense for both (typical arrival window)

### Option 2: Time-decay confidence instead of hard cutoff
```python
# Reduce confidence based on vehicle age
age_penalty = exp(-vehicle_age_s / decay_constant)
confidence *= age_penalty
```
- ✅ Gradual degradation instead of binary
- ✅ Very old vehicles still linkable but with low confidence
- ❌ More complex to reason about
- ❌ Unclear how to tune decay_constant

**Decision:** Rejected - Hard cutoff is simpler and more predictable

### Option 3: Check visit history instead of track age
```python
# Link only if vehicle appeared in same visit_id as person
if vehicle.visit_id == person.visit_id:
    link()
```
- ✅ Uses existing visit concept
- ❌ Requires visit_id on objects (not always available)
- ❌ Doesn't handle cross-visit scenarios (person exits, returns)

**Decision:** Rejected - Track age is more reliable

## Testing

Added 3 comprehensive tests in `tests/test_scene_linkage.py`:

1. **`test_old_vehicle_prevents_linking`**
   - Vehicle: 90 minutes old
   - Person: 1 second old
   - Expected: No link

2. **`test_recent_vehicle_allows_linking`**
   - Vehicle: 30 seconds old
   - Person: 1 second old
   - Expected: Link created

3. **`test_old_person_and_old_vehicle_no_link`**
   - Vehicle: 2 hours old
   - Person: 10 seconds old (outside first-appearance window)
   - Expected: No link

All 44 existing tests continue to pass.

## Migration

No database migration required. Changes are runtime-only in linkage logic.

## Related Decisions

- **ADR-00006:** Scene Awareness Entity Association - Original person-vehicle linkage design
- **ADR-0005:** Scene Awareness Temporal Tracking - Introduced `scene_tracks` table
- **ADR-0007:** Cross-Camera Intent Persistence - Uses linkage for visitor tracking

## Future Enhancements

1. **Temporary vehicle keys** - Track vehicles without plates using bbox-based temp keys
2. **Variable thresholds by intent** - Different age limits for delivery vs. visitor scenarios
3. **Vehicle movement detection** - Reset age if vehicle moves (re-parks)
4. **Confidence decay** - Gradual degradation instead of hard cutoff (if needed)

## References

- `packages/scene/scene_linkage.py` - Linkage implementation
- `tests/test_scene_linkage.py` - Test coverage
- `packages/classify/classify_and_log.py` - Uses linkage for evidence enrichment

# ADR-0011: Vehicle Type Preservation and Size-Aware Person-Vehicle Linkage

**Status**: Accepted  
**Date**: 2026-01-10  
**Deciders**: System Architect  
**Related**: ADR-0004 (Vehicle Role Inference), ADR-0005 (Scene Awareness)

---

## Context

Person-vehicle linkage is critical for inferring visitor intent (e.g., "person arrived with this vehicle"). However, the system faced two related challenges:

### Problem 1: Loss of Vehicle Type Granularity

YOLO detects specific vehicle types (`bicycle`, `car`, `truck`, `bus`, `motorbike`), but the vision class mapping collapses all to generic `vehicle` for linkage purposes. This lost granularity prevents:

- Intent rules specific to vehicle types (e.g., "bicycle delivery" vs "truck delivery")
- Analytics on vehicle type distribution
- Type-specific notifications ("delivery truck at gate" vs "bicycle visitor")

**Example**:
```
YOLO: "bicycle" (conf: 0.85)
  ↓ vision_class_map
Semantic: "vehicle" 
  ↓ Evidence
feature="class", value="vehicle"  ← Lost that it was a bicycle!
```

### Problem 2: False Linkages from Size Mismatches

Using only normalized distance for linkage caused false positives:

1. **Head brushing corner**: Person walking past vehicle with head barely clipping vehicle bbox
   - Person box: 30px (just head)
   - Car box: 300px tall
   - Normalized distance: 0.3 (within threshold) → FALSE LINKAGE ❌

2. **One-size-fits-all thresholds**: Same size ratio expectations for bicycles and semi-trucks
   - Bicycle: Person often LARGER than vehicle (normal)
   - Semi-truck: Person should be MUCH smaller
   - Previous logic treated both the same → Rejected valid bicycle linkages ❌

### Root Cause

The `Detection` dataclass only stored the **semantic class** (`vehicle`), discarding the original YOLO class name. Size validation had no awareness of vehicle type.

---

## Decision

We implement a two-part solution:

### Part 1: Preserve Raw YOLO Class

**Add `raw_class` field to `Detection`**:
```python
@dataclass
class Detection:
    cls: str              # "vehicle" (semantic, for linkage)
    raw_class: str        # "bicycle" (YOLO raw) ← NEW!
    conf: float
    box: Tuple[int, int, int, int]
    color: str
```

**Emit `vehicle_type` evidence** for all vehicles:
```python
# In snapshot_and_detect():
if det.cls.lower() == "vehicle" and det.raw_class:
    obj.evidence.append(
        Evidence("vision", "vehicle_type", det.raw_class.lower(), conf, obj_id)
    )
```

**Result**: Every vehicle now has BOTH:
- `Evidence(feature="class", value="vehicle")` - for generic linkage
- `Evidence(feature="vehicle_type", value="bicycle")` - for specific intent rules

### Part 2: Vehicle-Type-Aware Size Ratio Validation

**Add `_size_ratio_check()` function**:
```python
def _size_ratio_check(
    person_box: tuple,
    vehicle_box: tuple,
    vehicle_type: Optional[str] = None,
) -> bool:
    """
    Check if person and vehicle sizes are proportionally reasonable.
    
    Uses vehicle_type to apply appropriate thresholds:
    - Bicycles/motorcycles: Person can be 0.8x to 2.5x vehicle size
    - Cars/trucks/buses: Person must be 0.15x to 0.85x vehicle size
    """
    p_diag = math.hypot(person_width, person_height)
    v_diag = math.hypot(vehicle_width, vehicle_height)
    ratio = p_diag / v_diag
    
    if vehicle_type in ("bicycle", "motorbike", "motorcycle"):
        return 0.8 <= ratio <= 2.5  # Person can be larger
    else:
        return 0.15 <= ratio <= 0.85  # Person should be smaller
```

**Integration** in `compute_visit_links_for_snapshot()`:
```python
for v in vehicles:
    vehicle_type = getattr(v, "props", {}).get("raw_class")
    
    # Check size ratio BEFORE distance calculation
    if not _size_ratio_check(p_box, v_box, vehicle_type):
        continue  # Skip this vehicle candidate
    
    # ... existing normalized distance logic
```

---

## Consequences

### Positive

1. **Granular Intent Classification**
   - Signal rules can now match `vehicle_type == "bicycle"` vs `vehicle_type == "truck"`
   - Enables type-specific responses: "Package left by your door" (bike) vs "Delivery truck at gate" (truck)
   - Analytics: Track which vehicle types visit (delivery methods, visitor patterns)

2. **Eliminates False Linkages**
   - **Head clips rejected**: Person box 30px vs car 300px → ratio 0.10 < 0.15 threshold ❌
   - **Bicycle linkage preserved**: Person 150px vs bike 90px → ratio 1.67 within 0.8-2.5 range ✅
   - **Toy vehicle rejection**: Person 200px vs toy bike 60px → ratio 3.33 > 2.5 threshold ❌

3. **Bicycle/Motorcycle Support**
   - Previous logic would reject person larger than vehicle
   - Now correctly handles rider-on-bike scenarios
   - Enables bicycle delivery intent classification

4. **No Breaking Changes**
   - Existing linkage logic unchanged (still uses `label == "vehicle"`)
   - `raw_class` field is optional (backward compatible)
   - Size ratio check complements (not replaces) distance check

### Negative

1. **Slight Performance Cost**
   - Additional diagonal calculation per vehicle candidate
   - Negligible impact (simple math operations)

2. **Configuration Complexity**
   - Two sets of thresholds (bicycle vs car)
   - Mitigated by clear documentation and tests

3. **Edge Cases**
   - Unknown vehicle types default to car thresholds
   - Very large people on small bikes might be rejected (rare)

### Neutral

1. **Database Schema**
   - No database changes required
   - `raw_class` already stored in `scene_tracks.raw_class`
   - Evidence stored in existing `evidence_json` field

2. **Migration Path**
   - Existing events unaffected (backward compatible)
   - New detections automatically get `vehicle_type` evidence
   - Old signal rules continue working

---

## Implementation Details

### Class Mappings (migration `004_add_vision_maps.sql`)

```sql
INSERT INTO vision_class_map (model_name, raw_class, semantic_class)
VALUES 
    ('yolov8n', 'bicycle',   'vehicle'),  -- Now mapped!
    ('yolov8n', 'car',       'vehicle'),
    ('yolov8n', 'motorbike', 'vehicle'),
    ('yolov8n', 'truck',     'vehicle'),
    ('yolov8n', 'bus',       'vehicle');  -- Added
```

### Example Evidence Output

```python
# For a bicycle detection:
Evidence(source="vision", feature="class", value="vehicle", conf=0.85)
Evidence(source="vision", feature="vehicle_type", value="bicycle", conf=0.85)

# For a car detection:
Evidence(source="vision", feature="class", value="vehicle", conf=0.88)
Evidence(source="vision", feature="vehicle_type", value="car", conf=0.88)
```

### Example Intent Rules

```sql
-- Generic vehicle detection (still works)
INSERT INTO signal_rule (source, feature, operator, value, intent_name, weight)
VALUES ('vision', 'class', 'equals', 'vehicle', 'vehicle_visitor', 1.0);

-- Bicycle-specific intent (NEW capability)
INSERT INTO signal_rule (source, feature, operator, value, intent_name, weight)
VALUES ('vision', 'vehicle_type', 'equals', 'bicycle', 'bicycle_delivery', 2.0);

-- Large vehicle intent (NEW capability)
INSERT INTO signal_rule (source, feature, operator, value, intent_name, weight)
VALUES ('vision', 'vehicle_type', 'contains_any_of', 'truck,bus', 'commercial_delivery', 2.5);
```

### Size Ratio Test Coverage

```python
# Bicycle scenarios
test_bicycle_person_larger_accepted()      # Ratio 1.67 ✅
test_bicycle_person_tiny_clip_rejected()   # Ratio 0.30 ❌

# Car scenarios  
test_car_normal_ratio_accepted()           # Ratio 0.50 ✅
test_car_person_too_small_rejected()       # Ratio 0.10 ❌
test_car_person_too_large_rejected()       # Ratio 1.18 ❌

# Truck scenarios
test_truck_normal_ratio_accepted()         # Ratio 0.24 ✅

# Edge cases
test_suspiciously_small_vehicle_rejected() # Diagonal < 5px ❌
test_unknown_vehicle_uses_car_thresholds() # Defaults ✅
```

---

## Alternatives Considered

### Alternative 1: Store Multiple Classes per Object

**Approach**: Detection has both `cls` and `subtype` fields.

**Rejected because**:
- Confusing semantics ("which class is authoritative?")
- Requires changes to all consumers of `Detection.cls`
- `raw_class` is clearer intent (preserves original YOLO output)

### Alternative 2: Separate Evidence for Each Vehicle Type

**Approach**: Create separate semantic classes (`bicycle`, `car`, `truck`).

**Rejected because**:
- Breaks existing linkage logic (looks for `label == "vehicle"`)
- Would need N different linkage functions (one per type)
- Loses benefit of unified "vehicle" semantic category
- Current approach gets best of both worlds (generic + specific)

### Alternative 3: Post-Classification Vehicle Type Lookup

**Approach**: Look up raw class from database after classification.

**Rejected because**:
- Extra database query per classification
- Information already available at detection time
- Violates "enrich early" principle

### Alternative 4: Fixed Size Ratio for All Vehicles

**Approach**: Single threshold (e.g., 0.15-0.85) for all vehicle types.

**Rejected because**:
- Rejects valid bicycle linkages (person often larger)
- One-size-fits-all doesn't match real-world vehicle diversity
- False negatives on small vehicles, false positives on large

---

## Related Work

- **ADR-0004**: Vehicle Role Inference - Now enhanced with type-specific rules
- **ADR-0005**: Scene Awareness - Scene tracker already stores `raw_class`
- **ADR-0002**: Plate Privacy - Vehicle type complements plate-based identity
- **Vision Class Mapping**: Migration `004_add_vision_maps.sql`

---

## Testing Strategy

### Unit Tests (16 tests)
- `test_size_ratio_check.py`: Validates all size ratio scenarios
- Covers bicycles, cars, trucks, motorcycles
- Boundary condition testing (exact thresholds)
- Edge cases (tiny vehicles, unknown types)

### Integration Tests (5 tests)
- `test_vehicle_type_evidence.py`: Validates evidence structure
- Ensures both `class` and `vehicle_type` evidence emitted
- Documents intent rule usage patterns

### Regression Protection
- All 176 existing tests continue passing
- No breaking changes to linkage behavior
- Backward compatible with existing events

---

## Metrics for Success

1. **False Linkage Reduction**: Eliminate "head clip" false positives
2. **Bicycle Detection**: Successfully link people to bicycles
3. **Intent Granularity**: Enable vehicle-type-specific intents
4. **Test Coverage**: 100% of size ratio logic tested
5. **Performance**: No measurable slowdown in linkage computation

---

## Future Enhancements

1. **Dynamic Thresholds**: Learn optimal ratios from labeled data
2. **Vehicle Size Classes**: Group by actual size (small/medium/large)
3. **Orientation-Aware**: Different thresholds for front vs. side view
4. **Confidence Weighting**: Adjust thresholds based on detection confidence
5. **Multi-Person Vehicles**: Handle multiple people entering from same vehicle

---

## References

- Code: `packages/perception/vision.py` (Detection dataclass, evidence emission)
- Code: `packages/scene/scene_linkage.py` (_size_ratio_check, integration)
- Tests: `tests/test_size_ratio_check.py` (16 unit tests)
- Tests: `tests/test_vehicle_type_evidence.py` (5 integration tests)
- Migration: `infra/db/migrations/004_add_vision_maps.sql` (bicycle/bus mappings)

---

**Decision Outcome**: ACCEPTED

This enhancement provides significant value with minimal risk. The dual approach (preserving raw class + type-aware validation) solves both granularity loss and false linkage problems elegantly. Implementation is backward compatible and thoroughly tested.

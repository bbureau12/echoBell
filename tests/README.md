# EchoBell Tests

This directory contains the test suite for the EchoBell vision and tracking system.

## Test Files

### Vision Regression Tests (`test_vision_regression.py`)
Image-based regression tests for the vision system. Uses real photos to verify
detection, classification, and evidence generation.

**Runs:** 6 tests  
**Coverage:** Person detection, vehicle detection, plate reading, scene evidence

See [Vision Regression Tests](#vision-regression-tests-1) section below for details.

### Scene Linkage Tests (`test_scene_linkage.py`)
Tests entity association logic (person-to-vehicle, person-to-package) using
synthetic bounding box data. No photos required.

**Runs:** 41 tests  
**Coverage:** Geometry helpers, spatial proximity, temporal constraints, confidence
scoring, linkage persistence, package handling, edge cases

**Key test classes:**
- `TestGeometryHelpers` (10 tests) - IoU, box relationships, distance calculations
- `TestPersonToVehicleLinkage` (8 tests) - Spatial proximity-based linkage
- `TestTemporalConstraints` (3 tests) - Time-based linkage rules
- `TestLinkageConfidenceScoring` (2 tests) - Confidence calculation
- `TestLinkagePersistence` (3 tests) - State tracking across frames
- `TestLinkageEvidence` (2 tests) - Evidence generation
- `TestEdgeCases` (5 tests) - Boundary conditions
- `TestPackageToPersonLinkage` (8 tests) - Package carrying detection

### Plate Service Tests (`test_plate_service.py`)
Tests license plate detection, HMAC privacy, trusted plate matching, and visit tracking.

**Runs:** 27 tests  
**Coverage:** Plate detection, hashing, trust labels, visit persistence

### Cross-Camera Tracking Tests (`test_cross_camera_tracking.py`)
Tests cross-camera person tracking via visitor_id. Verifies global presence
detection, camera handoffs, multi-visitor scenarios, and presence duration tracking.

**Runs:** 22 tests  
**Coverage:** Single camera baseline, cross-camera tracking, multi-visitor scenes,
grace period behavior, edge cases, continuous presence duration

**Key test classes:**
- `TestSingleCameraPersonTracking` (2 tests) - Per-camera baseline
- `TestCrossCameraPersonTracking` (5 tests) - Camera handoff, global presence
- `TestMultipleVisitorsMultipleCameras` (3 tests) - Multi-person scenes
- `TestGracePeriodAcrossCameras` (2 tests) - Temporal window behavior
- `TestEdgeCases` (4 tests) - No visitor_id, expired tracks, etc.
- `TestVisitorPresenceDuration` (6 tests) - Continuous session tracking, duration resets

## Running Tests

### Run all tests (96 total)
```powershell
$env:PYTHONPATH="d:\Projects\echoBell\echoBell"
.\.venv-vision\Scripts\python.exe -m pytest tests/ -v
```

### Run specific test file
```powershell
# Scene linkage only (41 tests)
pytest tests/test_scene_linkage.py -v

# Cross-camera tracking only (22 tests)
pytest tests/test_cross_camera_tracking.py -v

# Plate service only (27 tests)
pytest tests/test_plate_service.py -v

# Vision regression only (6 tests)
pytest tests/test_vision_regression.py -v
```

### Run specific test
```bash
pytest tests/test_vision_regression.py::test_vision_regression[trusted_person_single] -v
pytest tests/test_cross_camera_tracking.py::TestCrossCameraPersonTracking::test_person_moves_between_cameras -v
```

### Run with verbose output
```bash
pytest tests/ -v -s
```

## Structure

```
tests/
├── fixtures/                       # Test images for vision regression
│   ├── trusted/                   # Trusted person images
│   ├── sheriff/                   # Law enforcement images
│   ├── delivery/                  # Delivery person images
│   ├── resident/                  # Known resident images
│   └── unknown/                   # Unknown visitor images
├── test_vision_regression.py      # Image-based vision tests (6 tests)
├── test_scene_linkage.py          # Entity association tests (41 tests)
├── test_plate_service.py          # Plate detection tests (27 tests)
├── test_cross_camera_tracking.py  # Cross-camera tracking tests (16 tests)
└── README.md                      # This file
```

---

## Vision Regression Tests

## Adding New Test Cases

1. **Add test image** to appropriate fixtures subdirectory:
   ```
   tests/fixtures/<scenario>/<image_name>.jpg
   ```

2. **Define expected evidence** in `test_vision_regression.py`:
   ```python
   VisionTestCase(
       name="your_test_name",
       image_path=TEST_CASES_DIR / "scenario" / "image.jpg",
       expected_evidence=[
           {"source": "visitor", "feature": "visitor.trusted_id", "value": "1", "min_conf": 0.99, "object_id": 0},
           {"source": "scene", "feature": "person_count", "value": "1", "min_conf": 1.0, "object_id": None},
       ]
   )
   ```

3. **Run the test**:
   ```bash
   pytest tests/test_vision_regression.py::test_vision_regression[your_test_name] -v
   ```

## Evidence Format

Each expected evidence item has:
- `source`: Evidence source (e.g., "visitor", "scene", "age", "plate")
- `feature`: Evidence feature (e.g., "visitor.trusted_id", "vehicle_count")
- `value`: Expected value (optional, omit to just check presence)
- `min_conf`: Minimum confidence threshold (optional)
- `object_id`: Expected object_id (use `None` for scene-level evidence)

## Example Test Cases

### Police Officer (Trusted)
```python
expected_evidence=[
    {"source": "visitor", "feature": "visitor.trusted_id", "value": "1", "min_conf": 0.99, "object_id": 0},
    {"source": "age", "feature": "age_group", "value": "adult", "min_conf": 0.80, "object_id": 0},
    {"source": "scene", "feature": "vehicle_count", "value": "0", "min_conf": 1.0, "object_id": None},
    {"source": "scene", "feature": "person_present", "value": "true", "min_conf": 0.90, "object_id": None},
]
```

### Delivery Person with Package
```python
expected_evidence=[
    {"source": "scene", "feature": "person_count", "value": "1", "min_conf": 1.0, "object_id": None},
    {"source": "scene", "feature": "vehicle_count", "value": "1", "min_conf": 1.0, "object_id": None},
    {"source": "vision", "feature": "package_box", "value": "true", "min_conf": 0.9, "object_id": None},
    {"source": "scene", "feature": "link.carrying_package", "min_conf": 0.5, "object_id": 0},
]
```

### Vehicle with License Plate
```python
expected_evidence=[
    {"source": "scene", "feature": "vehicle_count", "value": "1", "min_conf": 1.0, "object_id": None},
    {"source": "plate", "feature": "plate_text", "min_conf": 0.7},  # Check plate detected
    {"source": "plate", "feature": "plate_state", "value": "CA", "min_conf": 0.6},
]
```

## Debugging Failed Tests

When a test fails, the output shows:
1. Which evidence item failed
2. Expected vs actual values
3. All evidence generated (for comparison)

Example failure output:
```
Missing or incorrect evidence: visitor.visitor.trusted_id
  Expected: value=1, min_conf=0.99, object_id=0
  Actual value: None

=== All Evidence for police_officer_trusted ===
  - scene.person_present=true conf=0.90 obj=None
  - scene.person_count=1 conf=1.00 obj=None
  - age.age_group=adult conf=0.85 obj=0
==================================================
```

## Tips

- **Start with loose confidence thresholds** and tighten based on actual performance
- **Use `None` for optional evidence** - omit value/min_conf to just check presence
- **Group related tests** in subdirectories (police/, delivery/, etc.)
- **Use descriptive test names** - they appear in pytest output
- **Add comments** explaining tricky test cases

## CI/CD Integration

Add to your CI pipeline:
```yaml
- name: Run vision regression tests
  run: |
    pytest tests/test_vision_regression.py --junitxml=test-results.xml
```

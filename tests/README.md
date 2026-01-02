# Vision Regression Tests

This directory contains regression tests for the echoBell vision system.

## Structure

```
tests/
├── fixtures/           # Test images organized by scenario
│   ├── trusted/       # Trusted person images
│   ├── sheriff/       # Law enforcement images
│   ├── delivery/      # Delivery person images
│   ├── resident/      # Known resident images
│   └── unknown/       # Unknown visitor images
├── test_vision_regression.py  # Main regression test suite
└── README.md          # This file
```

## Running Tests

### Run all tests
```bash
pytest tests/
```

### Run specific test
```bash
pytest tests/test_vision_regression.py::test_vision_regression[trusted_person_single]
```

### Run with verbose output
```bash
pytest tests/ -v -s
```

### Run only regression tests
```bash
pytest tests/ -m regression
```

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

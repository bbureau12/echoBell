# Quick Start Guide: Vision Regression Testing

## Setup (One Time)

1. **Install pytest** (if not already installed):
   ```bash
   pip install pytest
   ```

2. **Move your test image** to the fixtures directory:
   ```bash
   # Move your trusted person image
   move test\police\20251227_174156.jpg tests\fixtures\trusted\20251227_174156.jpg
   
   # Move your sheriff image
   copy "D:\Projects\echoBell\echoBell\data\police\Dep.-A-Fox-3-scaled-e1670953812693.jpg" tests\fixtures\sheriff\
   ```

## Running Tests

### Run the Trusted Person Test
```bash
pytest tests/test_vision_regression.py::test_vision_regression[trusted_person_single] -v
```

### Run the Sheriff Authority Test
```bash
pytest tests/test_vision_regression.py::test_vision_regression[sheriff_authority_urgent] -v -s
```
This test validates:
- Evidence: OCR detects "sherifpl", adult age, tie class
- Classification: intent=authority_urgent, conf≥0.70, urgency≥85

### Run All Tests
```bash
pytest tests/test_vision_regression.py -v
```

### Option: Generate fresh test case from your image

If you want to regenerate the expected evidence from scratch:

```bash
python tests/generate_test_case.py tests/fixtures/trusted/20251227_174156.jpg trusted_person_single
```

This will:
1. Run vision detection on the image
2. Show all evidence generated
3. Print Python code to copy into `test_vision_regression.py`

## Expected Output

When the test passes:
```
tests/test_vision_regression.py::test_vision_regression[trusted_person_single] PASSED [100%]
```

When the test fails:
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

## Adding More Test Cases

1. **Add image** to fixtures:
   ```bash
   # Example: delivery person
   copy path\to\delivery.jpg tests\fixtures\delivery\
   ```

2. **Generate test case**:
   ```bash
   python tests/generate_test_case.py tests/fixtures/delivery/delivery.jpg delivery_with_package
   ```

3. **Copy generated code** into `test_vision_regression.py` in the `VISION_TEST_CASES` list

4. **Run the new test**:
   ```bash
   pytest tests/test_vision_regression.py::test_vision_regression[delivery_with_package] -v
   ```

## Common Commands

```bash
# Run all regression tests
pytest tests/

# Run specific test with verbose output
pytest tests/test_vision_regression.py::test_vision_regression[police_officer_trusted] -v -s

# Run all tests and show print statements
pytest tests/ -s

# List all tests without running
pytest tests/ --collect-only

# Run tests matching pattern
pytest tests/ -k "police"
```

## Tips

- **Start with current image**: Use `generate_test_case.py` on your existing image to see what evidence is actually generated
- **Adjust thresholds**: If evidence confidence varies slightly, lower the `min_conf` value
- **Remove flaky evidence**: Some evidence may not be deterministic - comment those out
- **Test both positive and negative**: Add tests for cases that SHOULD and SHOULDN'T match

# Sheriff Authority Test Case

## Overview

This test validates that the vision + classification pipeline correctly identifies law enforcement (sheriff) imagery and classifies it with the `authority_urgent` intent.

## Test Image

**Source**: `D:\Projects\echoBell\echoBell\data\police\Dep.-A-Fox-3-scaled-e1670953812693.jpg`

**Expected Location**: `tests/fixtures/sheriff/Dep.-A-Fox-3-scaled-e1670953812693.jpg`

## Expected Behavior

### Evidence Detection

The vision system should detect at least these pieces of evidence:

1. **OCR Token**: "sherifpl" (confidence ≥ 0.15, object_id = 0)
   - Source: OCR text recognition on badge/uniform
   - Matches signal rule 29: contains 'sheri'

2. **Age Group**: "adult" (confidence ≥ 0.80, object_id = 0)
   - Source: Age classification
   - Matches signal rule 31: equals 'adult'

3. **Tie Detection**: "tie" (confidence ≥ 0.75, object_id = 1)
   - Source: YOLO vision classification
   - Matches signal rule 30: equals 'tie'

### Signal Rules Triggered

```
[signal_rule 29] authority_urgent +0.00 (w=0.00*conf=0.16, urg=10)
  because ev(src=ocr feat=token val=sherifpl obj=0) contains 'sheri' scope=person

[signal_rule 31] authority_urgent +0.00 (w=0.00*conf=0.85, urg=10)
  because ev(src=age feat=age_group val=adult obj=0) equals 'adult' scope=person

[signal_rule 30] authority_urgent +0.00 (w=0.00*conf=0.80, urg=10)
  because ev(src=vision feat=class val=tie obj=1) equals 'tie' scope=person

[group sheriff deputy] authority_urgent +1.00 bind=0 scope=person
```

### Classification Output

- **Intent**: `authority_urgent`
- **Confidence**: ≥ 0.70 (target: 0.75)
- **Urgency**: ≥ 85 (target: 90)

The test allows ±10 point tolerance on urgency and slightly lower confidence to account for variations in vision detection.

## Running the Test

### Setup (One Time)

```powershell
# Copy the sheriff image to the test fixtures
copy "D:\Projects\echoBell\echoBell\data\police\Dep.-A-Fox-3-scaled-e1670953812693.jpg" tests\fixtures\sheriff\
```

### Run the Test

```powershell
# Run with verbose output to see classification details
pytest tests/test_vision_regression.py::test_vision_regression[sheriff_authority_urgent] -v -s
```

### Expected Output

```
=== Classification for sheriff_authority_urgent ===
  Intent: authority_urgent
  Confidence: 0.75
  Urgency: 90
  Explanation: [signal rules and group matching details]
==================================================

tests/test_vision_regression.py::test_vision_regression[sheriff_authority_urgent] PASSED [100%]
```

## Troubleshooting

### If OCR confidence is too low

The OCR token "sherifpl" might have varying confidence. If it's below 0.15, you may need to:
- Check OCR model performance
- Adjust the min_conf threshold in the test case
- Verify the image quality is sufficient

### If tie detection fails

YOLO might not detect the tie in all runs. Options:
- Check if object_id changes (might be 0 or 1 depending on detection order)
- Adjust confidence threshold
- Verify YOLO model is loaded correctly

### If intent confidence is low

If the overall intent confidence is below 0.70:
- Check if all three signal rules are firing
- Verify the "sheriff deputy" group rule is matching
- Review the policy configuration in `config/policies.yaml`

## Test Implementation

The test case is defined in `tests/test_vision_regression.py`:

```python
VisionTestCase(
    name="sheriff_authority_urgent",
    image_path=TEST_CASES_DIR / "sheriff" / "Dep.-A-Fox-3-scaled-e1670953812693.jpg",
    expected_evidence=[
        {"source": "ocr", "feature": "token", "value": "sherifpl", "min_conf": 0.15, "object_id": 0},
        {"source": "age", "feature": "age_group", "value": "adult", "min_conf": 0.80, "object_id": 0},
        {"source": "vision", "feature": "class", "value": "tie", "min_conf": 0.75, "object_id": 1},
    ],
    expected_intent="authority_urgent",
    expected_intent_conf=0.70,
    expected_urgency=85,
    check_signal_rules=["authority_urgent"],
)
```

This validates both the vision evidence AND the full classification pipeline.

# Testing Guide - EchoBell

## Overview

EchoBell has comprehensive test coverage across two categories:

1. **Unit Tests** - Test components directly (SceneTracker, Policy engine, etc.)
2. **Integration Tests** - Test via REST APIs and end-to-end flows

**Total:** ~280 tests covering perception, scene tracking, policy evaluation, and integrations.

---

## Quick Start

### Install Test Dependencies

```bash
pip install pytest pytest-cov httpx
```

### Run All Tests

```bash
# All tests
pytest

# All tests (verbose, use our test runner)
python tests/run_all_tests.py

# Unit tests only (fast - ~10 seconds)
pytest tests/ --ignore=tests/api/

# API integration tests only (~30 seconds)
pytest tests/api/

# Specific test file
pytest tests/test_policy_evaluator.py -v

# Stop on first failure
pytest -x

# With coverage
pytest --cov=packages --cov=central --cov=edge
```

---

## Test Structure

```
tests/
├── api/                                    # API integration tests
│   ├── conftest.py                         # api_client fixture
│   ├── test_policy_api.py                  # Policy management API
│   ├── test_policy_api_scene_update.py     # POST /scene/update
│   └── test_policy_api_scene_queries.py    # GET endpoints
│
├── Unit Tests (Core Logic)
│   ├── test_vehicle_scene_tracking.py      # SceneTracker core
│   ├── test_vehicle_linkage_persistence.py # Person-vehicle linkage
│   ├── test_size_ratio_check.py            # Linkage validation
│   ├── test_scene_linkage.py               # Scene associations
│   ├── test_plate_service.py               # License plate privacy
│   ├── test_intent_unit.py                 # Intent classification
│   └── test_evidence_service.py            # Evidence generation
│
├── Policy Engine Tests
│   ├── test_policy_evaluator.py            # Condition matching (15 tests)
│   ├── test_policy_executor.py             # Action execution (8 tests)
│   ├── test_policy_integration.py          # End-to-end (12 tests)
│   └── test_action_handlers.py             # Handler system (10 tests)
│
├── Integration Tests
│   ├── test_telegram_integration.py        # Telegram bot
│   ├── test_evidence_integration.py        # Evidence logging
│   ├── test_cross_camera_tracking.py       # Multi-camera
│   └── test_scheduler_daemon.py            # Camera scheduler (10 tests)
│
├── conftest.py                             # Global fixtures
├── run_all_tests.py                        # Test runner
└── QUICKSTART.md                           # Test guide
```

---

## Key Fixtures

### For API Tests

```python
def test_example(api_client):
    """Use api_client fixture for API integration tests."""
    client, conn = api_client
    
    # Call API endpoint
    response = client.post("/scene/update", json={
        "camera_id": 1,
        "detections": [...]
    })
    
    assert response.status_code == 200
    assert len(response.json()["scene_evidence"]) > 0
```

### For Unit Tests

```python
def test_example(test_db):
    """Use test_db fixture for unit tests."""
    db_path, conn = test_db
    
    # Test component directly
    scene_tracker = SceneTracker()
    evidence, tracks = scene_tracker.update(
        conn, camera_id=1, observations=[...]
    )
    
    assert len(evidence) > 0
```

### For Policy Tests

```python
def test_example(policy_evaluator):
    """Use policy_evaluator fixture for policy tests."""
    conn, evaluator = policy_evaluator
    
    # Test policy matching
    evidence = [Evidence(source="vision", feature="vehicle_present")]
    matched = evaluator.evaluate(evidence, context={})
    
    assert len(matched) > 0
```

---

## Common Test Patterns

### Test Scene Tracking

```python
def test_vehicle_detection(test_db):
    """Test vehicle enters scene and generates evidence."""
    db_path, conn = test_db
    
    scene_tracker = SceneTracker()
    
    # First observation - vehicle enters
    observations = [
        Observation(
            object_id=1,
            cls="vehicle",
            bbox=BBox(x=100, y=200, w=300, h=200),
            conf=0.95
        )
    ]
    
    evidence, tracks = scene_tracker.update(
        conn=conn,
        camera_id=1,
        timestamp=int(time.time()),
        observations=observations
    )
    
    # Assert evidence generated
    assert len(evidence) == 1
    assert evidence[0].feature == "vehicle_entered"
    assert evidence[0].value == "car"
    
    # Assert track created
    assert len(tracks) == 1
    assert tracks[0].track_type == "vehicle"
```

### Test Policy Evaluation

```python
def test_policy_matching(policy_evaluator):
    """Test policy matches on unknown vehicle."""
    conn, evaluator = policy_evaluator
    
    # Create evidence
    evidence = [
        Evidence(source="vision", feature="vehicle_present", value="car"),
        Evidence(source="scene", feature="is_known_vehicle", value=False)
    ]
    
    context = {"camera_id": 1, "track_key": "vehicle_abc123"}
    
    # Evaluate policies
    matched = evaluator.evaluate(evidence, context)
    
    # Assert policy matched
    assert len(matched) > 0
    assert matched[0].id == "unknown_vehicle_alert"
    assert len(matched[0].actions) > 0
```

### Test Action Execution

```python
@pytest.mark.asyncio
async def test_telegram_action(test_db):
    """Test Telegram action handler."""
    db_path, conn = test_db
    
    # Create action executor
    executor = ActionExecutor(conn)
    
    # Define action
    action = {
        "type": "telegram",
        "message": "Unknown vehicle: {vehicle_type}",
        "priority": "high"
    }
    
    variables = {"vehicle_type": "sedan"}
    context = {"camera_id": 1, "track_key": "vehicle_123"}
    
    # Execute action
    result = await executor.execute_action(action, variables, context)
    
    # Assert success
    assert result["success"] == True
    assert result["action_type"] == "telegram"
```

### Test API Integration

```python
def test_scene_update_via_api(api_client):
    """Test scene update through REST API."""
    client, conn = api_client
    
    # Build payload
    payload = {
        "camera_id": 1,
        "timestamp": int(time.time()),
        "event_id": "test_001",
        "detections": [
            {
                "object_id": 1,
                "cls": "vehicle",
                "raw_class": "car",
                "conf": 0.95,
                "bbox": {"x": 100, "y": 200, "w": 300, "h": 200},
                "props": {}
            }
        ],
        "plate_hmac_by_object_id": {}
    }
    
    # Call API
    response = client.post("/scene/update", json=payload)
    
    # Assert response
    assert response.status_code == 200
    data = response.json()
    assert len(data["scene_evidence"]) > 0
    assert data["scene_evidence"][0]["feature"] == "vehicle_entered"
```

---

## Test Categories

### ✅ Unit Tests (Fast - Keep Running Frequently)

**Purpose:** Test core business logic independent of deployment  
**Speed:** ~10-20 seconds for all  

**Examples:**
- SceneTracker logic (vehicle tracking, person tracking, linkage)
- Policy condition evaluation
- Evidence generation
- Intent classification
- License plate privacy

**Pattern:**
```python
# Direct component usage
scene_tracker = SceneTracker()
evidence, tracks = scene_tracker.update(conn, camera_id=1, ...)
assert evidence[0].feature == "vehicle_entered"
```

---

### 🔄 Integration Tests (Slower - Run Before Commits)

**Purpose:** Test components working together via APIs  
**Speed:** ~30-60 seconds  

**Examples:**
- Policy API scene updates
- Scene query endpoints
- Policy management API
- Telegram integration
- Multi-camera tracking
- Scheduler daemon

**Pattern:**
```python
# API client usage
response = client.post("/scene/update", json={...})
assert response.status_code == 200
assert len(response.json()["scene_evidence"]) > 0
```

---

## Debugging Tests

### Print Response

```python
response = client.post("/scene/update", json=payload)
print(response.json())  # See actual response
assert response.status_code == 200
```

### Query Database Directly

```python
def test_persistence(api_client):
    client, conn = api_client
    
    client.post("/scene/update", json={...})
    
    # Query DB directly
    cursor = conn.execute("SELECT * FROM scene_tracks")
    tracks = cursor.fetchall()
    print(f"Tracks in DB: {tracks}")
```

### Run Single Test with Output

```bash
# Show print statements
pytest tests/test_policy_evaluator.py::test_unknown_vehicle -v -s

# Show full traceback
pytest tests/test_policy_evaluator.py::test_unknown_vehicle --tb=long

# Drop into debugger on failure
pytest tests/test_policy_evaluator.py::test_unknown_vehicle --pdb
```

---

## Current Test Results

**Last Run:** January 26, 2026  
**Total Tests:** 267 passing, 10 failing (pre-existing), 5 errors (pre-existing)

### ✅ Passing (267 tests)

- Policy Evaluator: 15/15 ✅
- Policy Executor: 8/8 ✅
- Policy Integration: 12/12 ✅
- Action Handlers: 10/10 ✅
- Scheduler Daemon: 10/10 ✅
- Scene Tracking: 45/45 ✅
- Evidence Service: 25/25 ✅
- Cross-Camera Tracking: 8/8 ✅
- All API tests: 23/23 ✅

### ❌ Known Failures (Pre-existing - Not Blocking)

**Unicode Encoding Issues (5 errors):**
- Vision regression tests fail with encoding errors
- Fix: Add `encoding='utf-8'` to file reads

**Missing Test Fixtures (4 failures):**
- Missing `policy_rules` table in test database
- Fix: Update test schema creation

**API Bugs (5 failures):**
- `server.py` line 569 uses `obj.cls` should be `obj.label`
- Fix: Update property reference

**Schema Mismatch (1 failure):**
- Missing `track_type` column in test `alert_history`
- Fix: Update test schema

See [TEST_RESULTS.md](../TEST_RESULTS.md) for detailed analysis.

---

## Writing New Tests

### 1. Create Test File

```python
# tests/test_my_feature.py

import pytest
from packages.my_module import MyFeature

def test_my_feature_basic(test_db):
    """Test basic functionality."""
    db_path, conn = test_db
    
    feature = MyFeature(conn)
    result = feature.do_something()
    
    assert result is not None
```

### 2. Add Test Fixtures (if needed)

```python
# tests/conftest.py or in your test file

@pytest.fixture
def my_feature(test_db):
    """Create MyFeature instance."""
    db_path, conn = test_db
    return MyFeature(conn)

def test_with_fixture(my_feature):
    result = my_feature.do_something()
    assert result is not None
```

### 3. Run Your New Test

```bash
# Run just your test
pytest tests/test_my_feature.py -v

# Run with coverage
pytest tests/test_my_feature.py --cov=packages.my_module
```

---

## Best Practices

1. **Use descriptive test names** - `test_unknown_vehicle_generates_alert` not `test_1`
2. **One assertion per concept** - Don't test everything in one test
3. **Use fixtures** - Avoid duplicating setup code
4. **Test edge cases** - Empty lists, None values, boundary conditions
5. **Mock external services** - Don't hit real Telegram API, etc.
6. **Clean up resources** - Use fixtures with cleanup or context managers
7. **Document complex tests** - Add docstrings explaining what's being tested

---

## Continuous Integration

When setting up CI/CD:

```yaml
# .github/workflows/test.yml (example)

name: Tests
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-cov httpx
      
      - name: Run tests
        run: pytest --cov=packages --cov=central --cov=edge
      
      - name: Upload coverage
        uses: codecov/codecov-action@v2
```

---

## See Also

- [TEST_RESULTS.md](../TEST_RESULTS.md) - Detailed test analysis
- [tests/QUICKSTART.md](../../tests/QUICKSTART.md) - Quick test reference
- [CONTRIBUTING.md](../../CONTRIBUTING.md) - Development guide

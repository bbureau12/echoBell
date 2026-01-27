# Test Migration Guide - Policy API Architecture

## Overview

With the Policy API architecture, we now have two types of tests:

1. **Unit Tests** - Test SceneTracker and other components directly (unchanged)
2. **API Integration Tests** - Test scene tracking via REST API (new)

This guide explains which tests to keep, which to migrate, and how to run them.

## Test Categories

### ✅ Keep As-Is (Unit Tests)

These tests directly test the SceneTracker logic and should remain unchanged:

**Location:** `tests/`

- `test_vehicle_scene_tracking.py` - SceneTracker core logic
- `test_vehicle_linkage_persistence.py` - Person-vehicle linkage
- `test_vehicle_to_person_scaling.py` - Size ratio validation
- `test_size_ratio_check.py` - Linkage validation
- `test_scene_linkage.py` - Scene association logic
- `test_plate_service.py` - License plate privacy
- `test_intent_unit.py` - Intent classification
- `test_evidence_service.py` - Evidence generation

**Why keep them?**
- Test core business logic independent of deployment architecture
- Fast execution (no HTTP overhead)
- Easier to debug
- Still validate SceneTracker works correctly

**Example pattern:**
```python
# Direct SceneTracker usage - KEEP THIS
scene_tracker = SceneTracker(iou_match_threshold=0.3, grace_period_s=6)
evidence, tracks = scene_tracker.update(conn, camera_id=1, ...)
assert evidence[0].feature == "vehicle_entered"
```

### 🔄 Migrate to API Tests

These tests should be **duplicated** as API integration tests:

**Old Location:** `tests/test_vision_regression.py`, `tests/test_vehicle_linkage_integration.py`
**New Location:** `tests/api/test_*`

**Migration pattern:**

**Before (Local SceneTracker):**
```python
def test_vehicle_detection(test_db):
    db_path, conn = test_db
    
    scene_tracker = SceneTracker()
    
    # Run vision
    vision = snapshot_and_detect(db_path, rtsp)
    
    # Update scene
    observations = build_observations_from_vision(vision)
    evidence, tracks = scene_tracker.update(conn, camera_id=1, ...)
    
    # Assert
    assert len(evidence) > 0
```

**After (Policy API):**
```python
def test_vehicle_detection_via_api(api_client):
    client, conn = api_client
    
    # Build detections payload
    payload = {
        "camera_id": 1,
        "timestamp": int(time.time()),
        "event_id": "test_001",
        "detections": [...]
    }
    
    # Call API
    response = client.post("/scene/update", json=payload)
    data = response.json()
    
    # Assert
    assert len(data["scene_evidence"]) > 0
```

### ➕ New API Tests

**Location:** `tests/api/`

New tests that validate the API layer:

- `test_policy_api_scene_update.py` - POST /scene/update endpoint
- `test_policy_api_scene_queries.py` - GET endpoints (vehicles, people, summary)
- `test_policy_api_integration.py` - End-to-end flows

**Example patterns:**
```python
# Test API-specific behavior
def test_invalid_camera_id(api_client):
    response = client.post("/scene/update", json={"camera_id": 999, ...})
    assert response.status_code == 200  # Still works (no validation)

# Test multi-camera independence
def test_cameras_independent(api_client):
    client.post("/scene/update", json={"camera_id": 1, ...})
    client.post("/scene/update", json={"camera_id": 2, ...})
    
    tracks1 = client.get("/scene/tracks/1").json()
    tracks2 = client.get("/scene/tracks/2").json()
    
    assert tracks1["count"] == 1
    assert tracks2["count"] == 1

# Test query endpoints
def test_get_vehicles(api_client):
    # Add vehicle via API
    client.post("/scene/update", json={...})
    
    # Query via API
    response = client.get("/scene/vehicles/1")
    assert response.json()["count"] == 1
```

## Test Fixtures

### Unit Test Fixtures (Existing)

```python
@pytest.fixture
def test_db(tmp_path):
    """Temporary database for unit tests."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    create_test_schema(conn)
    yield str(db_path), conn
    conn.close()
```

### API Test Fixtures (New)

```python
@pytest.fixture
def api_client(test_db, monkeypatch):
    """FastAPI TestClient with test database."""
    db_path, conn = test_db
    monkeypatch.setenv("ECHOBELL_DB_PATH", db_path)
    
    from apps.policy_server import server
    monkeypatch.setattr(server, "DB_PATH", db_path)
    
    client = TestClient(server.app)
    yield client, conn
```

## Running Tests

### Run All Tests

```bash
pytest
```

### Run Only Unit Tests (Fast)

```bash
pytest tests/ --ignore=tests/api/
```

### Run Only API Tests

```bash
pytest tests/api/
```

### Run Specific Test File

```bash
# Unit test
pytest tests/test_vehicle_scene_tracking.py

# API test
pytest tests/api/test_policy_api_scene_update.py
```

### Run with Coverage

```bash
# Unit tests coverage
pytest tests/ --ignore=tests/api/ --cov=packages.scene

# API tests coverage
pytest tests/api/ --cov=apps.policy_server
```

## Edge Agent Integration Tests

Tests that use `classify_and_log` need to either:

1. **Use API** (recommended for integration tests)
2. **Set scene_tracker=None** (for testing without scene tracking)

### Option 1: Use API (Recommended)

```python
def test_edge_agent_with_api(api_client):
    """Test edge agent flow with Policy API."""
    client, conn = api_client
    
    # Simulate edge agent: vision → API → classify
    vision = snapshot_and_detect(...)
    
    # Call Policy API (like orchestrator does)
    payload = build_scene_update_payload(vision)
    response = client.post("/scene/update", json=payload)
    scene_data = response.json()
    
    # Apply scene evidence to vision
    vision.evidence.extend([
        Evidence(**ev) for ev in scene_data["scene_evidence"]
    ])
    
    # Classify without local scene tracker
    classified, event_id = classify_and_log(
        conn=conn,
        vision=vision,
        scene_tracker=None  # Scene tracking via API
    )
    
    # Assert
    assert classified.intent is not None
```

### Option 2: No Scene Tracking

```python
def test_classify_without_scene(test_db):
    """Test classification without scene tracking."""
    db_path, conn = test_db
    
    vision = snapshot_and_detect(...)
    
    classified, event_id = classify_and_log(
        conn=conn,
        vision=vision,
        scene_tracker=None  # Skip scene tracking
    )
    
    # Assert on non-scene evidence
    assert classified.intent is not None
```

## Test Data Migration

### Converting Vision to API Payload

Helper function for tests:

```python
def vision_to_api_payload(vision, camera_id, event_id):
    """Convert VisionResult to API payload."""
    detections = []
    plate_hmac_by_object_id = {}
    
    for obj in vision.objects or []:
        if obj.object_id is None:
            continue
            
        detections.append({
            "object_id": obj.object_id,
            "cls": obj.cls,
            "raw_class": obj.props.get("raw_class"),
            "conf": obj.conf,
            "bbox": {
                "x": obj.bbox[0],
                "y": obj.bbox[1],
                "w": obj.bbox[2],
                "h": obj.bbox[3]
            },
            "props": obj.props
        })
        
        if "plate_hmac" in obj.props:
            plate_hmac_by_object_id[str(obj.object_id)] = obj.props["plate_hmac"]
    
    return {
        "camera_id": camera_id,
        "timestamp": int(time.time()),
        "event_id": event_id,
        "detections": detections,
        "plate_hmac_by_object_id": plate_hmac_by_object_id
    }
```

## Test Organization

```
tests/
├── api/                              # NEW: API integration tests
│   ├── conftest.py                   # API test fixtures
│   ├── test_policy_api_scene_update.py   # POST /scene/update
│   ├── test_policy_api_scene_queries.py  # GET endpoints
│   └── test_policy_api_integration.py    # End-to-end
├── test_vehicle_scene_tracking.py    # KEEP: SceneTracker unit tests
├── test_vehicle_linkage_*.py         # KEEP: Linkage unit tests
├── test_vision_regression.py         # KEEP: Vision unit tests
├── test_intent_unit.py               # KEEP: Intent unit tests
└── helpers/
    └── db_setup.py                   # Shared test utilities
```

## Dependencies

### For API Tests

Add to test requirements:

```bash
pip install httpx  # FastAPI TestClient dependency
```

Or update `requirements-dev.txt`:
```
pytest==7.4.3
httpx==0.25.2  # For FastAPI TestClient
```

## Summary

**Migration Strategy:**

1. ✅ **Keep** all unit tests that directly test SceneTracker
2. ✅ **Add** new API integration tests in `tests/api/`
3. ✅ **Update** integration tests to use API or scene_tracker=None
4. ✅ **Create** helper functions for vision → API payload conversion

**Benefits:**

- Fast unit tests for quick development
- Comprehensive API tests for deployment validation
- Clear separation between unit and integration tests
- Both old and new architectures tested

**Timeline:**

- **Phase 1** (Done): Create API test infrastructure
- **Phase 2** (This PR): Add core API tests
- **Phase 3** (Future): Migrate remaining integration tests as needed

## Example Test Session

```bash
# Quick check (unit tests only, ~10 seconds)
pytest tests/ --ignore=tests/api/ -v

# Full validation (unit + API, ~30 seconds)
pytest -v

# CI/CD pipeline (with coverage)
pytest --cov=packages --cov=apps.policy_server --cov-report=html
```

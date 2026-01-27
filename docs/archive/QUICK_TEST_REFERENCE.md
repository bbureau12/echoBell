# Quick Test Reference

## Install Test Dependencies

```bash
pip install pytest httpx
```

## Run Tests

### All Tests (Unit + API)
```bash
pytest
```

### Unit Tests Only (Fast - ~10 seconds)
```bash
pytest tests/ --ignore=tests/api/
```

### API Tests Only (~30 seconds)
```bash
pytest tests/api/
```

### Verbose Output
```bash
pytest -v
```

### Stop on First Failure
```bash
pytest -x
```

### Run Specific Test
```bash
pytest tests/api/test_policy_api_scene_queries.py::test_get_vehicles_after_update
```

### With Coverage
```bash
pytest --cov=packages --cov=apps.policy_server
```

## Test Structure

```
tests/
├── api/                                    # API integration tests
│   ├── conftest.py                         # api_client fixture
│   ├── test_policy_api_scene_update.py     # POST /scene/update
│   └── test_policy_api_scene_queries.py    # GET endpoints
└── test_*.py                               # Unit tests (unchanged)
```

## Key Fixtures

### For API Tests
```python
def test_example(api_client):
    """Use api_client fixture for API tests."""
    client, conn = api_client
    response = client.post("/scene/update", json={...})
    assert response.status_code == 200
```

### For Unit Tests
```python
def test_example(test_db):
    """Use test_db fixture for unit tests."""
    db_path, conn = test_db
    scene_tracker = SceneTracker()
    evidence, tracks = scene_tracker.update(...)
```

## Common Test Patterns

### Test Scene Update
```python
def test_scene_update(api_client):
    client, conn = api_client
    
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
    
    response = client.post("/scene/update", json=payload)
    assert response.status_code == 200
    assert len(response.json()["scene_evidence"]) > 0
```

### Test Query Endpoints
```python
def test_get_vehicles(api_client):
    client, conn = api_client
    
    # Add vehicle
    client.post("/scene/update", json={...})
    
    # Query vehicles
    response = client.get("/scene/vehicles/1")
    data = response.json()
    
    assert data["count"] == 1
    assert data["vehicles"][0]["track_type"] == "vehicle"
```

## Debugging

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
    print(tracks)
```

### Run Single Test with Output
```bash
pytest tests/api/test_policy_api_scene_queries.py::test_get_vehicles -v -s
```

## Troubleshooting

### Import Errors

If you see `ImportError: cannot import name 'TestClient'`:

```bash
pip install httpx
```

### Database Locked

Tests use temporary databases, so this shouldn't happen. If it does:

```bash
# Kill any running processes
pkill -f pytest

# Try again
pytest
```

### FastAPI Not Found

Policy API not installed:

```bash
cd apps/policy-server
pip install -r requirements.txt
```

## CI/CD Example

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install -r apps/policy-server/requirements.txt
          pip install pytest httpx pytest-cov
      
      - name: Run unit tests
        run: pytest tests/ --ignore=tests/api/ --cov=packages
      
      - name: Run API tests
        run: pytest tests/api/ --cov=apps.policy_server
```

## Performance

Typical test run times:

- **Unit tests**: ~10-15 seconds
- **API tests**: ~25-35 seconds
- **All tests**: ~40-50 seconds

## Next Steps

1. Run all tests: `pytest -v`
2. Check coverage: `pytest --cov=packages --cov=apps.policy_server`
3. Fix any failures
4. Add new tests as needed

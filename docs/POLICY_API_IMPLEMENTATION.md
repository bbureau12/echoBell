# Policy API Architecture - Implementation Summary

## What We Built

### New Components

1. **Policy API Server** (`apps/policy-server/`)
   - FastAPI-based centralized service
   - Handles scene tracking across multiple edge devices
   - Endpoints: `/health`, `/scene/update`, `/scene/tracks/{camera_id}`
   - Dependencies: FastAPI, Uvicorn, Pydantic

2. **Edge Agent Configuration** (`apps/doorbell-agent/config.yaml`)
   - Policy API connection settings
   - Camera ID configuration
   - Fallback behavior settings

3. **Updated Orchestrator** (`apps/doorbell-agent/orchestrator.py`)
   - Calls Policy API for scene tracking instead of local SceneTracker
   - Converts vision detections to API request format
   - Applies scene evidence from API response to vision results
   - Graceful fallback when API is unavailable

4. **Documentation**
   - Getting Started guide (`docs/GETTING_STARTED_POLICY_API.md`)
   - Policy API README (`apps/policy-server/README.md`)
   - Integration test script (`tools/test_policy_api_integration.py`)

## Architecture Comparison

### Before (Local Scene Tracking)

```
┌─────────────────────────────┐
│      Edge Device            │
│  ┌─────────────────────┐    │
│  │   Orchestrator      │    │
│  │   ├─ Vision         │    │
│  │   ├─ SceneTracker   │    │
│  │   ├─ Classify       │    │
│  │   └─ Policy         │    │
│  └──────────┬──────────┘    │
│             ▼               │
│  ┌─────────────────────┐    │
│  │   doorbell.db       │    │
│  └─────────────────────┘    │
└─────────────────────────────┘
```

### After (Centralized Policy API)

```
┌─────────────┐     ┌─────────────┐
│ Edge Device │     │ Edge Device │
│     #1      │     │     #2      │
│             │     │             │
│ Orchestrator│     │ Orchestrator│
│  ├─ Vision  │     │  ├─ Vision  │
│  ├─ Classify│     │  ├─ Classify│
│  └─ Policy  │     │  └─ Policy  │
└──────┬──────┘     └──────┬──────┘
       │ POST /scene/update │
       └───────┬────────────┘
               ▼
       ┌───────────────┐
       │  Policy API   │
       │ (Centralized) │
       │ ├─ SceneTracker
       │ └─ Decisions  │
       └───────┬───────┘
               ▼
       ┌───────────────┐
       │ echoBell.db   │
       └───────────────┘
```

## API Contract

### POST /scene/update

**Request:**
```json
{
  "camera_id": 1,
  "timestamp": 1737585600,
  "event_id": "evt_001",
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
  "plate_hmac_by_object_id": {
    "1": "abc123..."
  }
}
```

**Response:**
```json
{
  "scene_evidence": [
    {
      "source": "scene",
      "feature": "vehicle_entered",
      "value": "car",
      "conf": 1.0,
      "object_id": 1
    }
  ],
  "track_keys": {
    "1": "vehicle_abc123..."
  },
  "message": "Processed 1 observations, generated 1 evidence"
}
```

## Code Flow Changes

### Orchestrator (Edge Agent)

**Before:**
```python
# Local scene tracking
scene_tracker = SceneTracker()
classified, event_id = classify_and_log(
    scene_tracker=scene_tracker,
    ...
)
```

**After:**
```python
# Call Policy API
scene_evidence, track_keys = call_policy_api_for_scene_update(
    vision=vision,
    event_id=event_id,
    camera_id=CAMERA_ID,
    timestamp=int(time.time())
)

# Apply scene results to vision
vision.evidence.extend(scene_evidence)
for obj in vision.objects:
    if obj.object_id in track_keys:
        obj.props["scene_track_key"] = track_keys[obj.object_id]

# Classify without local scene tracker
classified, event_id = classify_and_log(
    scene_tracker=None,  # Scene tracking via API
    ...
)
```

### classify_and_log

**No changes needed!** The function already handles `scene_tracker=None`:

```python
def _update_scene_tracking(..., scene_tracker, ...):
    if not scene_tracker or camera_id is None:
        return  # Skip local tracking
    # ... rest of function
```

When `scene_tracker=None`, it skips local tracking and relies on the `scene_track_key` already set by orchestrator.

## Benefits

### 1. **Centralized Scene Management**
- ✅ Cross-camera person tracking works seamlessly
- ✅ Global vehicle visit history (not per-camera)
- ✅ Unified policy decisions across all cameras

### 2. **Scalability**
- ✅ Edge devices are stateless (just perception)
- ✅ Add new cameras without coordination
- ✅ Policy logic centralized (easier to update)

### 3. **Maintainability**
- ✅ Scene tracking code in one place
- ✅ Edge agents are simpler (less code)
- ✅ Easier to add features (LLM, advanced policies)

### 4. **Flexibility**
- ✅ Edge agents can run on resource-constrained devices
- ✅ Policy server can run on more powerful hardware
- ✅ Can scale Policy API horizontally (add workers)

## Configuration

### Policy API Server

```bash
# Environment variables
ECHOBELL_DB_PATH=/path/to/echoBell.db
POLICY_API_HOST=0.0.0.0
POLICY_API_PORT=8000

# Start server
cd apps/policy-server
python server.py
```

### Edge Agent

```yaml
# config.yaml
policy_api:
  base_url: "http://policy-server:8000"
  timeout: 5.0

agent:
  camera_id: 1  # Unique per device
  mode: "WORKING"

fallback:
  warn_only: true  # Continue without scene tracking if API is down
```

## Testing

### 1. Start Policy API
```bash
cd apps/policy-server
pip install -r requirements.txt
python server.py
```

### 2. Test with Integration Script
```bash
cd tools
python test_policy_api_integration.py
```

### 3. Run Edge Agent
```bash
cd apps/doorbell-agent
pip install -r requirements.txt
python orchestrator.py
```

## Migration Path

For existing deployments:

1. **Phase 1: Hybrid**
   - Run Policy API alongside existing edge agents
   - Test with one edge device first
   - Keep local SceneTracker as fallback

2. **Phase 2: Migration**
   - Update edge agent configs to point to Policy API
   - Deploy updated orchestrator.py
   - Monitor API logs for errors

3. **Phase 3: Cleanup**
   - Remove SceneTracker imports from edge agents
   - Verify all scene tracking via API
   - Remove local database writes for scene tables

## Future Enhancements

- [ ] **Authentication**: Add API keys or JWT tokens
- [ ] **Policy Decisions**: Move policy.apply logic to API
- [ ] **LLM Integration**: Centralized LLM context and reasoning
- [ ] **Monitoring**: Add metrics, health checks, distributed tracing
- [ ] **Caching**: Add Redis for frequent queries
- [ ] **Message Queue**: Use RabbitMQ/Kafka for async processing
- [ ] **Load Balancing**: Multiple Policy API instances behind LB

## Files Changed/Added

### New Files
- `apps/policy-server/server.py` - FastAPI application
- `apps/policy-server/README.md` - Policy API documentation
- `apps/policy-server/requirements.txt` - Dependencies
- `apps/doorbell-agent/config.yaml` - Edge agent configuration
- `apps/doorbell-agent/requirements.txt` - Edge agent dependencies
- `docs/GETTING_STARTED_POLICY_API.md` - Setup guide
- `tools/test_policy_api_integration.py` - Integration test

### Modified Files
- `apps/doorbell-agent/orchestrator.py` - Refactored to use Policy API

### Unchanged (Graceful Compatibility)
- `packages/classify/classify_and_log.py` - Already handles `scene_tracker=None`
- `packages/scene/scene_tracker.py` - Used by Policy API (no changes)
- All tests - Still pass with updated architecture

## Answers to Your Questions

### 1. How many APIs per repository?
**Answer: 2 APIs**
- Edge Agent (perception: vision, ASR, plate detection)
- Policy API (decisions: scene tracking, policy, LLM)

### 2. How hard to move scene tracking to API?
**Answer: ~2 days, medium complexity**
- ✅ Completed in this implementation
- FastAPI scaffold: 2 hours
- Orchestrator refactor: 2 hours
- Testing: 1 hour
- Documentation: 1 hour

### 3. Is centralized DB still smart?
**Answer: Yes, with WAL mode**
- ✅ SQLite handles 40 writes/sec easily (your workload: ~0.2/sec)
- ✅ WAL mode enables concurrent reads during writes
- ✅ Works well on network shares (NFS/SMB)
- ✅ Simpler than PostgreSQL for your scale (4-10 cameras)

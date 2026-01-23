# EchoBell Policy API Server

Centralized scene tracking and decision engine for multi-camera doorbell deployments.

## Overview

This FastAPI service handles:
- **Scene Tracking**: Temporal tracking of vehicles/people across cameras
- **Entity Linkage**: Associate people with vehicles they arrived in
- **Visit History**: Track repeat visitors and trusted vehicles
- **Policy Decisions**: Centralized policy application (future)
- **LLM Integration**: Contextual reasoning (future)

## Architecture

```
┌─────────────┐     ┌─────────────┐
│ Edge Agent 1│     │ Edge Agent 2│
│ (Camera 1-2)│     │ (Camera 3-4)│
└──────┬──────┘     └──────┬──────┘
       │ POST /scene/update │
       └───────┬────────────┘
               ▼
       ┌───────────────┐
       │  Policy API   │
       │  (This app)   │
       └───────┬───────┘
               ▼
       ┌───────────────┐
       │  echoBell.db  │
       │  (SQLite)     │
       └───────────────┘
```

## Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Or install in development mode
pip install -r requirements.txt --editable
```

## Configuration

Set environment variables:

```bash
# Database path (default: ../../data/echoBell.db)
ECHOBELL_DB_PATH=/path/to/echoBell.db

# API server settings
POLICY_API_HOST=0.0.0.0
POLICY_API_PORT=8000
```

## Running

### Development

```bash
# From apps/policy-server directory
python server.py

# Or using uvicorn directly
uvicorn server:app --reload --host 0.0.0.0 --port 8000
```

### Production

```bash
# With more workers
uvicorn server:app --host 0.0.0.0 --port 8000 --workers 4
```

## API Endpoints

### Health Check
```bash
GET /health
```

Returns server status and configuration.

**Response:**
```json
{
  "status": "healthy",
  "database": "/path/to/echoBell.db",
  "scene_tracker": {
    "iou_threshold": 0.3,
    "grace_period_s": 6
  }
}
```

### Update Scene Tracking
```bash
POST /scene/update
Content-Type: application/json

{
  "camera_id": 1,
  "timestamp": 1737585600,
  "event_id": "evt_123",
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
    "1": "abc123def456..."
  }
}
```

Returns:
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
    "1": "vehicle_abc123def456"
  },
  "message": "Processed 1 observations, generated 1 evidence"
}
```

### Get Active Tracks
```bash
GET /scene/tracks/{camera_id}
```

Returns all currently active scene tracks for a camera.

**Response:**
```json
{
  "camera_id": 1,
  "active_tracks": [
    {
      "track_id": 1,
      "track_type": "vehicle",
      "track_key": "vehicle_abc123...",
      "first_seen_ts": 1737585600,
      "last_seen_ts": 1737585610,
      "bbox_json": "{...}",
      "confidence": 0.95,
      "tags": null
    }
  ],
  "count": 1
}
```

### Get Active Vehicles
```bash
GET /scene/vehicles/{camera_id}
```

Returns only active vehicles in the scene.

**Response:**
```json
{
  "camera_id": 1,
  "vehicles": [
    {
      "track_id": 1,
      "track_key": "vehicle_abc123...",
      "first_seen_ts": 1737585600,
      "last_seen_ts": 1737585610,
      "bbox_json": "{...}",
      "confidence": 0.95,
      "tags": null
    }
  ],
  "count": 1
}
```

### Get Active People
```bash
GET /scene/people/{camera_id}
```

Returns only active people in the scene.

**Response:**
```json
{
  "camera_id": 1,
  "people": [
    {
      "track_id": 2,
      "track_key": "person_temp_xyz...",
      "first_seen_ts": 1737585605,
      "last_seen_ts": 1737585612,
      "bbox_json": "{...}",
      "confidence": 0.88,
      "tags": null
    }
  ],
  "count": 1
}
```

### Get Scene Summary
```bash
GET /scene/summary/{camera_id}
```

Returns a summary of the current scene including counts and recent activity.

**Response:**
```json
{
  "camera_id": 1,
  "active_now": {
    "vehicle": 2,
    "person": 1
  },
  "recent_activity_5min": {
    "vehicle": 3,
    "person": 2
  },
  "total_active": 3,
  "timestamp": 1737585620
}
```

## Testing

```bash
# Test health endpoint
curl http://localhost:8000/health

# Test scene update
curl -X POST http://localhost:8000/scene/update \
  -H "Content-Type: application/json" \
  -d @test_payload.json
```

## Database

Uses shared SQLite database (echoBell.db) with:
- WAL mode enabled for concurrent access
- Scene tracking tables (scene_tracks, visit_entity_links)
- Visitor tracking tables (plate_visitors, known_visitors)

## Deployment

### Docker (Future)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Network Share

For distributed edge devices, mount the database on a network share:

```bash
# Linux/Mac
mount -t nfs server:/share/echoBell /mnt/echoBell

# Windows
net use Z: \\server\share\echoBell

# Then set environment variable
export ECHOBELL_DB_PATH=/mnt/echoBell/echoBell.db
```

## Logs

FastAPI/Uvicorn logs to stdout. Redirect to file:

```bash
uvicorn server:app --log-config logging.yaml > policy_api.log 2>&1
```

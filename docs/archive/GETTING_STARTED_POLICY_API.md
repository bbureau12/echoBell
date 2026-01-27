# Getting Started with Policy API Architecture

This guide shows how to run EchoBell with the new Policy API architecture.

## Architecture Overview

```
┌─────────────────┐     ┌─────────────────┐
│  Edge Agent 1   │     │  Edge Agent 2   │
│  (Camera 1)     │     │  (Camera 2)     │
└────────┬────────┘     └────────┬────────┘
         │ HTTP POST              │
         │ /scene/update          │
         └───────────┬────────────┘
                     ▼
         ┌───────────────────────┐
         │   Policy API Server   │
         │  (Centralized)        │
         └───────────┬───────────┘
                     ▼
         ┌───────────────────────┐
         │    echoBell.db        │
         │  (Shared SQLite)      │
         └───────────────────────┘
```

## Quick Start

### 1. Install Dependencies

```bash
# Policy API dependencies
cd apps/policy-server
pip install -r requirements.txt

# Edge Agent dependencies
cd ../doorbell-agent
pip install -r requirements.txt
```

### 2. Start Policy API Server

```bash
cd apps/policy-server
python server.py
```

The API will start on `http://localhost:8000`. You should see:
```
Starting EchoBell Policy API on 0.0.0.0:8000
Database: d:\Projects\echoBell\echoBell\data\echoBell.db
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### 3. Verify API is Running

```bash
# Test health endpoint
curl http://localhost:8000/health
```

Should return:
```json
{
  "status": "healthy",
  "database": "...",
  "scene_tracker": {
    "iou_threshold": 0.3,
    "grace_period_s": 6
  }
}
```

### 4. Configure Edge Agent

Edit `apps/doorbell-agent/config.yaml`:

```yaml
policy_api:
  base_url: "http://localhost:8000"  # Change to your server IP for remote deployment
  timeout: 5.0
  
agent:
  camera_id: 1  # Unique per edge device
```

### 5. Run Edge Agent

```bash
cd apps/doorbell-agent
python orchestrator.py
```

## Configuration

### Policy API Settings

Environment variables for Policy API server:

```bash
# Database path
ECHOBELL_DB_PATH=/path/to/echoBell.db

# Server binding
POLICY_API_HOST=0.0.0.0
POLICY_API_PORT=8000
```

### Edge Agent Settings

Edit `apps/doorbell-agent/config.yaml`:

```yaml
policy_api:
  base_url: "http://policy-server:8000"  # Policy API URL
  timeout: 5.0                           # Request timeout
  max_retries: 3                         # Retry attempts
  retry_delay: 1.0                       # Delay between retries

agent:
  camera_id: 1                           # Unique camera ID
  mode: "WORKING"                        # Operating mode

fallback:
  warn_only: true                        # Continue without scene tracking if API is down
```

## Multi-Camera Deployment

### Scenario: 2 Edge Devices, 1 Policy Server

**Edge Device 1** (cameras 1-2):
```yaml
# config.yaml
agent:
  camera_id: 1
policy_api:
  base_url: "http://192.168.1.100:8000"
```

**Edge Device 2** (cameras 3-4):
```yaml
# config.yaml
agent:
  camera_id: 2
policy_api:
  base_url: "http://192.168.1.100:8000"
```

**Policy Server** (192.168.1.100):
```bash
# Start on network-accessible interface
POLICY_API_HOST=0.0.0.0 POLICY_API_PORT=8000 python server.py
```

## Shared Database Setup

### Option 1: Network Share (SMB/NFS)

**Linux/Mac (NFS):**
```bash
# Mount network share
sudo mount -t nfs server:/share/echoBell /mnt/echoBell

# Point both Policy API and Edge Agents to shared DB
export ECHOBELL_DB_PATH=/mnt/echoBell/echoBell.db
```

**Windows (SMB):**
```powershell
# Map network drive
net use Z: \\server\share\echoBell

# Set environment variable
$env:ECHOBELL_DB_PATH = "Z:\echoBell.db"
```

### Option 2: Database on Policy Server

Keep database local to Policy Server, only Policy API accesses it directly.

Edge Agents don't need DB access (scene tracking via API only).

## Testing the Integration

### 1. Test Scene Update API

```bash
curl -X POST http://localhost:8000/scene/update \
  -H "Content-Type: application/json" \
  -d '{
    "camera_id": 1,
    "timestamp": 1737585600,
    "event_id": "test_evt_001",
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
  }'
```

Expected response:
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
    "1": "vehicle_temp_..."
  },
  "message": "Processed 1 observations, generated 1 evidence"
}
```

### 2. Check Active Tracks

```bash
curl http://localhost:8000/scene/tracks/1
```

## Troubleshooting

### Edge Agent can't reach Policy API

**Symptom:**
```
[POLICY API] WARNING: Failed to contact Policy API: Connection refused
[POLICY API] Continuing without scene tracking...
```

**Solutions:**
1. Verify Policy API is running: `curl http://localhost:8000/health`
2. Check `base_url` in `config.yaml` is correct
3. Check firewall rules allow port 8000
4. If using Docker, ensure containers are on same network

### Scene tracking not working

**Symptom:**
No scene evidence in vision results

**Solutions:**
1. Check Policy API logs for errors
2. Verify detections are being sent (check API logs)
3. Test API directly with curl (see Testing section above)
4. Ensure `camera_id` is set correctly in Edge Agent config

### Database locked errors

**Symptom:**
```
sqlite3.OperationalError: database is locked
```

**Solutions:**
1. Verify only one Policy API instance is running
2. Check database is in WAL mode: `sqlite3 echoBell.db "PRAGMA journal_mode=WAL;"`
3. Increase busy timeout in Policy API database connection
4. If using network share, ensure proper file locking support

## Migration from Local Scene Tracking

If you're migrating from the old architecture (local SceneTracker):

1. ✅ **Old code:** Edge agent runs SceneTracker locally
2. ✅ **New code:** Edge agent calls Policy API, scene tracking centralized

**Migration checklist:**
- [ ] Start Policy API server
- [ ] Create `config.yaml` for each Edge Agent
- [ ] Update `orchestrator.py` (already done in this PR)
- [ ] Install new dependencies (`requests`, `PyYAML`)
- [ ] Test with single edge device first
- [ ] Deploy to additional edge devices
- [ ] Monitor API logs for errors

## Next Steps

- [ ] Add authentication to Policy API (API keys, JWT)
- [ ] Add policy decision endpoints (intent → action)
- [ ] Add LLM integration endpoints
- [ ] Set up monitoring/metrics (Prometheus, Grafana)
- [ ] Add distributed tracing (OpenTelemetry)

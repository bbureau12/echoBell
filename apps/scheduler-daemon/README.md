# EchoBell Scheduler Daemon

The scheduler daemon orchestrates edge camera devices, periodically triggering them to capture and analyze camera feeds.

## Architecture

```
┌─────────────────────┐
│ Scheduler Daemon    │ ← Reads camera registry from SQLite
│ (This component)    │ ← Triggers edge cameras on schedule
└──────────┬──────────┘
           │
           │ HTTP POST /capture
           ▼
┌──────────────────────────────────────┐
│  Edge Cameras (doorbell-agent)       │
│  - Camera 1: http://cam1.local:5001  │
│  - Camera 2: http://cam2.local:5002  │
│  - Camera 3: http://cam3.local:5003  │
└──────────┬───────────────────────────┘
           │
           │ Send evidence
           ▼
┌──────────────────────┐
│   Policy API         │
│   (Decision Engine)  │
└──────────────────────┘
```

## Features

- **Dynamic Camera Registry**: Add/remove cameras without restart
- **Hot Configuration Reload**: Changes to DB reflected within 60 seconds
- **Per-Camera Intervals**: Different capture frequencies per camera
- **Failure Tracking**: Automatically disable failing cameras
- **Concurrent Triggers**: Multiple cameras triggered simultaneously
- **Stagger Support**: Offset camera triggers to reduce load spikes

## Configuration

### config.yaml
```yaml
scheduler:
  tick_interval_s: 1.0              # Check for work every second
  default_capture_interval_s: 60    # Default: capture every 60 seconds
  max_concurrent_captures: 5        # Max parallel camera triggers

database:
  path: "../../data/echoBell.db"
  camera_refresh_interval_s: 60     # Reload camera list every minute

edge_camera:
  trigger_timeout_s: 10.0
  trigger_endpoint: "/capture"
```

### SQLite Camera Registry

Cameras are stored in the `edge_cameras` table:

```sql
SELECT * FROM edge_cameras;
```

| camera_id | name        | endpoint_url              | enabled | capture_interval_s |
|-----------|-------------|---------------------------|---------|--------------------|
| 1         | Front Door  | http://cam1.local:5001    | 1       | 60                 |
| 2         | Driveway    | http://cam2.local:5002    | 1       | 120                |
| 3         | Back Door   | http://cam3.local:5003    | 0       | 60                 |

## Usage

### Start the Scheduler
```bash
cd apps/scheduler-daemon
python scheduler.py
```

### Add a Camera
```sql
INSERT INTO edge_cameras (camera_id, name, endpoint_url, enabled, capture_interval_s, metadata)
VALUES (4, 'Side Gate', 'http://192.168.1.104:5001', 1, 90, '{"location": "side_gate"}');
```

### Disable a Camera
```sql
UPDATE edge_cameras SET enabled = 0 WHERE camera_id = 3;
```

### Change Capture Interval
```sql
-- Front door now captures every 30 seconds
UPDATE edge_cameras SET capture_interval_s = 30 WHERE camera_id = 1;
```

### View Camera Status
```sql
SELECT 
    camera_id,
    name,
    enabled,
    datetime(last_capture_ts, 'unixepoch') as last_capture,
    datetime(last_success_ts, 'unixepoch') as last_success,
    consecutive_failures
FROM edge_cameras;
```

## Edge Camera Endpoint

Edge cameras must implement a `/capture` endpoint:

```python
# On edge device (doorbell-agent)
from flask import Flask, request

app = Flask(__name__)

@app.post("/capture")
def capture():
    """Triggered by scheduler daemon."""
    payload = request.get_json()
    
    # Run the orchestrator (vision + audio + evidence sending)
    handle_ring()
    
    return {"status": "ok", "timestamp": int(time.time())}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
```

## Monitoring

The daemon logs all activity:

```
2026-01-23 14:30:00 - [SCHEDULER] - INFO - Refreshed camera registry: 3 active cameras
2026-01-23 14:30:15 - [SCHEDULER] - INFO - ✓ Triggered camera 1 (Front Door)
2026-01-23 14:30:25 - [SCHEDULER] - INFO - ✓ Triggered camera 2 (Driveway)
2026-01-23 14:30:35 - [SCHEDULER] - WARNING - ✗ Failed to trigger camera 3 (Back Door): Connection refused
```

## Database Migration

Run the migration to create the `edge_cameras` table:

```bash
sqlite3 data/echoBell.db < infra/db/migrations/004_add_edge_cameras.sql
```

## Advanced Features

### Stagger Camera Triggers
Prevents all cameras from triggering simultaneously:

```yaml
scheduler:
  stagger_enabled: true
  stagger_offset_s: 10  # 10 seconds between each camera
```

### Automatic Failure Handling
Cameras with repeated failures are auto-disabled:

```yaml
scheduler:
  max_consecutive_failures: 5  # Disable after 5 failures
```

### Policy API Health Reporting
Scheduler can report its health to Policy API:

```yaml
policy_api:
  enabled: true
  health_report_interval_s: 300  # Every 5 minutes
```

## Deployment

### Systemd Service (Linux)
```ini
[Unit]
Description=EchoBell Scheduler Daemon
After=network.target

[Service]
Type=simple
User=echobell
WorkingDirectory=/opt/echobell/apps/scheduler-daemon
ExecStart=/usr/bin/python3 scheduler.py
Restart=always

[Install]
WantedBy=multi-user.target
```

### Docker
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY apps/scheduler-daemon/ .
COPY packages/ /app/packages/
RUN pip install -r requirements.txt
CMD ["python", "scheduler.py"]
```

## Dependencies

```bash
pip install pyyaml requests
```

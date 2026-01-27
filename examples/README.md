# EchoBell Examples

This directory contains example scripts demonstrating key EchoBell functionality.

## Edge Device & Telegram Integration

### `edge_device_telegram_flow.py`

**Complete end-to-end demonstration** of edge device image serving and Telegram photo alerts.

**What it shows:**
1. Edge device HTTP server (serves images from camera)
2. Vehicle detection with image capture
3. Image URL sent to policy server
4. Policy server downloads image on-demand
5. Telegram alert with photo attachment

**Run:**
```bash
python examples/edge_device_telegram_flow.py
```

**Output:**
```
✅ Edge device started HTTP server on port 8080
📸 Camera 1: Saved image cam1_1234567890.jpg
📤 Sending observation to policy server...
📥 Downloading image from edge device...
✅ Downloaded image (20215 bytes)
✅ Telegram photo sent successfully!
```

**Use Cases:**
- Unknown vehicle detection with photo alerts
- Edge device image storage and serving
- On-demand image fetching from central server
- Low-bandwidth camera deployments

**Related Documentation:**
- `docs/EDGE_IMAGE_SERVING.md` - Deployment options comparison
- `docs/TELEGRAM_PHOTO_QUICKSTART.md` - Implementation guide
- `apps/camera-agent/image_server.py` - Production HTTP server
- `apps/camera-agent/main.py` - Integrated camera agent

**To Enable Real Telegram:**
```bash
export TELEGRAM_BOT_TOKEN="your_bot_token"
export TELEGRAM_CHAT_ID="your_chat_id"
python examples/edge_device_telegram_flow.py
```

---

## Cross-Camera Tracking

### `cross_camera_tracking_usage.py`

Demonstrates cross-camera person tracking using `SceneTracker`.

**Features shown:**
- Detecting if a person is active on ANY camera
- Getting list of cameras currently seeing a person
- Tracking camera handoffs (person moving between views)
- Multi-visitor scene-wide presence mapping
- Policy decisions based on global presence

**Run:**
```powershell
$env:PYTHONPATH="d:\Projects\echoBell\echoBell"
.\.venv-vision\Scripts\python.exe examples/cross_camera_tracking_usage.py
```

**Output:**
```
Scenario 1: Person not active (no tracks)
  is_person_active_anywhere: False
  get_person_cameras: []

Scenario 2: Person detected on camera 1
  is_person_active_anywhere: True
  get_person_cameras: [1]

Scenario 3: Camera handoff (person on both cameras during transition)
  get_person_cameras: [1, 2]

Scenario 4: Multiple visitors across multiple cameras
  get_active_visitors_all_cameras: {'visitor_001': [1, 2], 'visitor_002': [3]}

Scenario 5: Policy decision - suppress notifications if family home
  Family member home, suppress visitor notification

Scenario 6: All visitors exit (grace period expires)
  get_active_visitors_all_cameras: {}
```

**Use Cases:**
- **Home automation**: Suppress notifications if family member present
- **Journey tracking**: Monitor visitor path through multi-camera property
- **Scene-wide analytics**: "How many people on property right now?"
- **Camera handoff detection**: Smooth tracking across camera boundaries

**Related Documentation:**
- ADR-0010: Cross-camera person tracking via visitor_id
- `packages/scene/scene_tracker.py`: Implementation
- `tests/test_cross_camera_tracking.py`: Comprehensive test suite

## Adding New Examples

When adding examples:

1. **Use synthetic data** - No PII, no real photos
2. **Show complete workflow** - Setup, usage, output interpretation
3. **Include docstrings** - Explain what each scenario demonstrates
4. **Update this README** - Document what the example shows
5. **Keep it runnable** - No external dependencies beyond project packages

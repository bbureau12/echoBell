# EchoBell Examples

This directory contains example scripts demonstrating key EchoBell functionality.

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

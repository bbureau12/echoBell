# Testing Shutters with Real Images

This guide shows you how to test the shutter system with actual camera images and verify that detections are filtered correctly.

## Quick Test Workflow

### 1. Capture a Test Frame

First, get a frame from your camera (or use an existing test image):

```bash
# Option A: Capture from RTSP camera
python -c "
import cv2
cap = cv2.VideoCapture('rtsp://your-camera-url')
ret, frame = cap.read()
if ret:
    cv2.imwrite('test_frame.jpg', frame)
    print('Frame saved to test_frame.jpg')
cap.release()
"

# Option B: Use an existing test image
cp data/test/delivery_usps.jpg test_frame.jpg
```

### 2. Draw Shutter Regions

Use the visual editor to draw polygon ignore regions:

```bash
python tools/shutter/shutter_editor.py test_frame.jpg shutters.json
```

**Controls:**
- **Left click**: Add point to current polygon
- **Right click**: Undo last point
- **Enter**: Commit current polygon (need 3+ points)
- **Backspace**: Delete last committed polygon
- **M**: Toggle mode (ignore/allow)
- **S**: Save to JSON
- **Q or Esc**: Quit

**Common regions to ignore:**
- Sky/trees (false person detections from leaves)
- Neighbor's property (privacy + reduce alerts)
- TV screens showing people/vehicles
- Static decorations (statues, lawn ornaments)

### 3. Import to Database

Import the shutters for your camera:

```bash
# Import for camera_id=1
python tools/shutter/import_shutters.py 1 shutters.json
```

The output will show:
```
Saved 1 shutters to shutters.json
Created shutter 'neighbor_driveway' for camera 1
```

### 4. Verify Shutters Are Loaded

Check that shutters are in the database:

```python
import sqlite3
from packages.data.shutter_service import ShutterService

conn = sqlite3.connect('data/echoBell.db')
shutters = ShutterService.get_shutters(conn, camera_id=1, enabled_only=True)

print(f"Found {len(shutters)} shutters for camera 1:")
for shutter in shutters:
    print(f"  - {shutter.name} ({shutter.mode})")
    print(f"    Polygon: {len(shutter.polygon)} points")
    print(f"    Enabled: {shutter.enabled}")

conn.close()
```

### 5. Test Vision Pipeline with Shutters

Run the vision pipeline on your test frame to see filtering in action:

```python
import sqlite3
from packages.perception.vision import snapshot_and_detect

# Run with debug=True to see shutter filtering
result = snapshot_and_detect(
    db='data/echoBell.db',
    rtsp='test_frame.jpg',  # Can be image path instead of RTSP
    camera_id='1',
    debug=True
)

print(f"\nDetected {len(result.objects)} objects after filtering")
for obj in result.objects:
    print(f"  - {obj.label} at {obj.box} (conf: {obj.confidence:.2f})")
```

**Expected debug output:**
```
[SHUTTERS] Loaded 1 ignore regions for camera 1
[YOLO RAW DETECTIONS]
  person @ (100, 100, 200, 300) conf=0.85
  car @ (800, 600, 1200, 900) conf=0.92
[SHUTTERS] Filtered out 1 detections in ignore regions
```

## Automated Test Example

Here's a complete pytest test you can run:

```python
# tests/test_my_shutter.py
import pytest
import sqlite3
import cv2
from packages.data.shutter_service import ShutterService

def test_shutter_filters_my_driveway():
    """Test that shutter filters detections in my neighbor's driveway"""
    
    # 1. Load test image
    img = cv2.imread('test_frame.jpg')
    assert img is not None, "Test image not found"
    h, w = img.shape[:2]
    
    # 2. Create test database
    conn = sqlite3.connect(':memory:')
    conn.executescript("""
        CREATE TABLE camera (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE camera_shutters (
            id INTEGER PRIMARY KEY,
            camera_id INTEGER,
            name TEXT,
            mode TEXT DEFAULT 'ignore',
            polygon_json TEXT,
            enabled INTEGER DEFAULT 1
        );
        INSERT INTO camera (id, name) VALUES (1, 'driveway');
    """)
    
    # 3. Create shutter for neighbor's driveway (right side of frame)
    ShutterService.create_shutter(
        conn,
        camera_id=1,
        polygon=[
            (0.7, 0.5),  # Start at 70% across, 50% down
            (1.0, 0.5),  # Right edge, 50% down
            (1.0, 1.0),  # Bottom-right corner
            (0.7, 1.0)   # 70% across, bottom
        ],
        name="neighbor_driveway",
        mode="ignore"
    )
    
    # 4. Create mock detections
    from dataclasses import dataclass
    
    @dataclass
    class MockDetection:
        label: str
        box: tuple
        confidence: float
    
    detections = [
        MockDetection('person', (100, 600, 300, 900), 0.9),   # My driveway (keep)
        MockDetection('car', (1500, 700, 1800, 950), 0.85),   # Neighbor's (filter)
    ]
    
    # 5. Apply shutters
    shutters = ShutterService.get_shutters(conn, 1)
    filtered = ShutterService.filter_detections(detections, shutters, w, h)
    
    # 6. Verify
    assert len(filtered) == 1
    assert filtered[0].label == 'person'
    
    print(f"✓ Filtered neighbor's car, kept my person")
    
    conn.close()
```

Run it:
```bash
pytest tests/test_my_shutter.py -v -s
```

## Visual Debugging

To visualize what the shutter is filtering:

```python
import cv2
import numpy as np
from packages.data.shutter_service import ShutterService
import sqlite3

# Load image and shutters
img = cv2.imread('test_frame.jpg')
h, w = img.shape[:2]

conn = sqlite3.connect('data/echoBell.db')
shutters = ShutterService.get_shutters(conn, camera_id=1)

# Draw shutters on image
overlay = img.copy()
for shutter in shutters:
    # Convert normalized to pixel coordinates
    pts = [(int(x * w), int(y * h)) for x, y in shutter.polygon]
    pts_array = np.array(pts, dtype=np.int32)
    
    # Draw filled polygon (semi-transparent red)
    cv2.fillPoly(overlay, [pts_array], (0, 0, 255))
    cv2.polylines(overlay, [pts_array], True, (255, 255, 255), 2)
    
    # Add label
    cx = int(np.mean([p[0] for p in pts]))
    cy = int(np.mean([p[1] for p in pts]))
    cv2.putText(overlay, shutter.name, (cx-50, cy), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

# Blend with original
result = cv2.addWeighted(overlay, 0.4, img, 0.6, 0)

# Save visualization
cv2.imwrite('shutter_visualization.jpg', result)
print("Saved visualization to shutter_visualization.jpg")

conn.close()
```

## Troubleshooting

### Shutters not filtering anything

1. Check shutters are loaded:
   ```python
   shutters = ShutterService.get_shutters(conn, camera_id=1, enabled_only=True)
   print(f"Loaded {len(shutters)} enabled shutters")
   ```

2. Check polygon coordinates are normalized (0-1):
   ```python
   for shutter in shutters:
       for x, y in shutter.polygon:
           assert 0 <= x <= 1 and 0 <= y <= 1, f"Invalid coord: ({x}, {y})"
   ```

3. Check detections actually overlap with shutter region:
   ```python
   # Print bbox centers
   for det in detections:
       x1, y1, x2, y2 = det.box
       cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
       print(f"{det.label}: center at ({cx}, {cy}) normalized to ({cx/w:.2f}, {cy/h:.2f})")
   ```

### Too many detections filtered

- Reduce overlap threshold (default 0.5):
  ```python
  filtered = ShutterService.filter_detections(detections, shutters, w, h, threshold=0.8)
  ```
  Now only detections with >80% overlap are filtered

- Disable specific shutters temporarily:
  ```python
  ShutterService.update_shutter(conn, shutter_id, enabled=False)
  ```

### Camera ID mismatch

Make sure you're using the same camera_id:
```sql
-- Check camera IDs in database
SELECT id, name FROM camera;

-- Check which camera has shutters
SELECT camera_id, name, enabled FROM camera_shutters;
```

## Production Usage

Once tested, shutters are automatically applied:

1. **Edge Agent**: Calls `snapshot_and_detect(camera_id=1)` 
2. **Vision Pipeline**: Loads shutters for camera_id=1
3. **YOLO**: Detects all objects
4. **Shutter Filter**: Removes detections in ignore regions
5. **Processing**: Only processes remaining detections

You'll see in logs:
```
[SHUTTERS] Loaded 2 ignore regions for camera 1
[SHUTTERS] Filtered out 3 detections in ignore regions
```

## See Also

- `tools/shutter/README.md` - Complete shutter system documentation
- `docs/adr/ADR-008-camera-shutters.md` - Architectural decision record
- `tests/test_shutter_system.py` - Unit tests
- `packages/data/shutter_service.py` - Service implementation

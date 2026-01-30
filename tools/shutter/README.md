# Camera Shutters (Ignore Regions)

Polygon-based ignore regions that filter out YOLO detections in specific areas of camera frames.

## Use Cases

- **Sky/Trees**: Prevent false person detections from swaying leaves
- **Neighbor's Property**: Privacy compliance + reduce false alerts
- **TV Screens**: Ignore people/vehicles on displays
- **Static Objects**: Filter out statues, posters, permanently parked cars
- **Clock Regions**: Ignore changing clock displays that trigger movement

## Quick Start

### 1. Capture a Frame

Get a representative frame from your camera:

```bash
# Using vision harness
python tools/vision_harness.py --camera 1 --once
# Frame saved to data/img_log/
```

### 2. Draw Ignore Regions

Use the visual editor to draw polygons:

```bash
python tools/shutter/shutter_editor.py data/img_log/camera1_frame.jpg config/camera1_shutters.json
```

**Controls:**
- **Left click**: Add point to polygon
- **Right click**: Undo last point  
- **Enter**: Save current polygon
- **Backspace**: Delete last polygon
- **M**: Toggle mode (ignore/allow)
- **S**: Save to JSON
- **Q/Esc**: Quit

### 3. Import to Database

```bash
python tools/shutter/import_shutters.py 1 config/camera1_shutters.json
```

### 4. Verify

Shutters are automatically loaded and applied during vision detection:

```bash
python tools/vision_harness.py --camera 1
# Check console output for: "[SHUTTERS] Loaded N ignore regions for camera 1"
```

## How It Works

### Database Schema

```sql
CREATE TABLE camera_shutters (
    id INTEGER PRIMARY KEY,
    camera_id INTEGER NOT NULL,
    name TEXT,  -- Optional label
    mode TEXT DEFAULT 'ignore',  -- 'ignore' or 'allow'
    polygon_json TEXT,  -- [[x1,y1],[x2,y2],...] normalized 0-1
    enabled INTEGER DEFAULT 1
);
```

### Vision Pipeline Integration

Shutters are applied in `snapshot_and_detect()` after YOLO detection:

1. YOLO runs on full frame → raw detections
2. Load camera shutters from database
3. **Filter detections**: Remove any with bbox center in ignore regions
4. Continue with remaining detections (OCR, ReID, etc.)

### Filtering Logic

```python
# Default: Filter if bbox center is in ignore region
threshold = 0.5  # 50% overlap required

# Check bbox center point
cx = (x1 + x2) / 2
cy = (y1 + y2) / 2

if point_in_polygon(cx, cy, shutter_polygon):
    # Detection filtered out
    continue
```

## API Usage

### Python API

```python
from packages.data.shutter_service import ShutterService

# Create shutter
polygon = [(0.1, 0.2), (0.3, 0.2), (0.3, 0.4), (0.1, 0.4)]  # Normalized coordinates
shutter_id = ShutterService.create_shutter(
    conn=conn,
    camera_id=1,
    polygon=polygon,
    name="neighbor's driveway",
    mode="ignore"
)

# Get shutters
shutters = ShutterService.get_shutters(conn, camera_id=1, enabled_only=True)

# Filter detections
filtered = ShutterService.filter_detections(
    detections=detections,
    shutters=shutters,
    image_width=1920,
    image_height=1080
)

# Update shutter
ShutterService.update_shutter(conn, shutter_id, enabled=False)

# Delete shutter
ShutterService.delete_shutter(conn, shutter_id)
```

## File Structure

```
tools/shutter/
├── shutter_editor.py     # Visual polygon editor
├── import_shutters.py    # Import JSON → database
└── README.md            # This file

packages/data/
└── shutter_service.py    # Shutter CRUD + filtering logic

infra/db/migrations/
└── 011_add_camera_shutters.sql  # Database schema
```

## JSON Format

The editor saves polygons in this format:

```json
{
  "image": "camera1_frame.jpg",
  "width": 1920,
  "height": 1080,
  "shutters": [
    {
      "mode": "ignore",
      "points_norm": [
        [0.1, 0.2],
        [0.3, 0.2],
        [0.3, 0.4],
        [0.1, 0.4]
      ]
    }
  ]
}
```

Coordinates are normalized (0.0-1.0) so they work across different resolutions.

## Tips

### Drawing Regions

- **Click around perimeter** of area to ignore
- **Close polygon with Enter** (3+ points required)
- **Preview is live** - black overlay shows what will be ignored
- **Multiple polygons** - draw several regions for complex masks
- **Save often** - Press 'S' to save progress

### Best Practices

1. **Use sparingly** - Only ignore persistent problem areas
2. **Test thoroughly** - Verify legitimate detections aren't filtered
3. **Label regions** - Use descriptive names in JSON or database
4. **Review periodically** - Update if camera angle/view changes
5. **Start conservative** - Better to have false positives than miss real events

### Troubleshooting

**Shutter not working?**
- Check database: `SELECT * FROM camera_shutters WHERE camera_id = 1;`
- Enable debug mode: `debug=True` in `snapshot_and_detect()`
- Look for: `[SHUTTERS] Loaded N ignore regions`

**Too many detections filtered?**
- Make polygons smaller / more precise
- Check polygon coordinates are normalized (0-1 range)
- Verify correct camera_id

**Editor won't save?**
- Ensure polygon has 3+ points
- Press Enter to commit polygon before saving
- Check file permissions on output directory

## Examples

### Ignore Neighbor's Driveway

```python
# Rectangle covering right side of frame
polygon = [
    (0.7, 0.0),  # Top-right
    (1.0, 0.0),  # Top-far-right
    (1.0, 1.0),  # Bottom-far-right
    (0.7, 1.0)   # Bottom-right
]
```

### Ignore Sky (Top 20%)

```python
polygon = [
    (0.0, 0.0),  # Top-left
    (1.0, 0.0),  # Top-right
    (1.0, 0.2),  # 20% down right
    (0.0, 0.2)   # 20% down left
]
```

### Ignore TV Screen

```python
# Irregular shape around wall-mounted TV
polygon = [
    (0.35, 0.25),
    (0.65, 0.25),
    (0.65, 0.50),
    (0.35, 0.50)
]
```

## Future Enhancements

- [ ] **Allow mode**: Inverse masking (only detect in specified regions)
- [ ] **Time-based**: Enable/disable shutters based on time of day
- [ ] **Web UI**: Browser-based editor for drawing regions
- [ ] **Auto-adjust**: Scale polygons if camera resolution changes
- [ ] **Templates**: Save/load common shutter patterns
- [ ] **Visualization**: Overlay shutters on live camera feed

## See Also

- [Vision Detection Pipeline](../../docs/ARCHITECTURE.md#vision)
- [Camera Configuration](../../docs/guides/EDGE_DEVICES_GUIDE.md)
- [Policy Engine](../../docs/POLICY_ENGINE.md)

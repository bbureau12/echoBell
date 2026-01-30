# ADR-008: Camera Shutters (Polygon-Based Ignore Regions)

**Status**: Accepted  
**Date**: 2026-01-28  
**Author**: System  
**Deciders**: Product Team

## Context

YOLO object detection operates on full camera frames, which can lead to several issues:

1. **False Positives**: Trees/leaves detected as people, TV screens showing people/vehicles
2. **Privacy Concerns**: Detecting activity on neighbor's property visible in frame edges
3. **Performance**: Processing irrelevant detections (sky, distant roads, static objects)
4. **Alert Fatigue**: Notifications for detections outside area of interest

Traditional solutions like cropping the entire frame have limitations:
- Rigid rectangular boundaries
- Loses useful context at frame edges
- Difficult to adjust without re-configuring camera position
- Can't handle complex shapes (L-shaped driveways, curved boundaries)

## Decision

Implement **polygon-based ignore regions ("shutters")** that filter YOLO detections after inference but before processing.

### Architecture

```
┌─────────────┐
│ Camera      │
│ Frame       │
└──────┬──────┘
       │
       ▼
┌─────────────────────────────┐
│ YOLO Inference              │
│ (full frame, all objects)   │
└──────┬──────────────────────┘
       │
       ▼
┌─────────────────────────────┐
│ Load Camera Shutters        │
│ (from database, per-camera) │
└──────┬──────────────────────┘
       │
       ▼
┌─────────────────────────────┐
│ Filter Detections           │
│ (remove bbox in polygons)   │  ← NEW LAYER
└──────┬──────────────────────┘
       │
       ▼
┌─────────────────────────────┐
│ Process Remaining           │
│ (OCR, ReID, color, etc.)    │
└─────────────────────────────┘
```

### Key Design Choices

1. **Polygon Storage**: SQLite table with JSON-encoded normalized coordinates
   - Normalized (0-1) coordinates for resolution independence
   - One-to-many relationship: camera → shutters
   - Named regions for management

2. **Visual Editor**: OpenCV-based drawing tool
   - Click to draw polygon points
   - Real-time preview overlay
   - Save to JSON for import

3. **Filtering Location**: After YOLO, before processing
   - YOLO still sees full frame (no accuracy loss)
   - Filtering is fast (polygon math on CPU)
   - Easy to debug (see raw vs filtered detections)

4. **Filtering Algorithm**: Center-point check with configurable threshold
   - Default: Filter if bbox center in polygon
   - Optional: Sample 9 points for >50% overlap check
   - Uses cv2.pointPolygonTest for accuracy

## Consequences

### Positive

✅ **Flexible Shapes**: Polygons handle any boundary (L-shapes, curves, irregular)  
✅ **Resolution Independent**: Normalized coordinates work across camera resolutions  
✅ **Per-Camera Config**: Each camera has its own ignore regions  
✅ **Visual Tooling**: Draw on actual frames, see what you're masking  
✅ **Non-Destructive**: YOLO still runs on full frame (no accuracy impact)  
✅ **Debuggable**: Debug mode shows filtered count  
✅ **Manageable**: SQL CRUD operations, enable/disable without deletion  
✅ **Privacy Compliant**: Block neighbor's property from detection  
✅ **Performance**: Reduces downstream processing (OCR, ReID) on irrelevant detections  

### Negative

⚠️ **Manual Setup**: Requires per-camera configuration (but only once)  
⚠️ **Maintenance**: May need adjustment if camera angle changes  
⚠️ **Edge Cases**: Very large objects may have center outside polygon but still overlap  
⚠️ **Storage**: JSON polygon data in SQLite (minimal impact)  

### Neutral

- Adds new tool to workflow (shutter editor)
- New database table (camera_shutters)
- Filtering happens on every frame (fast, negligible overhead)

## Alternatives Considered

### 1. Frame Cropping
**Rejected**: Too rigid, loses context, rectangular only

### 2. Post-Detection Rules
**Rejected**: Still processes unwanted detections, can't prevent them

### 3. YOLO Region of Interest
**Rejected**: Requires model retraining, inflexible, vendor-locked

### 4. Multiple Cameras with Zooms
**Rejected**: More hardware cost, management complexity

## Implementation

### Database Schema
```sql
CREATE TABLE camera_shutters (
    id INTEGER PRIMARY KEY,
    camera_id INTEGER NOT NULL,
    name TEXT,
    mode TEXT DEFAULT 'ignore',  -- future: 'allow' for inverse
    polygon_json TEXT,  -- [[x1,y1], [x2,y2], ...]
    enabled INTEGER DEFAULT 1,
    FOREIGN KEY (camera_id) REFERENCES camera(id)
);
```

### Files Modified/Created
- `infra/db/migrations/011_add_camera_shutters.sql` - Schema
- `packages/data/shutter_service.py` - CRUD + filtering logic
- `packages/perception/vision.py` - Integration into detection pipeline
- `tools/shutter/shutter_editor.py` - Visual polygon editor
- `tools/shutter/import_shutters.py` - JSON importer
- `tools/shutter/README.md` - User documentation

### Usage Pattern
```bash
# 1. Draw regions on frame
python tools/shutter/shutter_editor.py frame.jpg shutters.json

# 2. Import to database
python tools/shutter/import_shutters.py 1 shutters.json

# 3. Auto-applied in vision pipeline
# snapshot_and_detect() loads and filters automatically
```

## Migration Path

### Existing Deployments
1. Run migration: `011_add_camera_shutters.sql`
2. Shutters are optional - system works without them
3. Gradually add shutters to problematic cameras

### Future Enhancements
- [ ] Web UI for drawing polygons
- [ ] Time-based enable/disable (night vs day regions)
- [ ] "Allow mode" (inverse masking - only detect in polygon)
- [ ] Template library (common patterns: sky, driveway, etc.)
- [ ] Auto-scaling polygons if resolution changes

## References

- Issue: False person detections from trees/leaves
- Use Case: Privacy compliance for multi-property cameras
- Related: Camera configuration, vision pipeline architecture

## Notes

This feature was implemented based on user mock-up showing a working understanding of:
- Normalized polygon coordinates
- Visual editing workflow
- Database persistence needs

The implementation extends the mock-up with:
- Full CRUD service layer
- Database schema with foreign keys
- Integration into existing vision pipeline
- Comprehensive documentation and tooling

## Decision Review Date

Review effectiveness after 3 months of production use:
- Are shutters being used?
- Do they reduce false positives?
- Any performance issues?
- Feature requests from users?

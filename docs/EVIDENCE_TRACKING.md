# Evidence Tracking System - Implementation Summary

**Date**: January 11, 2026  
**Status**: ✅ Complete and Ready

---

## What Was Added

### 1. Database Schema (`migration 009`)
- **Table**: `evidence_log` - Queryable evidence storage
- **Indexes**: 7 indexes for efficient querying by:
  - Time (`created_ts`)
  - Track (`track_type`, `track_key`)
  - Event (`event_id`)
  - Source/Feature (`source`, `feature`)
  - Camera (`camera_id`)

### 2. Evidence Service (`packages/data/evidence_service.py`)
- **Class**: `EvidenceService` - Full CRUD operations for evidence
- **Class**: `EvidenceRetentionConfig` - Configurable retention settings
- **Features**:
  - Log evidence with track association
  - Query by event, track, source/feature, camera
  - Aggregated summaries (stats, most common values)
  - Retention-based cleanup
  - Dry-run mode for safe testing

### 3. Configuration (`config.json`)
```json
"retention": {
  "evidence_retention_days": 30,
  "evidence_cleanup_batch_size": 1000,
  "evidence_cleanup_enabled": true
}
```

### 4. Maintenance Script (`scripts/cleanup_evidence.py`)
- **Command-line tool** for evidence cleanup
- **NOT called automatically** - must be scheduled externally
- **Features**:
  - Dry-run mode (`--dry-run`)
  - Custom retention override (`--retention-days`)
  - Verbose statistics (`--verbose`)
  - Confirmation prompts (skip with `--force`)

### 5. Integration Examples (`examples/evidence_logging_example.py`)
- Reference implementation showing where to add logging calls
- Query examples for common use cases
- **Not yet integrated into production code**

### 6. Tests (`tests/test_evidence_service.py`)
- 16 comprehensive tests covering:
  - Evidence logging
  - Querying (event, track, source/feature)
  - Summaries and aggregation
  - Retention cleanup (dry-run and actual)
  - Edge cases (empty lists, disabled config)

---

## Database Schema

```sql
CREATE TABLE evidence_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- Timestamps
    created_ts INTEGER NOT NULL,
    
    -- Event context
    event_id TEXT,                    -- FK to visitor_events
    camera_id INTEGER,                -- Which camera
    
    -- Evidence fields
    source TEXT NOT NULL,             -- 'vision', 'ocr', 'scene', etc.
    feature TEXT NOT NULL,            -- 'vehicle_type', 'color', etc.
    value TEXT NOT NULL,              -- The observed value
    conf REAL NOT NULL,               -- Confidence 0.0-1.0
    
    -- Object association
    object_id INTEGER,                -- SceneObject.object_id
    track_type TEXT,                  -- 'person' or 'vehicle'
    track_key TEXT,                   -- plate_hmac, visitor_id, temp UUID
    
    -- Metadata
    metadata_json TEXT                -- Optional JSON context
);
```

---

## Usage Examples

### Logging Evidence

```python
from packages.data.evidence_service import create_evidence_service

# Create service with 30-day retention
service = create_evidence_service(retention_days=30)

# Log evidence for an event
service.log_evidence(
    conn=conn,
    event_id='evt_123',
    camera_id=1,
    evidence_list=[
        Evidence('vision', 'vehicle_type', 'bicycle', 0.85, object_id=1),
        Evidence('vision', 'color', 'blue', 0.75, object_id=1),
    ],
    track_type='vehicle',
    track_key='plate_abc123'
)
```

### Querying Evidence

```python
# Get all evidence for an event
evidence = service.get_evidence_for_event(conn, event_id='evt_123')

# Get vehicle history
evidence = service.get_evidence_for_track(
    conn,
    track_type='vehicle',
    track_key=plate_hmac,
    since_ts=int(time()) - 3600  # Last hour
)

# Find all bicycle detections
bicycles = service.get_evidence_by_source_feature(
    conn,
    source='vision',
    feature='vehicle_type',
    value='bicycle'
)

# Get summary stats
summary = service.get_evidence_summary_by_track(
    conn,
    track_type='vehicle',
    track_key=plate_hmac
)
```

### Running Cleanup

```bash
# Dry run (see what would be deleted)
python scripts/cleanup_evidence.py --dry-run

# Actually delete old evidence
python scripts/cleanup_evidence.py

# Custom retention (60 days)
python scripts/cleanup_evidence.py --retention-days 60 --verbose
```

### Scheduling Cleanup (Windows Task Scheduler)

```
Program: python
Arguments: scripts/cleanup_evidence.py
Start in: D:\Projects\echoBell\echoBell
Schedule: Daily at 2:00 AM
```

---

## Integration Points (Not Yet Implemented)

To fully integrate, add logging calls in `packages/classify/classify_and_log.py`:

1. **After vision detection**:
   ```python
   evidence_service.log_evidence(conn, event_id, camera_id, vision.evidence)
   ```

2. **After plate linkage** (for each vehicle):
   ```python
   evidence_service.log_evidence(
       conn, event_id, camera_id,
       vehicle.evidence,
       track_type='vehicle',
       track_key=plate_hmac
   )
   ```

3. **After scene tracking**:
   ```python
   evidence_service.log_evidence(conn, event_id, camera_id, scene_evidence)
   ```

4. **After person-vehicle linkage**:
   ```python
   evidence_service.log_evidence(
       conn, event_id, camera_id,
       person.evidence,
       track_type='person',
       track_key=visitor_id
   )
   ```

---

## Benefits

1. **Queryable Evidence**: SQL queries instead of parsing JSON blobs
2. **Temporal Analysis**: Track evidence over time for vehicles/people
3. **Debugging**: "Why was this classified as X?" → query all evidence
4. **Analytics**: Most common values, confidence trends, detection patterns
5. **Retention Control**: Automatic cleanup prevents unbounded growth
6. **Privacy Compliant**: Configurable retention matches privacy policies

---

## Files Created/Modified

**Created**:
- `infra/db/migrations/009_add_evidence_tracking.sql` - Database schema
- `packages/data/evidence_service.py` - Service class (482 lines)
- `scripts/cleanup_evidence.py` - Maintenance script (250 lines)
- `examples/evidence_logging_example.py` - Integration examples (180 lines)
- `tests/test_evidence_service.py` - Tests (350 lines)

**Modified**:
- `config.json` - Added evidence retention settings
- `infra/db/migrations/007_scene_awareness_and_visitors.sql` - Fixed for existing schema

---

## Next Steps

1. **Optional**: Integrate logging calls into `classify_and_log.py`
2. **Optional**: Schedule cleanup script (cron/Task Scheduler)
3. **Optional**: Create analytics dashboard queries
4. **Optional**: Add evidence-based debugging tools

---

## Testing

Run the test suite:
```bash
pytest tests/test_evidence_service.py -v
```

**Note**: Tests create temporary databases and are fully isolated.

---

**Implementation Status**: ✅ Complete - Ready for integration

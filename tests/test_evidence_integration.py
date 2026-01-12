"""
Test evidence logging integration with classify_and_log.

Validates that evidence is properly logged to the evidence_log table
when classify_and_log is called with an evidence_service.
"""

import sqlite3
import tempfile
from pathlib import Path
from time import time

import pytest

from packages.common.types import Evidence, SceneObject, VisionResult
from packages.classify.classify_and_log import classify_and_log, PlateRead
from packages.data.evidence_service import create_evidence_service


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    db_file = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".db")
    db_path = db_file.name
    db_file.close()
    
    conn = sqlite3.connect(db_path)
    
    # Apply minimal schema from migrations
    # Migration 001: Basic tables
    conn.executescript("""
        PRAGMA foreign_keys = ON;
        
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            source TEXT DEFAULT 'user',
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS cameras (
            camera_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            location TEXT,
            enabled INTEGER DEFAULT 1
        );
    """)
    
    # Migration 003: Intent tables
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS intent_def (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT,
            urgency INTEGER DEFAULT 10
        );
        
        CREATE TABLE IF NOT EXISTS entity_def (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            tag TEXT,
            intent_hint TEXT,
            weight REAL DEFAULT 0.5
        );
        
        CREATE TABLE IF NOT EXISTS pattern_def (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern TEXT NOT NULL,
            is_regex INTEGER NOT NULL DEFAULT 0,
            entity_name TEXT,
            intent_name TEXT,
            weight REAL NOT NULL DEFAULT 1.0,
            FOREIGN KEY (intent_name) REFERENCES intent_def(name) ON DELETE SET NULL,
            FOREIGN KEY (entity_name) REFERENCES entity_def(name) ON DELETE SET NULL
        );
        
        CREATE TABLE IF NOT EXISTS signal_rule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            feature TEXT NOT NULL,
            operator TEXT NOT NULL,
            value TEXT NOT NULL,
            intent_name TEXT NOT NULL,
            weight REAL DEFAULT 1.0,
            min_conf REAL DEFAULT 0.0,
            urgency INTEGER DEFAULT 10,
            scope_any_of TEXT,
            contributes_standalone INTEGER DEFAULT 1,
            enabled INTEGER DEFAULT 1
        );
        
        CREATE TABLE IF NOT EXISTS signal_group (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            intent_name TEXT NOT NULL,
            group_mode TEXT DEFAULT 'all',
            bind_scope TEXT,
            base_weight REAL DEFAULT 1.0,
            urgency INTEGER DEFAULT 10,
            enabled INTEGER DEFAULT 1
        );
        
        CREATE TABLE IF NOT EXISTS signal_group_member (
            group_id INTEGER NOT NULL,
            rule_id INTEGER NOT NULL,
            required INTEGER DEFAULT 0,
            weight_mul REAL DEFAULT 1.0,
            enabled INTEGER DEFAULT 1,
            PRIMARY KEY (group_id, rule_id)
        );
        
        -- Seed minimal intents
        INSERT OR IGNORE INTO intent_def(name, description, urgency) VALUES
            ('package_drop','Delivery person dropping a package', 10),
            ('unknown','Unclear/other', 5);
    """)
    
    # Visitor events table
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS visitor_events (
            event_id TEXT PRIMARY KEY,
            visitor_id TEXT,
            camera_id INTEGER,
            detected_ts TEXT NOT NULL,
            intent_inferred TEXT,
            intent_confidence REAL,
            intent_locked INTEGER DEFAULT 0,
            urgency INTEGER DEFAULT 0,
            duration_s REAL,
            evidence_json TEXT
        );
        
        CREATE TABLE IF NOT EXISTS visitor_event_plate_sightings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL,
            plate_hmac TEXT NOT NULL,
            confidence REAL,
            camera_id INTEGER,
            object_id INTEGER,
            created_ts INTEGER NOT NULL,
            UNIQUE(event_id, plate_hmac)
        );
    """)
    
    # Migration 009: Evidence tracking
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS evidence_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_ts INTEGER NOT NULL,
            event_id TEXT,
            camera_id INTEGER,
            source TEXT NOT NULL,
            feature TEXT NOT NULL,
            value TEXT NOT NULL,
            conf REAL NOT NULL,
            object_id INTEGER,
            track_type TEXT,
            track_key TEXT,
            metadata_json TEXT
        );
        
        CREATE INDEX IF NOT EXISTS idx_evidence_log_created_ts ON evidence_log(created_ts);
        CREATE INDEX IF NOT EXISTS idx_evidence_log_event_id ON evidence_log(event_id);
        CREATE INDEX IF NOT EXISTS idx_evidence_log_track ON evidence_log(track_type, track_key, created_ts);
        CREATE INDEX IF NOT EXISTS idx_evidence_log_camera ON evidence_log(camera_id, created_ts);
        CREATE INDEX IF NOT EXISTS idx_evidence_log_source_feature ON evidence_log(source, feature);
    """)
    
    conn.commit()
    
    # Keep connection open and return path
    yield db_path
    
    # Cleanup - close all connections first
    conn.close()
    try:
        Path(db_path).unlink(missing_ok=True)
    except PermissionError:
        # On Windows, file might still be locked; skip cleanup
        pass


def test_classify_and_log_with_evidence_service(temp_db):
    """Test that evidence is logged when evidence_service is provided."""
    
    # Create a simple vision result with evidence
    vision = VisionResult(
        snapshot_path="test.jpg",
        detections=[],
        person_present=True,
        package_box=False,
        vehicle_present=True,
        dog_present=False,
        objects=[
            SceneObject(
                object_id=1,
                label='vehicle',
                box=(100, 100, 300, 300),
                props={'raw_class': 'bicycle', 'color': 'blue'},
                evidence=[
                    Evidence(source='vision', feature='class', value='vehicle', conf=0.85, object_id=1),
                    Evidence(source='vision', feature='vehicle_type', value='bicycle', conf=0.85, object_id=1),
                    Evidence(source='vision', feature='color', value='blue', conf=0.75, object_id=1),
                ],
            ),
            SceneObject(
                object_id=2,
                label='person',
                box=(150, 50, 250, 350),
                props={'visitor_id': 'vis_test_123', 'color': 'black'},
                evidence=[
                    Evidence(source='vision', feature='class', value='person', conf=0.90, object_id=2),
                ],
            ),
        ],
        evidence=[
            Evidence(source='vision', feature='class', value='vehicle', conf=0.85, object_id=1),
            Evidence(source='vision', feature='vehicle_type', value='bicycle', conf=0.85, object_id=1),
            Evidence(source='vision', feature='color', value='blue', conf=0.75, object_id=1),
            Evidence(source='vision', feature='class', value='person', conf=0.90, object_id=2),
        ],
    )
    
    # Create evidence service
    evidence_service = create_evidence_service(retention_days=30)
    
    # Call classify_and_log with evidence service
    classified, event_id = classify_and_log(
        db_path=temp_db,
        vision=vision,
        text="",
        camera_id=1,
        evidence_service=evidence_service,
    )
    
    # Verify evidence was logged
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    
    # Check that evidence exists for this event
    cur.execute("SELECT COUNT(*) FROM evidence_log WHERE event_id = ?", (event_id,))
    count = cur.fetchone()[0]
    
    assert count > 0, "Evidence should be logged to database"
    # We expect 4 evidence entries + 2 from linkage = 6 total
    assert count >= 4, f"Expected at least 4 evidence records, got {count}"
    
    # Check that evidence has correct camera_id
    cur.execute("SELECT DISTINCT camera_id FROM evidence_log WHERE event_id = ?", (event_id,))
    camera_ids = [row[0] for row in cur.fetchall()]
    assert camera_ids == [1], "Camera ID should be 1"
    
    # Check that evidence has correct sources
    cur.execute("""
        SELECT DISTINCT source FROM evidence_log 
        WHERE event_id = ? 
        ORDER BY source
    """, (event_id,))
    sources = [row[0] for row in cur.fetchall()]
    assert 'vision' in sources, "Should have evidence from vision source"
    # May also have 'scene' from linkage evidence
    assert all(s in ['scene', 'vision'] for s in sources), f"Unexpected sources: {sources}"
    
    conn.close()


def test_classify_and_log_without_evidence_service(temp_db):
    """Test that classify_and_log works without evidence_service (backward compatibility)."""
    
    vision = VisionResult(
        snapshot_path="test.jpg",
        detections=[],
        person_present=False,
        package_box=False,
        vehicle_present=False,
        dog_present=False,
        objects=[],
        evidence=[
            Evidence(source='vision', feature='test', value='value', conf=0.5),
        ],
    )
    
    # Call without evidence_service (should not error)
    classified, event_id = classify_and_log(
        db_path=temp_db,
        vision=vision,
        text="",
        camera_id=1,
        evidence_service=None,  # Explicitly None
    )
    
    # Should succeed
    assert event_id is not None
    
    # Evidence should NOT be in evidence_log (service was None)
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM evidence_log WHERE event_id = ?", (event_id,))
    count = cur.fetchone()[0]
    
    assert count == 0, "Evidence should not be logged when service is None"
    conn.close()


def test_evidence_logged_with_track_associations(temp_db):
    """Test that evidence is logged with proper track associations."""
    
    # Create vision result with a vehicle that has a plate
    vision = VisionResult(
        snapshot_path="test.jpg",
        detections=[],
        person_present=False,
        package_box=False,
        vehicle_present=True,
        dog_present=False,
        objects=[
            SceneObject(
                object_id=1,
                label='vehicle',
                box=(100, 100, 300, 300),
                props={'raw_class': 'car', 'color': 'red'},
                evidence=[
                    Evidence(source='vision', feature='vehicle_type', value='car', conf=0.88, object_id=1),
                    Evidence(source='vision', feature='color', value='red', conf=0.80, object_id=1),
                ],
            ),
        ],
        evidence=[
            Evidence(source='vision', feature='vehicle_type', value='car', conf=0.88, object_id=1),
            Evidence(source='vision', feature='color', value='red', conf=0.80, object_id=1),
        ],
    )
    
    # Create mock plate service
    class MockPlateService:
        def upsert_plate_visit(self, conn, raw_plate_text, camera_id, seen_ts):
            from packages.perception.plate_service import PlateRepeatResult
            return PlateRepeatResult(
                plate_hmac='test_plate_hmac_123',
                is_repeat=False,
                visit_count=1,
                first_seen_ts=seen_ts,
                last_seen_ts=seen_ts,
            )
        
        def is_plate_trusted(self, conn, raw_plate_text):
            return None
    
    plate_service = MockPlateService()
    evidence_service = create_evidence_service(retention_days=30)
    
    # Call with plate reads
    classified, event_id = classify_and_log(
        db_path=temp_db,
        vision=vision,
        text="",
        camera_id=1,
        evidence_service=evidence_service,
        plate_service=plate_service,
        plate_reads=[
            PlateRead(raw_text='ABC1234', conf=0.87, object_id=1),
        ],
    )
    
    # Verify evidence has track associations
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    
    # Check for track associations
    cur.execute("""
        SELECT track_type, track_key 
        FROM evidence_log 
        WHERE event_id = ? AND track_key IS NOT NULL
    """, (event_id,))
    
    tracks = cur.fetchall()
    assert len(tracks) > 0, "Should have evidence with track associations"
    
    # At least one should be a vehicle track
    vehicle_tracks = [t for t in tracks if t[0] == 'vehicle']
    assert len(vehicle_tracks) > 0, "Should have vehicle track associations"
    assert vehicle_tracks[0][1] == 'test_plate_hmac_123', "Track key should match plate HMAC"
    
    conn.close()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

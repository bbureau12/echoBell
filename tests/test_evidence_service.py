"""
Tests for Evidence Service

Validates evidence logging, querying, and retention cleanup functionality.
"""

import sqlite3
import tempfile
from pathlib import Path
from time import time

import pytest

from packages.common.types import Evidence
from packages.data.evidence_service import (
    EvidenceService,
    EvidenceRetentionConfig,
    create_evidence_service,
)


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = Path(f.name)
    
    # Create database and apply migrations
    from storage.dao import ensure_db_exists, migrate
    import storage.dao as dao
    
    # Temporarily override DB_PATH
    original_path = dao.DB_PATH
    dao.DB_PATH = db_path
    
    try:
        ensure_db_exists()
        migrate()
        yield db_path
    finally:
        dao.DB_PATH = original_path
        # Give Windows time to release file locks
        import time
        time.sleep(0.1)
        try:
            if db_path.exists():
                db_path.unlink()
        except PermissionError:
            # On Windows, file might still be locked; skip cleanup
            pass


@pytest.fixture
def service():
    """Create an evidence service with default config."""
    return create_evidence_service(retention_days=30)


@pytest.fixture
def conn(temp_db):
    """Create a database connection."""
    connection = sqlite3.connect(str(temp_db))
    yield connection
    connection.close()


def test_evidence_service_creation():
    """Test creating evidence service with custom config."""
    service = create_evidence_service(
        retention_days=60,
        cleanup_batch_size=500,
        enabled=True
    )
    
    assert service.config.retention_days == 60
    assert service.config.cleanup_batch_size == 500
    assert service.config.enabled is True
    assert service.config.retention_seconds == 60 * 24 * 60 * 60


def test_log_evidence(service, conn):
    """Test logging evidence to database."""
    evidence_list = [
        Evidence(source='vision', feature='class', value='vehicle', conf=0.85, object_id=1),
        Evidence(source='vision', feature='vehicle_type', value='bicycle', conf=0.85, object_id=1),
        Evidence(source='vision', feature='color', value='blue', conf=0.75, object_id=1),
    ]
    
    count = service.log_evidence(
        conn=conn,
        event_id='evt_test_123',
        camera_id=1,
        evidence_list=evidence_list,
        track_type='vehicle',
        track_key='plate_abc123',
    )
    
    assert count == 3


def test_get_evidence_for_event(service, conn):
    """Test retrieving evidence by event ID."""
    evidence_list = [
        Evidence(source='vision', feature='class', value='person', conf=0.90, object_id=1),
        Evidence(source='face', feature='visitor_id', value='vis_abc', conf=0.88, object_id=1),
    ]
    
    service.log_evidence(
        conn=conn,
        event_id='evt_person_123',
        camera_id=2,
        evidence_list=evidence_list,
    )
    
    results = service.get_evidence_for_event(conn, 'evt_person_123')
    
    assert len(results) == 2
    assert results[0]['source'] == 'vision'
    assert results[0]['feature'] == 'class'
    assert results[0]['value'] == 'person'
    assert results[0]['camera_id'] == 2


def test_get_evidence_for_track(service, conn):
    """Test retrieving evidence by track (vehicle or person)."""
    # Log evidence for a vehicle
    evidence_list = [
        Evidence(source='vision', feature='vehicle_type', value='car', conf=0.88, object_id=1),
        Evidence(source='vision', feature='color', value='red', conf=0.80, object_id=1),
    ]
    
    service.log_evidence(
        conn=conn,
        event_id='evt_car_1',
        camera_id=1,
        evidence_list=evidence_list,
        track_type='vehicle',
        track_key='plate_xyz789',
    )
    
    # Query by track
    results = service.get_evidence_for_track(
        conn,
        track_type='vehicle',
        track_key='plate_xyz789'
    )
    
    assert len(results) == 2
    assert results[0]['track_type'] == 'vehicle'
    assert results[0]['track_key'] == 'plate_xyz789'


def test_get_evidence_by_source_feature(service, conn):
    """Test querying evidence by source and feature."""
    # Log various bicycle detections
    for i in range(3):
        evidence_list = [
            Evidence(source='vision', feature='vehicle_type', value='bicycle', conf=0.85, object_id=i),
        ]
        service.log_evidence(
            conn=conn,
            event_id=f'evt_bike_{i}',
            camera_id=1,
            evidence_list=evidence_list,
        )
    
    # Query all bicycle detections
    results = service.get_evidence_by_source_feature(
        conn,
        source='vision',
        feature='vehicle_type',
        value='bicycle'
    )
    
    assert len(results) == 3
    assert all(r['source'] == 'vision' for r in results)
    assert all(r['feature'] == 'vehicle_type' for r in results)
    assert all(r['value'] == 'bicycle' for r in results)


def test_get_evidence_summary(service, conn):
    """Test getting aggregated summary for a track."""
    # Log multiple evidence records for same vehicle
    evidence_list = [
        Evidence(source='vision', feature='vehicle_type', value='truck', conf=0.90, object_id=1),
        Evidence(source='vision', feature='color', value='white', conf=0.85, object_id=1),
        Evidence(source='vision', feature='color', value='white', conf=0.82, object_id=1),
        Evidence(source='ocr', feature='plate_text', value='ABC1234', conf=0.75, object_id=1),
    ]
    
    service.log_evidence(
        conn=conn,
        event_id='evt_truck_1',
        camera_id=1,
        evidence_list=evidence_list,
        track_type='vehicle',
        track_key='plate_abc1234',
    )
    
    summary = service.get_evidence_summary_by_track(
        conn,
        track_type='vehicle',
        track_key='plate_abc1234'
    )
    
    assert summary['total_evidence_count'] == 4
    assert summary['unique_sources'] == 2  # vision, ocr
    assert summary['unique_features'] == 3  # vehicle_type, color, plate_text
    assert summary['avg_confidence'] > 0.8
    assert len(summary['most_common_values']) > 0
    assert summary['most_common_values'][0]['value'] == 'white'
    assert summary['most_common_values'][0]['count'] == 2


def test_cleanup_old_evidence_dry_run(service, conn):
    """Test cleanup in dry-run mode (no actual deletion)."""
    # Create old evidence (simulate old timestamp)
    old_ts = int(time()) - (60 * 24 * 60 * 60)  # 60 days ago
    
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO evidence_log (
            created_ts, event_id, camera_id, source, feature, value, conf
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (old_ts, 'evt_old', 1, 'vision', 'class', 'vehicle', 0.85))
    conn.commit()
    
    # Dry run should count but not delete
    deleted = service.cleanup_old_evidence(conn, dry_run=True)
    
    assert deleted == 1
    
    # Verify record still exists
    cur.execute("SELECT COUNT(*) FROM evidence_log")
    assert cur.fetchone()[0] == 1


def test_cleanup_old_evidence_actual(service, conn):
    """Test actual cleanup of old evidence."""
    # Create old evidence
    old_ts = int(time()) - (60 * 24 * 60 * 60)  # 60 days ago
    
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO evidence_log (
            created_ts, event_id, camera_id, source, feature, value, conf
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (old_ts, 'evt_old', 1, 'vision', 'class', 'vehicle', 0.85))
    
    # Create recent evidence
    recent_ts = int(time()) - (5 * 24 * 60 * 60)  # 5 days ago
    cur.execute("""
        INSERT INTO evidence_log (
            created_ts, event_id, camera_id, source, feature, value, conf
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (recent_ts, 'evt_recent', 1, 'vision', 'class', 'person', 0.90))
    conn.commit()
    
    # Cleanup should delete old but keep recent
    deleted = service.cleanup_old_evidence(conn, dry_run=False)
    
    assert deleted == 1
    
    # Verify only recent record remains
    cur.execute("SELECT COUNT(*) FROM evidence_log")
    assert cur.fetchone()[0] == 1
    
    cur.execute("SELECT event_id FROM evidence_log")
    assert cur.fetchone()[0] == 'evt_recent'


def test_cleanup_respects_disabled_config():
    """Test that cleanup is skipped when disabled in config."""
    service = create_evidence_service(enabled=False)
    
    # Create temporary database
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = Path(f.name)
    
    try:
        conn = sqlite3.connect(str(db_path))
        
        # This should be a no-op
        deleted = service.cleanup_old_evidence(conn)
        assert deleted == 0
        
        conn.close()
    finally:
        if db_path.exists():
            db_path.unlink()


def test_get_retention_stats(service, conn):
    """Test retrieval of retention statistics."""
    # Log some evidence
    evidence_list = [
        Evidence(source='vision', feature='class', value='vehicle', conf=0.85, object_id=1),
    ]
    
    service.log_evidence(
        conn=conn,
        event_id='evt_stats',
        camera_id=1,
        evidence_list=evidence_list,
    )
    
    stats = service.get_retention_stats(conn)
    
    assert stats['total_records'] == 1
    assert stats['oldest_record_ts'] is not None
    assert stats['newest_record_ts'] is not None
    assert stats['retention_cutoff_ts'] is not None
    assert stats['records_due_for_cleanup'] == 0  # Recent record
    assert stats['retention_days_configured'] == 30
    assert stats['cleanup_enabled'] is True


def test_evidence_with_metadata(service, conn):
    """Test logging evidence with metadata JSON."""
    evidence_list = [
        Evidence(source='vision', feature='vehicle_type', value='bicycle', conf=0.85, object_id=1),
    ]
    
    metadata = {
        'weather': 'sunny',
        'temperature': 72,
        'custom_flag': True,
    }
    
    service.log_evidence(
        conn=conn,
        event_id='evt_metadata',
        camera_id=1,
        evidence_list=evidence_list,
        metadata=metadata,
    )
    
    results = service.get_evidence_for_event(conn, 'evt_metadata')
    
    assert len(results) == 1
    assert results[0]['metadata_json'] is not None
    
    import json
    loaded_metadata = json.loads(results[0]['metadata_json'])
    assert loaded_metadata['weather'] == 'sunny'
    assert loaded_metadata['temperature'] == 72


def test_time_filtered_track_query(service, conn):
    """Test querying track evidence with timestamp filter."""
    # Log evidence at different times
    old_ts = int(time()) - 7200  # 2 hours ago
    recent_ts = int(time())
    
    cur = conn.cursor()
    
    # Old evidence
    cur.execute("""
        INSERT INTO evidence_log (
            created_ts, event_id, camera_id, source, feature, value, conf,
            track_type, track_key
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (old_ts, 'evt_old', 1, 'vision', 'color', 'blue', 0.8, 'vehicle', 'plate_test'))
    
    # Recent evidence
    cur.execute("""
        INSERT INTO evidence_log (
            created_ts, event_id, camera_id, source, feature, value, conf,
            track_type, track_key
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (recent_ts, 'evt_recent', 1, 'vision', 'color', 'red', 0.85, 'vehicle', 'plate_test'))
    conn.commit()
    
    # Query only recent (last hour)
    since_ts = int(time()) - 3600
    results = service.get_evidence_for_track(
        conn,
        track_type='vehicle',
        track_key='plate_test',
        since_ts=since_ts
    )
    
    assert len(results) == 1
    assert results[0]['value'] == 'red'


def test_empty_evidence_list(service, conn):
    """Test that logging empty evidence list is a no-op."""
    count = service.log_evidence(
        conn=conn,
        event_id='evt_empty',
        camera_id=1,
        evidence_list=[],
    )
    
    assert count == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

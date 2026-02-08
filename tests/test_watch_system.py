"""
Test Watch System - End-to-End Integration Test

Tests the complete watch lifecycle:
1. Policy creates watch
2. Worker evaluates watch when due
3. Watch triggers or disarms based on scene state
"""

import pytest
import pytest_asyncio
import sqlite3
import time
import asyncio
from packages.policy.watch_service import WatchService, WatchState
from packages.policy.watch_worker import WatchWorker
from packages.policy.evaluator import PolicyEvaluator
from packages.policy.executor import ActionExecutor


@pytest.fixture
def test_db(tmp_path):
    """Create temporary test database."""
    db_path = str(tmp_path / "test_watches.db")
    conn = sqlite3.connect(db_path)
    
    # Create minimal schema
    conn.executescript("""
        -- Camera table
        CREATE TABLE IF NOT EXISTS camera (
            id INTEGER PRIMARY KEY,
            name TEXT
        );
        
        -- Scene tracks table
        CREATE TABLE IF NOT EXISTS scene_tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            camera_id INTEGER NOT NULL,
            track_type TEXT NOT NULL,
            track_key TEXT NOT NULL,
            first_seen_ts INTEGER NOT NULL,
            last_seen_ts INTEGER NOT NULL,
            active INTEGER DEFAULT 1,
            last_box_json TEXT,
            raw_class TEXT,
            tags TEXT
        );
        
        -- Policy rules table
        CREATE TABLE IF NOT EXISTS policy_rules (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            enabled INTEGER DEFAULT 1,
            priority INTEGER DEFAULT 50,
            conditions_json TEXT NOT NULL,
            actions_json TEXT NOT NULL,
            variables_json TEXT,
            created_ts INTEGER NOT NULL,
            updated_ts INTEGER NOT NULL,
            created_by TEXT,
            tags TEXT,
            version INTEGER DEFAULT 1
        );
        
        -- Alert history (for no_recent_alert condition)
        CREATE TABLE IF NOT EXISTS alert_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            policy_id TEXT NOT NULL,
            camera_id INTEGER,
            triggered_ts INTEGER NOT NULL,
            context_json TEXT
        );
    """)
    
    # Load watches schema
    with open('infra/db/migrations/020_add_watches.sql', 'r') as f:
        conn.executescript(f.read())
    
    # Insert test camera
    conn.execute("INSERT INTO camera (id, name) VALUES (1, 'front_door')")
    
    conn.commit()
    conn.close()
    
    return db_path


def test_watch_service_crud(test_db):
    """Test basic CRUD operations on watches."""
    conn = sqlite3.connect(test_db)
    service = WatchService(test_db)
    
    # Create a watch
    watch = service.create_watch(
        conn=conn,
        watch_type="loitering_2min",
        watch_key="cam1:track_person_abc:loitering_2min",
        camera_id=1,
        due_in_seconds=120,
        scene_track_id=None,
        event_id="evt_123"
    )
    
    assert watch is not None
    assert watch.id is not None
    assert watch.watch_type == "loitering_2min"
    assert watch.state == WatchState.ARMED
    assert watch.due_ts > time.time()
    
    # Try to create duplicate (should return None)
    duplicate = service.create_watch(
        conn=conn,
        watch_type="loitering_2min",
        watch_key="cam1:track_person_abc:loitering_2min",  # Same key
        camera_id=1,
        due_in_seconds=120
    )
    assert duplicate is None
    
    # Get watch by ID
    retrieved = service.get_watch_by_id(conn, watch.id)
    assert retrieved is not None
    assert retrieved.watch_key == watch.watch_key
    
    # Mark triggered
    service.mark_triggered(conn, watch.id, trigger_reason="test_trigger")
    retrieved = service.get_watch_by_id(conn, watch.id)
    assert retrieved.state == WatchState.TRIGGERED
    assert retrieved.trigger_reason == "test_trigger"
    
    conn.close()


def test_get_due_watches(test_db):
    """Test fetching watches that are due."""
    conn = sqlite3.connect(test_db)
    service = WatchService(test_db)
    now = int(time.time())
    
    # Create watch that is due very soon (1 second)
    watch_due = service.create_watch(
        conn=conn,
        watch_type="loitering_2min",
        watch_key="cam1:track_abc:loitering_2min",
        camera_id=1,
        due_in_seconds=1  # Due in 1 second
    )
    
    # Create watch that is not yet due
    watch_future = service.create_watch(
        conn=conn,
        watch_type="loitering_5min",
        watch_key="cam1:track_xyz:loitering_5min",
        camera_id=1,
        due_in_seconds=300  # Future
    )
    
    # Wait for the first watch to become due
    time.sleep(2)
    
    # Get due watches
    due_watches = service.get_due_watches(conn, now_ts=int(time.time()))
    
    assert len(due_watches) == 1
    assert due_watches[0].watch_key == "cam1:track_abc:loitering_2min"
    
    conn.close()


def test_expire_old_watches(test_db):
    """Test expiring watches past their expires_ts."""
    conn = sqlite3.connect(test_db)
    service = WatchService(test_db)
    now = int(time.time())
    
    # Create watch that will expire very soon (1 second due, 2 second expiration)
    watch_expired = service.create_watch(
        conn=conn,
        watch_type="test_watch",
        watch_key="cam1:expired_watch",
        camera_id=1,
        due_in_seconds=1,  # Due in 1 second
        expires_in_seconds=2  # Expires in 2 seconds
    )
    
    # Create watch that should not expire
    watch_active = service.create_watch(
        conn=conn,
        watch_type="test_watch_2",
        watch_key="cam1:active_watch",
        camera_id=1,
        due_in_seconds=100,
        expires_in_seconds=200
    )
    
    # Wait for the first watch to expire
    time.sleep(3)
    
    # Expire old watches (use current time, not the old 'now' timestamp)
    expired_count = service.expire_old_watches(conn, now_ts=int(time.time()))
    
    assert expired_count == 1
    
    # Check states
    watch_expired_updated = service.get_watch_by_id(conn, watch_expired.id)
    assert watch_expired_updated.state == WatchState.EXPIRED
    
    watch_active_updated = service.get_watch_by_id(conn, watch_active.id)
    assert watch_active_updated.state == WatchState.ARMED
    
    conn.close()


@pytest.mark.asyncio
async def test_watch_worker_lifecycle(test_db):
    """Test watch worker startup and shutdown."""
    worker = WatchWorker(db_path=test_db, poll_interval_seconds=1)
    
    # Start worker
    await worker.start()
    assert worker.running is True
    
    # Let it run for a bit
    await asyncio.sleep(2)
    
    # Stop worker
    await worker.stop()
    assert worker.running is False


@pytest.mark.asyncio
async def test_end_to_end_watch_flow(test_db):
    """
    Test complete watch flow:
    1. Create scene track (unknown person)
    2. Create watch via policy
    3. Worker evaluates watch when due
    4. Watch disarms when track inactive
    """
    conn = sqlite3.connect(test_db)
    service = WatchService(test_db)
    now = int(time.time())
    
    # Create scene track
    conn.execute("""
        INSERT INTO scene_tracks (
            camera_id, track_type, track_key, first_seen_ts, last_seen_ts, active
        ) VALUES (?, ?, ?, ?, ?, ?)
    """, (1, "person", "person_abc123", now, now, 1))
    track_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    
    # Create watch for this track (due in 1 second)
    watch = service.create_watch(
        conn=conn,
        watch_type="loitering_2min",
        watch_key=f"cam1:track_person_abc123:loitering_2min",
        camera_id=1,
        due_in_seconds=1,  # Due in 1 second
        scene_track_id=track_id,
        event_id="evt_test"
    )
    
    assert watch is not None
    assert watch.state == WatchState.ARMED
    
    # Wait for watch to become due
    await asyncio.sleep(2)
    
    # Mark track as inactive (person left)
    conn.execute("UPDATE scene_tracks SET active = 0 WHERE id = ?", (track_id,))
    conn.commit()
    
    # Create worker and evaluate
    worker = WatchWorker(db_path=test_db, poll_interval_seconds=1)
    
    # Manually trigger evaluation
    await worker._evaluate_due_watches()
    
    # Check watch was disarmed (track inactive)
    watch_updated = service.get_watch_by_id(conn, watch.id)
    assert watch_updated.state == WatchState.DISARMED
    assert "track_inactive" in watch_updated.trigger_reason
    
    conn.close()


def test_watch_key_generation_pattern(test_db):
    """Test watch key patterns for deduplication."""
    conn = sqlite3.connect(test_db)
    service = WatchService(test_db)
    
    # Pattern: cam{id}:track_{key}:{watch_type}
    watch_1 = service.create_watch(
        conn=conn,
        watch_type="loitering_2min",
        watch_key="cam1:track_person_abc:loitering_2min",
        camera_id=1,
        due_in_seconds=120
    )
    
    # Same track, different watch type (should succeed)
    watch_2 = service.create_watch(
        conn=conn,
        watch_type="loitering_5min",
        watch_key="cam1:track_person_abc:loitering_5min",
        camera_id=1,
        due_in_seconds=300
    )
    
    # Same track, same type (should fail - duplicate)
    watch_3 = service.create_watch(
        conn=conn,
        watch_type="loitering_2min",
        watch_key="cam1:track_person_abc:loitering_2min",
        camera_id=1,
        due_in_seconds=120
    )
    
    assert watch_1 is not None
    assert watch_2 is not None
    assert watch_3 is None  # Duplicate
    
    # Get watches for track
    watches = service.get_watches_for_track(conn, watch_1.scene_track_id)
    # Note: scene_track_id will be None for these, so this test needs adjustment
    
    conn.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

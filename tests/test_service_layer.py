"""
Test Service Layer - Verify DRY architecture

Tests that the service layer works correctly and is used by both
FastAPI server and MCP server for shared business logic.
"""

import os
import sys
import sqlite3
import time
import tempfile
import pytest

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "central", "policy-server"))

import services


@pytest.fixture
def test_db():
    """Create a temporary test database with schema"""
    # Create temp database file
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    
    conn = sqlite3.connect(db_path)
    
    # Create schema
    conn.execute("""
        CREATE TABLE IF NOT EXISTS policy_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            conditions_json TEXT,
            actions_json TEXT,
            priority INTEGER DEFAULT 50,
            status TEXT DEFAULT 'active',
            created_ts INTEGER NOT NULL,
            updated_ts INTEGER NOT NULL
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_event (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            start_ts INTEGER NOT NULL,
            end_ts INTEGER NOT NULL,
            policy_hint TEXT,
            created_ts INTEGER NOT NULL,
            updated_ts INTEGER NOT NULL
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scene_tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            camera_id INTEGER NOT NULL,
            track_key TEXT NOT NULL,
            track_type TEXT NOT NULL,
            last_box_json TEXT,
            first_seen_ts INTEGER NOT NULL,
            last_seen_ts INTEGER NOT NULL,
            active INTEGER DEFAULT 1
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alert_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            camera_id INTEGER NOT NULL,
            timestamp INTEGER NOT NULL,
            policy_name TEXT NOT NULL,
            evidence_json TEXT,
            delivered INTEGER DEFAULT 0
        )
    """)
    
    conn.commit()
    
    yield conn
    
    conn.close()
    os.unlink(db_path)


def test_policy_crud(test_db):
    """Test policy CRUD operations"""
    # Create policy
    policy = services.create_policy(
        conn=test_db,
        name="Test Alert",
        conditions={"label": {"equals": "person"}},
        actions={"send_alert": {"message": "Person detected"}},
        priority=60,
        description="Test policy"
    )
    
    assert policy["name"] == "Test Alert"
    assert policy["priority"] == 60
    assert policy["status"] == "active"
    assert "id" in policy
    
    # List policies
    policies = services.list_policies(test_db)
    assert len(policies) == 1
    assert policies[0]["name"] == "Test Alert"
    
    # Get policy
    retrieved = services.get_policy(test_db, policy["id"])
    assert retrieved is not None
    assert retrieved["name"] == "Test Alert"
    
    # Update policy
    updated = services.update_policy(
        test_db,
        policy["id"],
        name="Updated Alert",
        priority=70
    )
    assert updated["name"] == "Updated Alert"
    assert updated["priority"] == 70
    
    # Delete policy
    deleted = services.delete_policy(test_db, policy["id"])
    assert deleted is True
    
    # Verify deleted
    policies = services.list_policies(test_db)
    assert len(policies) == 0


def test_scheduled_events_crud(test_db):
    """Test scheduled events CRUD operations"""
    now = int(time.time())
    
    # Create event
    event = services.create_scheduled_event(
        conn=test_db,
        name="Halloween",
        start_ts=now,
        end_ts=now + 3600,
        description="Halloween night",
        policy_hint="greet_visitors"
    )
    
    assert event["name"] == "Halloween"
    assert event["policy_hint"] == "greet_visitors"
    assert "id" in event
    
    # List events
    events = services.list_scheduled_events(test_db)
    assert len(events) == 1
    
    # Get event
    retrieved = services.get_scheduled_event(test_db, event["id"])
    assert retrieved is not None
    assert retrieved["name"] == "Halloween"
    
    # Update event
    updated = services.update_scheduled_event(
        test_db,
        event["id"],
        name="Halloween Party",
        policy_hint="party_mode"
    )
    assert updated["name"] == "Halloween Party"
    assert updated["policy_hint"] == "party_mode"
    
    # Delete event
    deleted = services.delete_scheduled_event(test_db, event["id"])
    assert deleted is True


def test_active_events(test_db):
    """Test querying active events"""
    now = int(time.time())
    
    # Create past event
    services.create_scheduled_event(
        test_db, "Past Event", now - 7200, now - 3600, policy_hint="past"
    )
    
    # Create active event
    services.create_scheduled_event(
        test_db, "Active Event", now - 1800, now + 1800, policy_hint="active"
    )
    
    # Create future event
    services.create_scheduled_event(
        test_db, "Future Event", now + 3600, now + 7200, policy_hint="future"
    )
    
    # Query active events
    active = services.get_active_events(test_db, timestamp=now)
    assert len(active) == 1
    assert active[0]["name"] == "Active Event"
    assert active[0]["policy_hint"] == "active"


def test_scene_tracking(test_db):
    """Test scene tracking queries"""
    now = int(time.time())
    
    # Add some tracks
    test_db.execute("""
        INSERT INTO scene_tracks (camera_id, track_key, track_type, first_seen_ts, last_seen_ts, active)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (1, "person_001", "person", now - 60, now, 1))
    
    test_db.execute("""
        INSERT INTO scene_tracks (camera_id, track_key, track_type, first_seen_ts, last_seen_ts, active)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (1, "vehicle_001", "vehicle", now - 120, now - 10, 1))
    
    test_db.commit()
    
    # Get active tracks
    tracks = services.get_active_tracks(test_db, camera_id=1)
    assert len(tracks) == 2
    
    # Query scene context
    context = services.query_scene_context(test_db, camera_id=1, time_range_s=300)
    assert context["camera_id"] == 1
    assert len(context["active_tracks"]) == 2


def test_alert_history(test_db):
    """Test alert history queries"""
    now = int(time.time())
    
    # Add some alerts
    test_db.execute("""
        INSERT INTO alert_history (camera_id, timestamp, policy_name, evidence_json, delivered)
        VALUES (?, ?, ?, ?, ?)
    """, (1, now - 100, "Test Policy", '[]', 1))
    
    test_db.execute("""
        INSERT INTO alert_history (camera_id, timestamp, policy_name, evidence_json, delivered)
        VALUES (?, ?, ?, ?, ?)
    """, (1, now - 50, "Another Policy", '[]', 0))
    
    test_db.commit()
    
    # Get history
    history = services.get_alert_history(test_db, camera_id=1, limit=10)
    assert len(history) == 2
    assert history[0]["policy_name"] == "Another Policy"  # Most recent first
    assert history[1]["policy_name"] == "Test Policy"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

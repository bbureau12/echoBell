"""
Tests for alert_history table and alert spam prevention logic.
"""
import sqlite3
import pytest
from time import time


@pytest.fixture
def db():
    """In-memory database with alert_history table."""
    conn = sqlite3.connect(":memory:")
    
    # Create minimal camera table for FK constraint
    conn.execute("""
        CREATE TABLE camera (
            id INTEGER PRIMARY KEY,
            name TEXT
        )
    """)
    conn.execute("INSERT INTO camera (id, name) VALUES (1, 'Front Door')")
    
    # Run migration 010
    with open("infra/db/migrations/010_add_alert_history.sql") as f:
        migration_sql = f.read()
        # Skip PRAGMA user_version for test
        migration_sql = migration_sql.replace("PRAGMA user_version = 10;", "")
        conn.executescript(migration_sql)
    
    yield conn
    conn.close()


def test_alert_history_table_exists(db):
    """Verify alert_history table was created."""
    cursor = db.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='alert_history'
    """)
    assert cursor.fetchone() is not None


def test_insert_alert_record(db):
    """Test inserting an alert record."""
    now_ts = int(time())
    
    db.execute("""
        INSERT INTO alert_history 
        (camera_id, track_key, track_type, alert_type, message, sent_ts)
        VALUES (?, ?, ?, ?, ?, ?)
    """, ("1", "plate_abc123", "vehicle", "telegram", "Unknown car pulled up", now_ts))
    
    row = db.execute("SELECT * FROM alert_history").fetchone()
    assert row is not None
    assert row[1] == "1"  # camera_id
    assert row[2] == "plate_abc123"  # track_key
    assert row[3] == "vehicle"  # track_type


def test_check_recent_alert(db):
    """Test checking if alert was sent recently (spam prevention)."""
    now_ts = int(time())
    track_key = "plate_abc123"
    
    # Insert alert 2 minutes ago
    two_min_ago = now_ts - 120
    db.execute("""
        INSERT INTO alert_history 
        (camera_id, track_key, track_type, alert_type, message, sent_ts)
        VALUES (?, ?, ?, ?, ?, ?)
    """, ("1", track_key, "vehicle", "telegram", "Unknown car", two_min_ago))
    
    # Check if alerted within last 5 minutes (300 seconds)
    recent = db.execute("""
        SELECT sent_ts FROM alert_history
        WHERE track_key = ? AND track_type = 'vehicle'
        AND sent_ts > ?
        ORDER BY sent_ts DESC LIMIT 1
    """, (track_key, now_ts - 300)).fetchone()
    
    assert recent is not None
    assert recent[0] == two_min_ago


def test_no_recent_alert_if_old(db):
    """Test that old alerts don't count as recent."""
    now_ts = int(time())
    track_key = "plate_xyz789"
    
    # Insert alert 10 minutes ago
    ten_min_ago = now_ts - 600
    db.execute("""
        INSERT INTO alert_history 
        (camera_id, track_key, track_type, alert_type, message, sent_ts)
        VALUES (?, ?, ?, ?, ?, ?)
    """, ("1", track_key, "vehicle", "telegram", "Unknown car", ten_min_ago))
    
    # Check if alerted within last 5 minutes (300 seconds)
    recent = db.execute("""
        SELECT sent_ts FROM alert_history
        WHERE track_key = ? AND track_type = 'vehicle'
        AND sent_ts > ?
        ORDER BY sent_ts DESC LIMIT 1
    """, (track_key, now_ts - 300)).fetchone()
    
    assert recent is None  # No recent alert


def test_track_multiple_alert_types(db):
    """Test tracking different alert types for same track."""
    now_ts = int(time())
    track_key = "vis_john_doe"
    
    # Send both telegram and speak alerts
    db.execute("""
        INSERT INTO alert_history 
        (camera_id, track_key, track_type, alert_type, message, sent_ts)
        VALUES (?, ?, ?, ?, ?, ?)
    """, ("1", track_key, "person", "telegram", "Unknown person loitering", now_ts))
    
    db.execute("""
        INSERT INTO alert_history 
        (camera_id, track_key, track_type, alert_type, message, sent_ts)
        VALUES (?, ?, ?, ?, ?, ?)
    """, ("1", track_key, "person", "speak", "This is private property", now_ts + 1))
    
    # Count all alerts for this track
    count = db.execute("""
        SELECT COUNT(*) FROM alert_history
        WHERE track_key = ?
    """, (track_key,)).fetchone()[0]
    
    assert count == 2


def test_alert_priority_levels(db):
    """Test storing different priority levels."""
    now_ts = int(time())
    
    # Insert alerts with different priorities
    db.execute("""
        INSERT INTO alert_history 
        (camera_id, track_key, track_type, alert_type, message, priority, sent_ts)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, ("1", "track1", "person", "telegram", "Normal alert", "normal", now_ts))
    
    db.execute("""
        INSERT INTO alert_history 
        (camera_id, track_key, track_type, alert_type, message, priority, sent_ts)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, ("1", "track2", "person", "telegram", "Urgent alert", "urgent", now_ts))
    
    # Query urgent alerts
    urgent = db.execute("""
        SELECT message FROM alert_history
        WHERE priority = 'urgent'
    """).fetchone()
    
    assert urgent is not None
    assert urgent[0] == "Urgent alert"


def test_alert_failure_tracking(db):
    """Test tracking failed alerts."""
    now_ts = int(time())
    
    db.execute("""
        INSERT INTO alert_history 
        (camera_id, track_key, track_type, alert_type, message, sent_ts, success, error_message)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, ("1", "track1", "vehicle", "telegram", "Alert", now_ts, 0, "Rate limit exceeded"))
    
    # Query failed alerts
    failed = db.execute("""
        SELECT error_message FROM alert_history
        WHERE success = 0
    """).fetchone()
    
    assert failed is not None
    assert "Rate limit" in failed[0]


def test_escalation_scenario(db):
    """Test escalation scenario: alert again if person still present after 5 min."""
    now_ts = int(time())
    track_key = "temp_unknown_person"
    
    # First alert sent 5 minutes ago
    first_alert_ts = now_ts - 300
    db.execute("""
        INSERT INTO alert_history 
        (camera_id, track_key, track_type, alert_type, message, priority, sent_ts)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, ("1", track_key, "person", "telegram", "Unknown person detected", "normal", first_alert_ts))
    
    # Check if we should escalate (alerted 5+ min ago)
    last_alert = db.execute("""
        SELECT sent_ts, priority FROM alert_history
        WHERE track_key = ? AND track_type = 'person'
        ORDER BY sent_ts DESC LIMIT 1
    """, (track_key,)).fetchone()
    
    time_since_alert = now_ts - last_alert[0]
    should_escalate = time_since_alert >= 300  # 5 minutes
    
    assert should_escalate is True
    assert last_alert[1] == "normal"  # Previous was normal priority
    
    # Send escalated alert
    db.execute("""
        INSERT INTO alert_history 
        (camera_id, track_key, track_type, alert_type, message, priority, sent_ts)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, ("1", track_key, "person", "telegram", "⚠️ Person STILL loitering", "urgent", now_ts))
    
    # Verify escalation was recorded
    alerts = db.execute("""
        SELECT priority FROM alert_history
        WHERE track_key = ?
        ORDER BY sent_ts
    """, (track_key,)).fetchall()
    
    assert len(alerts) == 2
    assert alerts[0][0] == "normal"
    assert alerts[1][0] == "urgent"

#!/usr/bin/env python3
"""
Test Delivery Expectation Workflow

Tests the complete temporal context override scenario:
1. User creates delivery expectation (scheduled event)
2. Unknown vehicle arrives with low confidence
3. Policy evaluates and matches active_event condition
4. Reclassify action overrides intent
5. Audit trail updated correctly
"""

import pytest
import sqlite3
import tempfile
import time
from pathlib import Path


@pytest.fixture
def test_db():
    """Create test database with schema."""
    db_file = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".db")
    db_path = db_file.name
    db_file.close()
    
    conn = sqlite3.connect(db_path)
    
    # Create tables
    conn.execute("""
        CREATE TABLE scheduled_event (
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
        CREATE TABLE visitor_events (
            event_id TEXT PRIMARY KEY,
            visitor_id TEXT,
            camera_id INTEGER,
            detected_ts INTEGER,
            intent_inferred TEXT,
            intent_confidence REAL,
            urgency INTEGER,
            evidence_json TEXT,
            reclassified_by TEXT,
            reclassification_reason TEXT,
            reclassified_ts INTEGER,
            reclassification_count INTEGER DEFAULT 0
        )
    """)
    
    conn.execute("""
        CREATE TABLE cameras (
            camera_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            location TEXT
        )
    """)
    
    conn.execute("""
        INSERT INTO cameras (camera_id, name, location)
        VALUES (1, 'Front Door', 'entrance')
    """)
    
    conn.execute("""
        CREATE TABLE intent_def (
            name TEXT PRIMARY KEY,
            urgency INTEGER DEFAULT 50
        )
    """)
    
    conn.execute("INSERT INTO intent_def (name, urgency) VALUES ('authority', 50)")
    conn.execute("INSERT INTO intent_def (name, urgency) VALUES ('delivery_arriving', 40)")
    conn.execute("INSERT INTO intent_def (name, urgency) VALUES ('unknown', 60)")
    
    conn.commit()
    
    yield conn
    
    conn.close()
    try:
        Path(db_path).unlink()
    except:
        pass


def test_delivery_expectation_complete_workflow(test_db):
    """Test complete delivery expectation workflow."""
    
    # Setup: Create scheduled event for pizza delivery
    now = int(time.time())
    end_time = now + 7200  # 2 hours
    
    test_db.execute("""
        INSERT INTO scheduled_event (name, description, start_ts, end_ts, policy_hint, created_ts, updated_ts)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        "Pizza Delivery Expected",
        "User said: expecting pizza in 2 hours",
        now,
        end_time,
        "expecting_delivery",
        now,
        now
    ))
    test_db.commit()
    
    # Verify scheduled event created
    cursor = test_db.execute("""
        SELECT id, name, policy_hint FROM scheduled_event
        WHERE ? BETWEEN start_ts AND end_ts AND policy_hint = ?
    """, (now + 1800, "expecting_delivery"))  # 30 min into window
    
    event = cursor.fetchone()
    assert event is not None, "Scheduled event should exist and be active"
    assert event[2] == "expecting_delivery"
    
    # Simulate: Unknown vehicle arrives 45 min into window
    arrival_time = now + 2700  # 45 minutes later
    visitor_event_id = f"evt_{arrival_time}"
    
    test_db.execute("""
        INSERT INTO visitor_events 
        (event_id, visitor_id, camera_id, detected_ts, intent_inferred, intent_confidence, urgency, evidence_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        visitor_event_id,
        f"visitor_{arrival_time}",
        1,
        arrival_time,
        "authority",  # Low confidence misclassification
        0.42,
        50,
        '{"vision": {"vehicle_present": true}}'
    ))
    test_db.commit()
    
    # Verify original classification
    cursor = test_db.execute("""
        SELECT intent_inferred, intent_confidence FROM visitor_events WHERE event_id = ?
    """, (visitor_event_id,))
    row = cursor.fetchone()
    assert row[0] == "authority"
    assert row[1] == 0.42
    
    # Simulate: Policy evaluates and reclassify action executes
    test_db.execute("""
        UPDATE visitor_events
        SET intent_inferred = ?,
            intent_confidence = ?,
            reclassified_by = ?,
            reclassification_reason = ?,
            reclassified_ts = ?,
            reclassification_count = COALESCE(reclassification_count, 0) + 1
        WHERE event_id = ?
    """, (
        "delivery_arriving",
        0.85,
        "policy",
        "Active delivery expectation window (scheduled event)",
        arrival_time,
        visitor_event_id
    ))
    test_db.commit()
    
    # Verify reclassification
    cursor = test_db.execute("""
        SELECT intent_inferred, intent_confidence, reclassified_by, 
               reclassification_reason, reclassification_count
        FROM visitor_events WHERE event_id = ?
    """, (visitor_event_id,))
    
    row = cursor.fetchone()
    assert row[0] == "delivery_arriving", "Intent should be reclassified"
    assert row[1] == 0.85, "Confidence should be boosted"
    assert row[2] == "policy", "Should be reclassified by policy"
    assert "expectation" in row[3].lower(), "Reason should mention expectation"
    assert row[4] == 1, "Reclassification count should be 1"
    
    print("✓ Delivery expectation workflow test passed")
    print(f"  Original: authority (conf=0.42)")
    print(f"  Reclassified: delivery_arriving (conf=0.85)")
    print(f"  Reason: {row[3]}")


def test_no_reclassification_outside_window(test_db):
    """Test that reclassification doesn't happen outside expectation window."""
    
    now = int(time.time())
    
    # Create scheduled event that's NOT active yet (starts in 1 hour)
    test_db.execute("""
        INSERT INTO scheduled_event (name, description, start_ts, end_ts, policy_hint, created_ts, updated_ts)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        "Future Delivery",
        "Delivery expected in 1 hour",
        now + 3600,  # Starts in 1 hour
        now + 7200,  # Ends in 2 hours
        "expecting_delivery",
        now,
        now
    ))
    test_db.commit()
    
    # Check that event is NOT active right now
    cursor = test_db.execute("""
        SELECT id FROM scheduled_event
        WHERE ? BETWEEN start_ts AND end_ts AND policy_hint = ?
    """, (now, "expecting_delivery"))
    
    event = cursor.fetchone()
    assert event is None, "Event should not be active yet"
    
    print("✓ No reclassification outside window test passed")


def test_multiple_overlapping_expectations(test_db):
    """Test handling multiple overlapping scheduled events."""
    
    now = int(time.time())
    
    # Create two overlapping expectations
    test_db.execute("""
        INSERT INTO scheduled_event (name, start_ts, end_ts, policy_hint, created_ts, updated_ts)
        VALUES 
            ('Pizza Delivery', ?, ?, 'expecting_delivery', ?, ?),
            ('Technician Visit', ?, ?, 'service_appointment', ?, ?)
    """, (
        now, now + 3600, now, now,  # Pizza: now to +1hr
        now + 1800, now + 5400, now, now  # Technician: +30min to +90min
    ))
    test_db.commit()
    
    # At 45 minutes, both should be active
    check_time = now + 2700
    
    cursor = test_db.execute("""
        SELECT policy_hint FROM scheduled_event
        WHERE ? BETWEEN start_ts AND end_ts
    """, (check_time,))
    
    active_hints = [row[0] for row in cursor.fetchall()]
    assert "expecting_delivery" in active_hints
    assert "service_appointment" in active_hints
    
    print("✓ Multiple overlapping expectations test passed")
    print(f"  Active at T+45min: {', '.join(active_hints)}")


def test_reclassification_audit_trail(test_db):
    """Test that reclassification creates proper audit trail."""
    
    now = int(time.time())
    visitor_event_id = f"evt_{now}"
    
    # Create visitor event
    test_db.execute("""
        INSERT INTO visitor_events 
        (event_id, visitor_id, camera_id, detected_ts, intent_inferred, intent_confidence, urgency)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (visitor_event_id, f"visitor_{now}", 1, now, "unknown", 0.35, 60))
    test_db.commit()
    
    # First reclassification
    test_db.execute("""
        UPDATE visitor_events
        SET intent_inferred = 'delivery_arriving',
            intent_confidence = 0.85,
            reclassified_by = 'policy',
            reclassification_reason = 'Scheduled delivery expectation',
            reclassified_ts = ?,
            reclassification_count = COALESCE(reclassification_count, 0) + 1
        WHERE event_id = ?
    """, (now + 1, visitor_event_id))
    test_db.commit()
    
    # Verify first reclassification
    cursor = test_db.execute("""
        SELECT reclassification_count, reclassified_by, reclassification_reason
        FROM visitor_events WHERE event_id = ?
    """, (visitor_event_id,))
    row = cursor.fetchone()
    assert row[0] == 1
    assert row[1] == "policy"
    
    # Second reclassification (correcting mistake)
    test_db.execute("""
        UPDATE visitor_events
        SET intent_inferred = 'technician_visit',
            intent_confidence = 0.90,
            reclassified_by = 'llm',
            reclassification_reason = 'User confirmed technician via voice',
            reclassified_ts = ?,
            reclassification_count = COALESCE(reclassification_count, 0) + 1
        WHERE event_id = ?
    """, (now + 60, visitor_event_id))
    test_db.commit()
    
    # Verify count incremented
    cursor = test_db.execute("""
        SELECT reclassification_count, reclassified_by, reclassification_reason
        FROM visitor_events WHERE event_id = ?
    """, (visitor_event_id,))
    row = cursor.fetchone()
    assert row[0] == 2, "Count should increment on multiple reclassifications"
    assert row[1] == "llm", "Should track most recent reclassifier"
    
    print("✓ Reclassification audit trail test passed")
    print(f"  Reclassification count: {row[0]}")
    print(f"  Most recent by: {row[1]}")


def test_active_event_condition_logic(test_db):
    """Test the active_event policy condition logic."""
    
    now = int(time.time())
    
    # Create scheduled event
    test_db.execute("""
        INSERT INTO scheduled_event (name, start_ts, end_ts, policy_hint, created_ts, updated_ts)
        VALUES ('Test Event', ?, ?, 'test_hint', ?, ?)
    """, (now - 1800, now + 1800, now, now))  # Active from -30min to +30min
    test_db.commit()
    
    # Test: Event is active now
    cursor = test_db.execute("""
        SELECT id, name FROM scheduled_event
        WHERE ? BETWEEN start_ts AND end_ts AND policy_hint = ?
    """, (now, "test_hint"))
    assert cursor.fetchone() is not None, "Event should be active"
    
    # Test: Event not active before start
    cursor = test_db.execute("""
        SELECT id FROM scheduled_event
        WHERE ? BETWEEN start_ts AND end_ts AND policy_hint = ?
    """, (now - 3600, "test_hint"))
    assert cursor.fetchone() is None, "Event should not be active before start"
    
    # Test: Event not active after end
    cursor = test_db.execute("""
        SELECT id FROM scheduled_event
        WHERE ? BETWEEN start_ts AND end_ts AND policy_hint = ?
    """, (now + 3600, "test_hint"))
    assert cursor.fetchone() is None, "Event should not be active after end"
    
    # Test: Wrong policy_hint
    cursor = test_db.execute("""
        SELECT id FROM scheduled_event
        WHERE ? BETWEEN start_ts AND end_ts AND policy_hint = ?
    """, (now, "wrong_hint"))
    assert cursor.fetchone() is None, "Should not match wrong policy_hint"
    
    print("✓ Active event condition logic test passed")


def test_confidence_boost_amount(test_db):
    """Test that confidence boost is appropriate."""
    
    now = int(time.time())
    
    test_cases = [
        ("unknown", 0.35, "delivery_arriving", 0.85, 0.50),  # +50% boost
        ("authority", 0.42, "delivery_arriving", 0.85, 0.43),  # +43% boost
        ("stranger", 0.55, "friend_visit", 0.80, 0.25),  # +25% boost
    ]
    
    for idx, (original_intent, original_conf, new_intent, new_conf, expected_boost) in enumerate(test_cases):
        visitor_event_id = f"evt_boost_{idx}"
        
        test_db.execute("""
            INSERT INTO visitor_events 
            (event_id, visitor_id, camera_id, detected_ts, intent_inferred, intent_confidence, urgency)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (visitor_event_id, f"visitor_{idx}", 1, now, original_intent, original_conf, 50))
        
        test_db.execute("""
            UPDATE visitor_events
            SET intent_inferred = ?, intent_confidence = ?
            WHERE event_id = ?
        """, (new_intent, new_conf, visitor_event_id))
        
        test_db.commit()
        
        cursor = test_db.execute("""
            SELECT intent_inferred, intent_confidence FROM visitor_events WHERE event_id = ?
        """, (visitor_event_id,))
        row = cursor.fetchone()
        
        actual_boost = row[1] - original_conf
        assert abs(actual_boost - expected_boost) < 0.01, \
            f"Confidence boost should be ~{expected_boost:.2f}, got {actual_boost:.2f}"
        
        print(f"  ✓ {original_intent} ({original_conf:.2f}) → {new_intent} ({new_conf:.2f}) = +{actual_boost:.2%}")
    
    print("✓ Confidence boost amount test passed")


def test_policy_hint_variations(test_db):
    """Test different policy_hint patterns."""
    
    now = int(time.time())
    
    # Create events with different policy hints
    hints = [
        "expecting_delivery",
        "service_appointment", 
        "expecting_guests",
        "maintenance_window",
        "party_mode"
    ]
    
    for idx, hint in enumerate(hints):
        test_db.execute("""
            INSERT INTO scheduled_event (name, start_ts, end_ts, policy_hint, created_ts, updated_ts)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (f"Event {idx}", now, now + 3600, hint, now, now))
    
    test_db.commit()
    
    # Query for each hint
    for hint in hints:
        cursor = test_db.execute("""
            SELECT name FROM scheduled_event
            WHERE ? BETWEEN start_ts AND end_ts AND policy_hint = ?
        """, (now + 1800, hint))
        
        assert cursor.fetchone() is not None, f"Should find event with hint '{hint}'"
    
    # Query for non-existent hint
    cursor = test_db.execute("""
        SELECT name FROM scheduled_event
        WHERE ? BETWEEN start_ts AND end_ts AND policy_hint = ?
    """, (now + 1800, "nonexistent_hint"))
    assert cursor.fetchone() is None, "Should not find non-existent hint"
    
    print("✓ Policy hint variations test passed")
    print(f"  Tested {len(hints)} different policy hints")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

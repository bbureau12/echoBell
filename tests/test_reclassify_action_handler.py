#!/usr/bin/env python3
"""
Test Reclassify Action Handler

Unit tests for the reclassify action handler that overrides visitor intent
based on policy-driven temporal context.
"""

import pytest
import sqlite3
import tempfile
import time
from pathlib import Path


@pytest.fixture
def test_db():
    """Create test database with visitor_events table."""
    db_file = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".db")
    db_path = db_file.name
    db_file.close()
    
    conn = sqlite3.connect(db_path)
    
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
    
    conn.commit()
    
    yield conn
    
    conn.close()
    try:
        Path(db_path).unlink()
    except:
        pass


@pytest.fixture
def reclassify_handler(test_db):
    """Create reclassify action handler instance."""
    from packages.policy.actions.reclassify_handler import ReclassifyActionHandler
    return ReclassifyActionHandler(test_db)


@pytest.mark.asyncio
async def test_reclassify_basic_override(test_db, reclassify_handler):
    """Test basic intent override."""
    
    now = int(time.time())
    event_id = f"evt_{now}"
    
    # Create visitor event
    test_db.execute("""
        INSERT INTO visitor_events 
        (event_id, visitor_id, camera_id, detected_ts, intent_inferred, intent_confidence, urgency)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (event_id, f"visitor_{now}", 1, now, "unknown", 0.40, 60))
    test_db.commit()
    
    # Execute reclassify action
    action = {
        "type": "reclassify",
        "event_id": event_id,
        "intent": "delivery_arriving",
        "confidence": 0.85,
        "reason": "Test reclassification"
    }
    
    result = await reclassify_handler.execute(action, {}, {})
    
    assert result['success'] is True
    assert result['action_type'] == 'reclassify'
    assert result['new_intent'] == 'delivery_arriving'
    assert result['new_confidence'] == 0.85
    assert result['original_intent'] == 'unknown'
    assert result['original_confidence'] == 0.40
    
    # Verify database updated
    cursor = test_db.execute("""
        SELECT intent_inferred, intent_confidence, reclassified_by, reclassification_count
        FROM visitor_events WHERE event_id = ?
    """, (event_id,))
    row = cursor.fetchone()
    
    assert row[0] == 'delivery_arriving'
    assert row[1] == 0.85
    assert row[2] == 'policy'
    assert row[3] == 1


@pytest.mark.asyncio
async def test_reclassify_with_variable_substitution(test_db, reclassify_handler):
    """Test variable substitution in event_id and reason."""
    
    now = int(time.time())
    event_id = f"evt_{now}"
    
    test_db.execute("""
        INSERT INTO visitor_events 
        (event_id, visitor_id, camera_id, detected_ts, intent_inferred, intent_confidence, urgency)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (event_id, f"visitor_{now}", 1, now, "authority", 0.45, 50))
    test_db.commit()
    
    # Action with variable placeholders
    action = {
        "type": "reclassify",
        "event_id": "{event_id}",  # Variable
        "intent": "delivery_arriving",
        "confidence": 0.85,
        "reason": "Scheduled delivery at {camera_name}"  # Variable
    }
    
    variables = {
        "event_id": event_id,
        "camera_name": "Front Door"
    }
    
    result = await reclassify_handler.execute(action, variables, {})
    
    assert result['success'] is True
    assert result['event_id'] == event_id
    
    # Verify reason was substituted
    cursor = test_db.execute("""
        SELECT reclassification_reason FROM visitor_events WHERE event_id = ?
    """, (event_id,))
    reason = cursor.fetchone()[0]
    assert "Front Door" in reason


@pytest.mark.asyncio
async def test_reclassify_from_context(test_db, reclassify_handler):
    """Test getting event_id from context when not in action."""
    
    now = int(time.time())
    event_id = f"evt_{now}"
    
    test_db.execute("""
        INSERT INTO visitor_events 
        (event_id, visitor_id, camera_id, detected_ts, intent_inferred, intent_confidence, urgency)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (event_id, f"visitor_{now}", 1, now, "stranger", 0.50, 55))
    test_db.commit()
    
    # Action without event_id (should use context)
    action = {
        "type": "reclassify",
        "intent": "friend_visit",
        "confidence": 0.80,
        "reason": "Active guest expectation"
    }
    
    context = {
        "event_id": event_id,
        "camera_id": 1
    }
    
    result = await reclassify_handler.execute(action, {}, context)
    
    assert result['success'] is True
    assert result['event_id'] == event_id
    assert result['new_intent'] == 'friend_visit'


@pytest.mark.asyncio
async def test_reclassify_event_not_found(test_db, reclassify_handler):
    """Test error handling when event doesn't exist."""
    
    action = {
        "type": "reclassify",
        "event_id": "nonexistent_event",
        "intent": "delivery_arriving",
        "confidence": 0.85,
        "reason": "Test"
    }
    
    result = await reclassify_handler.execute(action, {}, {})
    
    assert result['success'] is False
    assert 'not found' in result['error'].lower()


@pytest.mark.asyncio
async def test_reclassify_no_event_id(test_db, reclassify_handler):
    """Test error when no event_id provided."""
    
    action = {
        "type": "reclassify",
        "intent": "delivery_arriving",
        "confidence": 0.85,
        "reason": "Test"
    }
    
    result = await reclassify_handler.execute(action, {}, {})
    
    assert result['success'] is False
    assert 'event_id' in result['error'].lower()


@pytest.mark.asyncio
async def test_reclassify_no_intent(test_db, reclassify_handler):
    """Test error when no intent specified."""
    
    now = int(time.time())
    event_id = f"evt_{now}"
    
    test_db.execute("""
        INSERT INTO visitor_events 
        (event_id, visitor_id, camera_id, detected_ts, intent_inferred, intent_confidence, urgency)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (event_id, f"visitor_{now}", 1, now, "unknown", 0.40, 60))
    test_db.commit()
    
    action = {
        "type": "reclassify",
        "event_id": event_id,
        "confidence": 0.85,
        "reason": "Test"
        # Missing intent
    }
    
    result = await reclassify_handler.execute(action, {}, {})
    
    assert result['success'] is False
    assert 'intent' in result['error'].lower()


@pytest.mark.asyncio
async def test_reclassify_already_at_target(test_db, reclassify_handler):
    """Test skipping when already at target classification."""
    
    now = int(time.time())
    event_id = f"evt_{now}"
    
    # Create event already classified as delivery_arriving
    test_db.execute("""
        INSERT INTO visitor_events 
        (event_id, visitor_id, camera_id, detected_ts, intent_inferred, intent_confidence, urgency)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (event_id, f"visitor_{now}", 1, now, "delivery_arriving", 0.85, 40))
    test_db.commit()
    
    # Try to reclassify to same intent
    action = {
        "type": "reclassify",
        "event_id": event_id,
        "intent": "delivery_arriving",
        "confidence": 0.85,
        "reason": "Test"
    }
    
    result = await reclassify_handler.execute(action, {}, {})
    
    assert result['success'] is True
    assert result.get('skipped') is True
    assert 'already' in result['reason'].lower()
    
    # Verify reclassification_count not incremented
    cursor = test_db.execute("""
        SELECT reclassification_count FROM visitor_events WHERE event_id = ?
    """, (event_id,))
    count = cursor.fetchone()[0]
    assert count == 0, "Should not increment count when skipped"


@pytest.mark.asyncio
async def test_reclassify_default_confidence(test_db, reclassify_handler):
    """Test default confidence when not specified."""
    
    now = int(time.time())
    event_id = f"evt_{now}"
    
    test_db.execute("""
        INSERT INTO visitor_events 
        (event_id, visitor_id, camera_id, detected_ts, intent_inferred, intent_confidence, urgency)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (event_id, f"visitor_{now}", 1, now, "unknown", 0.40, 60))
    test_db.commit()
    
    # Action without confidence (should default to 0.85)
    action = {
        "type": "reclassify",
        "event_id": event_id,
        "intent": "delivery_arriving",
        "reason": "Test"
        # No confidence specified
    }
    
    result = await reclassify_handler.execute(action, {}, {})
    
    assert result['success'] is True
    assert result['new_confidence'] == 0.85  # Default


@pytest.mark.asyncio
async def test_reclassify_increment_count(test_db, reclassify_handler):
    """Test that reclassification count increments correctly."""
    
    now = int(time.time())
    event_id = f"evt_{now}"
    
    test_db.execute("""
        INSERT INTO visitor_events 
        (event_id, visitor_id, camera_id, detected_ts, intent_inferred, intent_confidence, urgency)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (event_id, f"visitor_{now}", 1, now, "unknown", 0.40, 60))
    test_db.commit()
    
    # First reclassification
    action1 = {
        "type": "reclassify",
        "event_id": event_id,
        "intent": "delivery_arriving",
        "confidence": 0.85,
        "reason": "First reclassification"
    }
    
    result1 = await reclassify_handler.execute(action1, {}, {})
    assert result1['success'] is True
    
    cursor = test_db.execute("""
        SELECT reclassification_count FROM visitor_events WHERE event_id = ?
    """, (event_id,))
    assert cursor.fetchone()[0] == 1
    
    # Second reclassification (correcting)
    action2 = {
        "type": "reclassify",
        "event_id": event_id,
        "intent": "technician_visit",
        "confidence": 0.90,
        "reason": "Second reclassification"
    }
    
    result2 = await reclassify_handler.execute(action2, {}, {})
    assert result2['success'] is True
    
    cursor = test_db.execute("""
        SELECT reclassification_count FROM visitor_events WHERE event_id = ?
    """, (event_id,))
    assert cursor.fetchone()[0] == 2


@pytest.mark.asyncio
async def test_reclassify_reason_substitution(test_db, reclassify_handler):
    """Test reason field variable substitution."""
    
    now = int(time.time())
    event_id = f"evt_{now}"
    
    test_db.execute("""
        INSERT INTO visitor_events 
        (event_id, visitor_id, camera_id, detected_ts, intent_inferred, intent_confidence, urgency)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (event_id, f"visitor_{now}", 1, now, "unknown", 0.40, 60))
    test_db.commit()
    
    action = {
        "type": "reclassify",
        "event_id": event_id,
        "intent": "delivery_arriving",
        "confidence": 0.85,
        "reason": "Delivery from {company} expected at {time}"
    }
    
    variables = {
        "company": "Pizza Hut",
        "time": "6:30 PM"
    }
    
    result = await reclassify_handler.execute(action, variables, {})
    
    assert result['success'] is True
    
    cursor = test_db.execute("""
        SELECT reclassification_reason FROM visitor_events WHERE event_id = ?
    """, (event_id,))
    reason = cursor.fetchone()[0]
    
    assert "Pizza Hut" in reason
    assert "6:30 PM" in reason


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

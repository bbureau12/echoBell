#!/usr/bin/env python3
"""
Test Presence Tracking System

Tests for presence event collection and state aggregation.
"""

import pytest
import sqlite3
import tempfile
import time
from pathlib import Path

from packages.presence import (
    PresenceService,
    PresenceStatus,
    PresenceSource,
    PresenceSignal,
    calculate_time_decay,
)


@pytest.fixture
def test_db():
    """Create test database with presence tables."""
    db_file = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".db")
    db_path = db_file.name
    db_file.close()
    
    conn = sqlite3.connect(db_path)
    
    # Create presence_events table
    conn.execute("""
        CREATE TABLE presence_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            source TEXT NOT NULL,
            signal TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            person_id TEXT,
            confidence REAL,
            metadata_json TEXT,
            CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0))
        )
    """)
    
    # Create presence_state table
    conn.execute("""
        CREATE TABLE presence_state (
            person_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            confidence REAL NOT NULL,
            last_updated INTEGER NOT NULL,
            state_json TEXT,
            CHECK (status IN ('home', 'away', 'uncertain')),
            CHECK (confidence >= 0.0 AND confidence <= 1.0)
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
def presence_service(test_db):
    """Create presence service instance."""
    return PresenceService(test_db)


def test_insert_phone_heartbeat(presence_service):
    """Test inserting phone heartbeat evidence."""
    
    event_id = presence_service.insert_event(
        source="phone",
        signal="heartbeat",
        subject_id="beau_phone",
        person_id="beau",
        confidence=0.95,
        metadata={"ip": "192.168.1.50", "rssi": -42}
    )
    
    assert event_id > 0
    
    # Verify event was stored
    events = presence_service.get_recent_events("beau", lookback_seconds=60)
    assert len(events) == 1
    assert events[0].source == PresenceSource.PHONE
    assert events[0].signal == PresenceSignal.HEARTBEAT
    assert events[0].confidence == 0.95
    assert events[0].metadata["ip"] == "192.168.1.50"


def test_insert_vehicle_present(presence_service):
    """Test inserting vehicle presence evidence."""
    
    event_id = presence_service.insert_event(
        source="plate",
        signal="vehicle_present",
        subject_id="beau_tesla",
        person_id="beau",
        confidence=0.90,
        metadata={"plate": "ABC123", "camera_id": 1}
    )
    
    assert event_id > 0
    
    events = presence_service.get_recent_events("beau")
    assert len(events) == 1
    assert events[0].is_home_signal is True
    assert events[0].is_away_signal is False


def test_insert_manual_override(presence_service):
    """Test manual presence override."""
    
    event_id = presence_service.set_manual_override(
        person_id="beau",
        status="away",
        duration_hours=2,
        reason="Going to store"
    )
    
    assert event_id > 0
    
    # Verify state was updated
    state = presence_service.get_presence("beau")
    assert state is not None
    assert state.status == PresenceStatus.AWAY
    assert state.confidence == 1.0  # Manual overrides are definitive
    assert "manual" in state.reasons[0].lower()


def test_presence_state_phone_only(presence_service):
    """Test presence calculation with phone heartbeat only."""
    
    now = int(time.time())
    
    # Insert recent phone heartbeat
    presence_service.insert_event(
        source="phone",
        signal="heartbeat",
        subject_id="beau_phone",
        person_id="beau",
        confidence=0.95,
        timestamp=now - 120  # 2 minutes ago
    )
    
    # Calculate state
    state = presence_service.update_presence_state("beau")
    
    assert state.status == PresenceStatus.HOME
    assert state.confidence > 0.7
    assert "phone_seen" in str(state.reasons)


def test_presence_state_vehicle_only(presence_service):
    """Test presence calculation with vehicle only."""
    
    now = int(time.time())
    
    # Insert vehicle present
    presence_service.insert_event(
        source="plate",
        signal="vehicle_present",
        subject_id="beau_tesla",
        person_id="beau",
        confidence=0.90,
        timestamp=now - 300  # 5 minutes ago
    )
    
    state = presence_service.update_presence_state("beau")
    
    assert state.status == PresenceStatus.HOME
    assert state.confidence > 0.7
    assert any("tesla" in r for r in state.reasons)


def test_presence_state_multiple_signals(presence_service):
    """Test presence with multiple reinforcing signals."""
    
    now = int(time.time())
    
    # Phone heartbeat (2 min ago)
    presence_service.insert_event(
        source="phone",
        signal="heartbeat",
        subject_id="beau_phone",
        person_id="beau",
        confidence=0.95,
        timestamp=now - 120
    )
    
    # Vehicle present (10 min ago)
    presence_service.insert_event(
        source="plate",
        signal="vehicle_present",
        subject_id="beau_tesla",
        person_id="beau",
        confidence=0.90,
        timestamp=now - 600
    )
    
    # Face seen (1 min ago)
    presence_service.insert_event(
        source="face",
        signal="face_seen",
        subject_id="beau_face",
        person_id="beau",
        confidence=0.85,
        timestamp=now - 60
    )
    
    state = presence_service.update_presence_state("beau")
    
    # Multiple signals should give high confidence
    assert state.status == PresenceStatus.HOME
    assert state.confidence > 0.8
    assert len(state.reasons) >= 2


def test_presence_state_conflicting_signals(presence_service):
    """Test presence with conflicting signals (car present but left phone)."""
    
    now = int(time.time())
    
    # Vehicle present (recent)
    presence_service.insert_event(
        source="plate",
        signal="vehicle_present",
        subject_id="beau_tesla",
        person_id="beau",
        confidence=0.90,
        timestamp=now - 300
    )
    
    # Phone heartbeat (very old - 30 minutes)
    presence_service.insert_event(
        source="phone",
        signal="heartbeat",
        subject_id="beau_phone",
        person_id="beau",
        confidence=0.95,
        timestamp=now - 1800
    )
    
    state = presence_service.update_presence_state("beau")
    
    # Vehicle signal should dominate (phone is too old)
    assert state.status == PresenceStatus.HOME
    # Confidence might be medium (only one strong signal)
    assert 0.5 < state.confidence < 0.95


def test_presence_time_decay_phone(presence_service):
    """Test that phone signals decay quickly."""
    
    # Test time decay calculation
    decay_2min = calculate_time_decay(120, "phone")   # 2 minutes
    decay_5min = calculate_time_decay(300, "phone")   # 5 minutes (half-life)
    decay_15min = calculate_time_decay(900, "phone")  # 15 minutes (max age)
    
    assert decay_2min > 0.7  # Recent signal still strong
    assert 0.4 < decay_5min < 0.6  # At half-life, ~0.5
    assert decay_15min < 0.1  # Very weak after max age


def test_presence_time_decay_vehicle(presence_service):
    """Test that vehicle signals decay slowly."""
    
    decay_5min = calculate_time_decay(300, "plate")
    decay_1hr = calculate_time_decay(3600, "plate")  # 1 hour (half-life)
    decay_2hr = calculate_time_decay(7200, "plate")  # 2 hours (max age)
    
    assert decay_5min > 0.9  # Vehicle barely decays in 5 min
    assert 0.4 < decay_1hr < 0.6  # At half-life
    assert decay_2hr < 0.1


def test_is_anyone_home(presence_service):
    """Test anyone_home query."""
    
    now = int(time.time())
    
    # Nobody home initially
    assert presence_service.is_anyone_home() is False
    
    # Add person home
    presence_service.insert_event(
        source="phone",
        signal="heartbeat",
        subject_id="beau_phone",
        person_id="beau",
        confidence=0.95,
        timestamp=now - 60
    )
    presence_service.update_presence_state("beau")
    
    # Now someone is home
    assert presence_service.is_anyone_home() is True


def test_is_everyone_away(presence_service):
    """Test everyone_away query."""
    
    now = int(time.time())
    
    # Add person away
    presence_service.set_manual_override(
        person_id="beau",
        status="away",
        duration_hours=2
    )
    
    # Everyone is away
    assert presence_service.is_everyone_away() is True
    
    # Add another person home
    presence_service.insert_event(
        source="phone",
        signal="heartbeat",
        subject_id="other_phone",
        person_id="other_person",
        confidence=0.95,
        timestamp=now - 60
    )
    presence_service.update_presence_state("other_person")
    
    # Not everyone away anymore
    assert presence_service.is_everyone_away() is False


def test_vehicle_left_signal(presence_service):
    """Test that vehicle_left creates negative signal."""
    
    now = int(time.time())
    
    # Vehicle present initially
    presence_service.insert_event(
        source="plate",
        signal="vehicle_present",
        subject_id="beau_tesla",
        person_id="beau",
        confidence=0.90,
        timestamp=now - 600  # 10 min ago
    )
    
    # Vehicle left recently
    presence_service.insert_event(
        source="plate",
        signal="vehicle_left",
        subject_id="beau_tesla",
        person_id="beau",
        confidence=0.90,
        timestamp=now - 60  # 1 min ago
    )
    
    state = presence_service.update_presence_state("beau")
    
    # More recent "left" signal should indicate away
    assert state.status in (PresenceStatus.AWAY, PresenceStatus.UNCERTAIN)


def test_manual_override_expiration(presence_service):
    """Test that manual overrides expire after duration."""
    
    now = int(time.time())
    
    # Create override that already expired
    presence_service.insert_event(
        source="manual",
        signal="override_away",
        subject_id="beau",
        person_id="beau",
        confidence=1.0,
        timestamp=now - 7200,  # 2 hours ago
        metadata={
            "duration_hours": 1,
            "expires_at": now - 3600,  # Expired 1 hour ago
            "reason": "Going to store"
        }
    )
    
    # Add recent phone heartbeat
    presence_service.insert_event(
        source="phone",
        signal="heartbeat",
        subject_id="beau_phone",
        person_id="beau",
        confidence=0.95,
        timestamp=now - 60
    )
    
    state = presence_service.update_presence_state("beau")
    
    # Expired override should be ignored, phone signal should win
    assert state.status == PresenceStatus.HOME


def test_get_all_presence(presence_service):
    """Test getting presence for all people."""
    
    now = int(time.time())
    
    # Add presence for two people
    presence_service.insert_event(
        source="phone",
        signal="heartbeat",
        subject_id="person1_phone",
        person_id="person1",
        timestamp=now - 60
    )
    presence_service.update_presence_state("person1")
    
    presence_service.insert_event(
        source="phone",
        signal="heartbeat",
        subject_id="person2_phone",
        person_id="person2",
        timestamp=now - 120
    )
    presence_service.update_presence_state("person2")
    
    states = presence_service.get_all_presence()
    
    assert len(states) == 2
    assert all(s.status == PresenceStatus.HOME for s in states)


def test_presence_state_to_dict(presence_service):
    """Test serialization of presence state."""
    
    now = int(time.time())
    
    presence_service.insert_event(
        source="phone",
        signal="heartbeat",
        subject_id="beau_phone",
        person_id="beau",
        timestamp=now - 60
    )
    
    state = presence_service.update_presence_state("beau")
    state_dict = state.to_dict()
    
    assert "person_id" in state_dict
    assert "status" in state_dict
    assert "confidence" in state_dict
    assert "reasons" in state_dict
    assert isinstance(state_dict["reasons"], list)


def test_no_evidence_uncertain(presence_service):
    """Test that no evidence results in uncertain status."""
    
    # Try to get presence with no events
    state = presence_service.get_presence("unknown_person", force_refresh=True)
    
    # Should return uncertain with low confidence
    assert state.status == PresenceStatus.UNCERTAIN
    assert state.confidence == 0.0
    assert "no_recent_evidence" in state.reasons


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

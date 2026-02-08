"""
Presence Tracking Service

Tracks who is currently home based on multiple evidence sources:
- Phone heartbeats (WiFi, Bluetooth)
- Vehicle detections (trusted plates)
- Face recognition (trusted faces)
- Manual overrides (voice commands, API)

Architecture:
- presence_events: Immutable evidence log
- presence_state: Current aggregated state
"""

import json
import time
import sqlite3
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
from enum import Enum


class PresenceStatus(str, Enum):
    """Possible presence states."""
    HOME = "home"
    AWAY = "away"
    UNCERTAIN = "uncertain"


class PresenceSource(str, Enum):
    """Evidence sources."""
    PHONE = "phone"
    PLATE = "plate"
    FACE = "face"
    MANUAL = "manual"
    BLUETOOTH = "bluetooth"
    OTHER = "other"


class PresenceSignal(str, Enum):
    """Specific signals from each source."""
    # Positive signals (indicate home)
    HEARTBEAT = "heartbeat"
    VEHICLE_PRESENT = "vehicle_present"
    FACE_SEEN = "face_seen"
    OVERRIDE_HOME = "override_home"
    
    # Negative signals (indicate away)
    VEHICLE_LEFT = "vehicle_left"
    OVERRIDE_AWAY = "override_away"


@dataclass
class PresenceEvent:
    """A single piece of presence evidence."""
    timestamp: int
    source: PresenceSource
    signal: PresenceSignal
    subject_id: str
    person_id: str
    confidence: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None
    
    @property
    def is_home_signal(self) -> bool:
        """Check if this signal indicates being home."""
        return self.signal in (
            PresenceSignal.HEARTBEAT,
            PresenceSignal.VEHICLE_PRESENT,
            PresenceSignal.FACE_SEEN,
            PresenceSignal.OVERRIDE_HOME,
        )
    
    @property
    def is_away_signal(self) -> bool:
        """Check if this signal indicates being away."""
        return self.signal in (
            PresenceSignal.VEHICLE_LEFT,
            PresenceSignal.OVERRIDE_AWAY,
        )


@dataclass
class PresenceState:
    """Current presence state for a person."""
    person_id: str
    status: PresenceStatus
    confidence: float
    last_updated: int
    reasons: List[str]
    evidence: Dict[str, Any]
    raw_signals: List[Dict[str, Any]]
    
    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "person_id": self.person_id,
            "status": self.status.value,
            "confidence": self.confidence,
            "last_updated": self.last_updated,
            "reasons": self.reasons,
            "evidence": self.evidence,
            "raw_signals": self.raw_signals,
        }
    
    def to_state_json(self) -> str:
        """Convert to JSON for database storage."""
        return json.dumps({
            "reasons": self.reasons,
            "evidence": self.evidence,
            "raw_signals": self.raw_signals,
        })


class PresenceService:
    """
    Service for tracking and querying presence.
    
    Example Usage:
        service = PresenceService(db_connection)
        
        # Insert evidence
        service.insert_event(
            source="phone",
            signal="heartbeat",
            subject_id="beau_phone",
            person_id="beau",
            confidence=0.95,
            metadata={"ip": "192.168.1.50", "rssi": -42}
        )
        
        # Get current presence
        state = service.get_presence("beau")
        print(f"{state.person_id} is {state.status} (confidence: {state.confidence})")
    """
    
    def __init__(self, db: sqlite3.Connection):
        self.db = db
    
    def insert_event(
        self,
        source: str,
        signal: str,
        subject_id: str,
        person_id: str,
        confidence: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[int] = None,
    ) -> int:
        """
        Insert a presence event (evidence).
        
        Args:
            source: Evidence source ("phone", "plate", "face", "manual")
            signal: Specific signal ("heartbeat", "vehicle_present", etc.)
            subject_id: The specific entity ("beau_phone", "beau_tesla")
            person_id: The person this belongs to ("beau")
            confidence: Optional confidence score 0.0-1.0
            metadata: Optional source-specific metadata
            timestamp: Optional timestamp (defaults to now)
        
        Returns:
            Event ID
        """
        if timestamp is None:
            timestamp = int(time.time())
        
        metadata_json = json.dumps(metadata) if metadata else None
        
        cursor = self.db.execute(
            """
            INSERT INTO presence_events 
            (timestamp, source, signal, subject_id, person_id, confidence, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (timestamp, source, signal, subject_id, person_id, confidence, metadata_json)
        )
        self.db.commit()
        
        return cursor.lastrowid
    
    def get_recent_events(
        self,
        person_id: str,
        lookback_seconds: int = 3600,
    ) -> List[PresenceEvent]:
        """
        Get recent presence events for a person.
        
        Args:
            person_id: Person to get events for
            lookback_seconds: How far back to look (default 1 hour)
        
        Returns:
            List of PresenceEvent objects
        """
        cutoff = int(time.time()) - lookback_seconds
        
        cursor = self.db.execute(
            """
            SELECT timestamp, source, signal, subject_id, person_id, confidence, metadata_json
            FROM presence_events
            WHERE person_id = ?
              AND timestamp > ?
            ORDER BY timestamp DESC
            """,
            (person_id, cutoff)
        )
        
        events = []
        for row in cursor.fetchall():
            metadata = json.loads(row[6]) if row[6] else None
            events.append(PresenceEvent(
                timestamp=row[0],
                source=PresenceSource(row[1]),
                signal=PresenceSignal(row[2]),
                subject_id=row[3],
                person_id=row[4],
                confidence=row[5],
                metadata=metadata,
            ))
        
        return events
    
    def update_presence_state(self, person_id: str) -> PresenceState:
        """
        Calculate and update presence state for a person.
        
        This aggregates recent evidence and updates the presence_state table.
        
        Args:
            person_id: Person to update
        
        Returns:
            Updated PresenceState
        """
        from .aggregator import calculate_presence_state
        
        current_time = int(time.time())
        events = self.get_recent_events(person_id, lookback_seconds=3600)
        
        # Calculate new state
        state = calculate_presence_state(events, current_time)
        
        # Update database
        self.db.execute(
            """
            INSERT INTO presence_state (person_id, status, confidence, last_updated, state_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(person_id) DO UPDATE SET
                status = excluded.status,
                confidence = excluded.confidence,
                last_updated = excluded.last_updated,
                state_json = excluded.state_json
            """,
            (person_id, state.status.value, state.confidence, current_time, state.to_state_json())
        )
        self.db.commit()
        
        return state
    
    def get_presence(self, person_id: str, force_refresh: bool = False) -> Optional[PresenceState]:
        """
        Get current presence state for a person.
        
        Args:
            person_id: Person to get state for
            force_refresh: If True, recalculate state from events
        
        Returns:
            PresenceState or None if not found
        """
        if force_refresh:
            return self.update_presence_state(person_id)
        
        cursor = self.db.execute(
            """
            SELECT person_id, status, confidence, last_updated, state_json
            FROM presence_state
            WHERE person_id = ?
            """,
            (person_id,)
        )
        
        row = cursor.fetchone()
        if not row:
            # No state yet, try to calculate it
            return self.update_presence_state(person_id)
        
        state_data = json.loads(row[4]) if row[4] else {}
        
        return PresenceState(
            person_id=row[0],
            status=PresenceStatus(row[1]),
            confidence=row[2],
            last_updated=row[3],
            reasons=state_data.get('reasons', []),
            evidence=state_data.get('evidence', {}),
            raw_signals=state_data.get('raw_signals', []),
        )
    
    def get_all_presence(self) -> List[PresenceState]:
        """
        Get presence state for all tracked people.
        
        Returns:
            List of PresenceState objects
        """
        cursor = self.db.execute(
            """
            SELECT person_id, status, confidence, last_updated, state_json
            FROM presence_state
            ORDER BY person_id
            """
        )
        
        states = []
        for row in cursor.fetchall():
            state_data = json.loads(row[4]) if row[4] else {}
            states.append(PresenceState(
                person_id=row[0],
                status=PresenceStatus(row[1]),
                confidence=row[2],
                last_updated=row[3],
                reasons=state_data.get('reasons', []),
                evidence=state_data.get('evidence', {}),
                raw_signals=state_data.get('raw_signals', []),
            ))
        
        return states
    
    def is_anyone_home(self, confidence_threshold: float = 0.6) -> bool:
        """
        Check if anyone is currently home.
        
        Args:
            confidence_threshold: Minimum confidence to consider "home"
        
        Returns:
            True if at least one person is home
        """
        cursor = self.db.execute(
            """
            SELECT COUNT(*)
            FROM presence_state
            WHERE status = 'home'
              AND confidence >= ?
            """,
            (confidence_threshold,)
        )
        
        count = cursor.fetchone()[0]
        return count > 0
    
    def is_everyone_away(self, confidence_threshold: float = 0.6) -> bool:
        """
        Check if everyone is currently away.
        
        Args:
            confidence_threshold: Minimum confidence to consider "away"
        
        Returns:
            True if all tracked people are away
        """
        cursor = self.db.execute(
            """
            SELECT COUNT(*)
            FROM presence_state
            WHERE status != 'away'
               OR confidence < ?
            """,
            (confidence_threshold,)
        )
        
        count = cursor.fetchone()[0]
        return count == 0
    
    def set_manual_override(
        self,
        person_id: str,
        status: str,
        duration_hours: Optional[int] = None,
        reason: Optional[str] = None,
    ) -> int:
        """
        Manually set presence status (e.g., "I'm leaving for 2 hours").
        
        Args:
            person_id: Person to set status for
            status: "home" or "away"
            duration_hours: How long this override lasts (None = indefinite)
            reason: Optional reason for override
        
        Returns:
            Event ID
        """
        signal = PresenceSignal.OVERRIDE_HOME if status == "home" else PresenceSignal.OVERRIDE_AWAY
        
        metadata = {
            "source": "manual",
            "reason": reason or f"Manual override to {status}",
        }
        
        if duration_hours:
            expires_at = int(time.time()) + (duration_hours * 3600)
            metadata["duration_hours"] = duration_hours
            metadata["expires_at"] = expires_at
        
        event_id = self.insert_event(
            source=PresenceSource.MANUAL,
            signal=signal,
            subject_id=person_id,
            person_id=person_id,
            confidence=1.0,  # Manual overrides are definitive
            metadata=metadata,
        )
        
        # Immediately update state
        self.update_presence_state(person_id)
        
        return event_id


def create_presence_service(db_path: str) -> PresenceService:
    """
    Factory function to create a PresenceService.
    
    Args:
        db_path: Path to SQLite database
    
    Returns:
        PresenceService instance
    """
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    return PresenceService(db)

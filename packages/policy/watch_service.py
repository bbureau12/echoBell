"""
Watch Service - Time-based Policy Evaluation

Manages "watches" - deferred policy evaluations that fire at a specific time.

Example flow:
    1. Unknown person detected → policy creates watch (due in 2 min)
    2. At 2 min: worker re-evaluates → alert if still present
    3. Policy creates next watch (due in 3 more min) for escalation
    
Watches enable:
- Loitering detection (alert after N minutes)
- Delivery timeouts (alert if package not picked up)
- Vehicle idling (alert if car parked too long)
- Escalation chains (2min → 5min → 10min alerts)
"""

import json
import sqlite3
import time
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum


class WatchState(str, Enum):
    """Watch state machine."""
    ARMED = "armed"          # Created, waiting for due_ts
    TRIGGERED = "triggered"  # Condition still true, action taken
    DISARMED = "disarmed"    # Condition no longer true (e.g., person left)
    EXPIRED = "expired"      # Reached expires_ts without triggering


@dataclass
class Watch:
    """Represents a watch in the database."""
    id: Optional[int]
    watch_type: str
    watch_key: str
    camera_id: int
    scene_track_id: Optional[int]
    event_id: Optional[str]
    created_ts: int
    due_ts: int
    evaluated_ts: Optional[int]
    expires_ts: Optional[int]
    state: WatchState
    context_json: Optional[str]
    trigger_reason: Optional[str]
    created_by_policy_id: Optional[str]
    last_updated_ts: int
    
    @property
    def context(self) -> Dict[str, Any]:
        """Parse context JSON."""
        if self.context_json:
            return json.loads(self.context_json)
        return {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "watch_type": self.watch_type,
            "watch_key": self.watch_key,
            "camera_id": self.camera_id,
            "scene_track_id": self.scene_track_id,
            "event_id": self.event_id,
            "created_ts": self.created_ts,
            "due_ts": self.due_ts,
            "evaluated_ts": self.evaluated_ts,
            "expires_ts": self.expires_ts,
            "state": self.state.value,
            "context": self.context,
            "trigger_reason": self.trigger_reason,
            "created_by_policy_id": self.created_by_policy_id,
            "last_updated_ts": self.last_updated_ts,
        }


class WatchService:
    """Service for managing watches."""
    
    def __init__(self, db_path: str):
        """Initialize watch service.
        
        Args:
            db_path: Path to SQLite database
        """
        self.db_path = db_path
    
    def create_watch(
        self,
        conn: sqlite3.Connection,
        watch_type: str,
        watch_key: str,
        camera_id: int,
        due_in_seconds: int,
        scene_track_id: Optional[int] = None,
        event_id: Optional[str] = None,
        expires_in_seconds: Optional[int] = None,
        context: Optional[Dict[str, Any]] = None,
        created_by_policy_id: Optional[str] = None,
    ) -> Optional[Watch]:
        """
        Create a new watch.
        
        Args:
            conn: Database connection
            watch_type: Type of watch (e.g., "loitering_2min")
            watch_key: Unique key for deduplication
            camera_id: Camera ID
            due_in_seconds: Seconds from now when watch should fire
            scene_track_id: Optional scene track ID
            event_id: Optional event ID that created watch
            expires_in_seconds: Optional expiration (default: 300 = 5 min after due)
            context: Optional context dict for debugging
            created_by_policy_id: Optional policy ID that created watch
            
        Returns:
            Created Watch object, or None if duplicate key
        """
        now = int(time.time())
        due_ts = now + due_in_seconds
        
        # Default expiration: 5 minutes after due_ts
        if expires_in_seconds is None:
            expires_ts = due_ts + 300
        else:
            expires_ts = due_ts + expires_in_seconds
        
        context_json = json.dumps(context) if context else None
        
        try:
            cursor = conn.execute("""
                INSERT INTO watches (
                    watch_type, watch_key, camera_id, scene_track_id, event_id,
                    created_ts, due_ts, expires_ts,
                    state, context_json, created_by_policy_id, last_updated_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                watch_type, watch_key, camera_id, scene_track_id, event_id,
                now, due_ts, expires_ts,
                WatchState.ARMED.value, context_json, created_by_policy_id, now
            ))
            
            watch_id = cursor.lastrowid
            
            return Watch(
                id=watch_id,
                watch_type=watch_type,
                watch_key=watch_key,
                camera_id=camera_id,
                scene_track_id=scene_track_id,
                event_id=event_id,
                created_ts=now,
                due_ts=due_ts,
                evaluated_ts=None,
                expires_ts=expires_ts,
                state=WatchState.ARMED,
                context_json=context_json,
                trigger_reason=None,
                created_by_policy_id=created_by_policy_id,
                last_updated_ts=now
            )
            
        except sqlite3.IntegrityError as e:
            if "UNIQUE constraint" in str(e):
                # Duplicate watch_key - this is expected (deduplication)
                return None
            raise
    
    def get_due_watches(
        self,
        conn: sqlite3.Connection,
        now_ts: Optional[int] = None
    ) -> List[Watch]:
        """
        Get all watches that are due to be evaluated.
        
        Args:
            conn: Database connection
            now_ts: Current timestamp (default: now)
            
        Returns:
            List of armed watches with due_ts <= now
        """
        if now_ts is None:
            now_ts = int(time.time())
        
        cursor = conn.execute("""
            SELECT 
                id, watch_type, watch_key, camera_id, scene_track_id, event_id,
                created_ts, due_ts, evaluated_ts, expires_ts,
                state, context_json, trigger_reason, created_by_policy_id, last_updated_ts
            FROM watches
            WHERE state = ? AND due_ts <= ?
            ORDER BY due_ts ASC
        """, (WatchState.ARMED.value, now_ts))
        
        watches = []
        for row in cursor.fetchall():
            watches.append(Watch(
                id=row[0],
                watch_type=row[1],
                watch_key=row[2],
                camera_id=row[3],
                scene_track_id=row[4],
                event_id=row[5],
                created_ts=row[6],
                due_ts=row[7],
                evaluated_ts=row[8],
                expires_ts=row[9],
                state=WatchState(row[10]),
                context_json=row[11],
                trigger_reason=row[12],
                created_by_policy_id=row[13],
                last_updated_ts=row[14]
            ))
        
        return watches
    
    def mark_triggered(
        self,
        conn: sqlite3.Connection,
        watch_id: int,
        trigger_reason: Optional[str] = None
    ) -> None:
        """
        Mark watch as triggered (condition was still true).
        
        Args:
            conn: Database connection
            watch_id: Watch ID
            trigger_reason: Optional reason for trigger
        """
        now = int(time.time())
        conn.execute("""
            UPDATE watches
            SET state = ?,
                evaluated_ts = ?,
                trigger_reason = ?,
                last_updated_ts = ?
            WHERE id = ?
        """, (WatchState.TRIGGERED.value, now, trigger_reason, now, watch_id))
    
    def mark_disarmed(
        self,
        conn: sqlite3.Connection,
        watch_id: int,
        trigger_reason: Optional[str] = None
    ) -> None:
        """
        Mark watch as disarmed (condition no longer true).
        
        Args:
            conn: Database connection
            watch_id: Watch ID
            trigger_reason: Optional reason for disarm
        """
        now = int(time.time())
        conn.execute("""
            UPDATE watches
            SET state = ?,
                evaluated_ts = ?,
                trigger_reason = ?,
                last_updated_ts = ?
            WHERE id = ?
        """, (WatchState.DISARMED.value, now, trigger_reason, now, watch_id))
    
    def mark_expired(
        self,
        conn: sqlite3.Connection,
        watch_id: int
    ) -> None:
        """
        Mark watch as expired (reached expires_ts without triggering).
        
        Args:
            conn: Database connection
            watch_id: Watch ID
        """
        now = int(time.time())
        conn.execute("""
            UPDATE watches
            SET state = ?,
                evaluated_ts = ?,
                trigger_reason = ?,
                last_updated_ts = ?
            WHERE id = ?
        """, (WatchState.EXPIRED.value, now, "expired", now, watch_id))
    
    def expire_old_watches(
        self,
        conn: sqlite3.Connection,
        now_ts: Optional[int] = None
    ) -> int:
        """
        Expire armed watches that have passed their expires_ts.
        
        Args:
            conn: Database connection
            now_ts: Current timestamp (default: now)
            
        Returns:
            Number of watches expired
        """
        if now_ts is None:
            now_ts = int(time.time())
        
        cursor = conn.execute("""
            UPDATE watches
            SET state = ?,
                evaluated_ts = ?,
                trigger_reason = ?,
                last_updated_ts = ?
            WHERE state = ?
              AND expires_ts IS NOT NULL
              AND expires_ts <= ?
        """, (
            WatchState.EXPIRED.value,
            now_ts,
            "expired",
            now_ts,
            WatchState.ARMED.value,
            now_ts
        ))
        
        return cursor.rowcount
    
    def cleanup_old_watches(
        self,
        conn: sqlite3.Connection,
        days_old: int = 30
    ) -> int:
        """
        Hard-delete watches older than N days (non-armed states only).
        
        Args:
            conn: Database connection
            days_old: Delete watches older than this many days
            
        Returns:
            Number of watches deleted
        """
        cutoff_ts = int(time.time()) - (days_old * 24 * 3600)
        
        cursor = conn.execute("""
            DELETE FROM watches
            WHERE state IN (?, ?, ?)
              AND last_updated_ts < ?
        """, (
            WatchState.TRIGGERED.value,
            WatchState.DISARMED.value,
            WatchState.EXPIRED.value,
            cutoff_ts
        ))
        
        return cursor.rowcount
    
    def get_watch_by_id(
        self,
        conn: sqlite3.Connection,
        watch_id: int
    ) -> Optional[Watch]:
        """Get watch by ID."""
        cursor = conn.execute("""
            SELECT 
                id, watch_type, watch_key, camera_id, scene_track_id, event_id,
                created_ts, due_ts, evaluated_ts, expires_ts,
                state, context_json, trigger_reason, created_by_policy_id, last_updated_ts
            FROM watches
            WHERE id = ?
        """, (watch_id,))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        return Watch(
            id=row[0],
            watch_type=row[1],
            watch_key=row[2],
            camera_id=row[3],
            scene_track_id=row[4],
            event_id=row[5],
            created_ts=row[6],
            due_ts=row[7],
            evaluated_ts=row[8],
            expires_ts=row[9],
            state=WatchState(row[10]),
            context_json=row[11],
            trigger_reason=row[12],
            created_by_policy_id=row[13],
            last_updated_ts=row[14]
        )
    
    def get_watches_for_track(
        self,
        conn: sqlite3.Connection,
        scene_track_id: int,
        state: Optional[WatchState] = None
    ) -> List[Watch]:
        """
        Get all watches for a specific scene track.
        
        Args:
            conn: Database connection
            scene_track_id: Scene track ID
            state: Optional state filter
            
        Returns:
            List of watches
        """
        if state:
            cursor = conn.execute("""
                SELECT 
                    id, watch_type, watch_key, camera_id, scene_track_id, event_id,
                    created_ts, due_ts, evaluated_ts, expires_ts,
                    state, context_json, trigger_reason, created_by_policy_id, last_updated_ts
                FROM watches
                WHERE scene_track_id = ? AND state = ?
                ORDER BY due_ts ASC
            """, (scene_track_id, state.value))
        else:
            cursor = conn.execute("""
                SELECT 
                    id, watch_type, watch_key, camera_id, scene_track_id, event_id,
                    created_ts, due_ts, evaluated_ts, expires_ts,
                    state, context_json, trigger_reason, created_by_policy_id, last_updated_ts
                FROM watches
                WHERE scene_track_id = ?
                ORDER BY due_ts ASC
            """, (scene_track_id,))
        
        watches = []
        for row in cursor.fetchall():
            watches.append(Watch(
                id=row[0],
                watch_type=row[1],
                watch_key=row[2],
                camera_id=row[3],
                scene_track_id=row[4],
                event_id=row[5],
                created_ts=row[6],
                due_ts=row[7],
                evaluated_ts=row[8],
                expires_ts=row[9],
                state=WatchState(row[10]),
                context_json=row[11],
                trigger_reason=row[12],
                created_by_policy_id=row[13],
                last_updated_ts=row[14]
            ))
        
        return watches
    
    def get_all_watches(
        self,
        conn: sqlite3.Connection,
        state: Optional[WatchState] = None,
        limit: int = 100
    ) -> List[Watch]:
        """
        Get all watches (for debugging/admin).
        
        Args:
            conn: Database connection
            state: Optional state filter
            limit: Max results
            
        Returns:
            List of watches
        """
        if state:
            cursor = conn.execute("""
                SELECT 
                    id, watch_type, watch_key, camera_id, scene_track_id, event_id,
                    created_ts, due_ts, evaluated_ts, expires_ts,
                    state, context_json, trigger_reason, created_by_policy_id, last_updated_ts
                FROM watches
                WHERE state = ?
                ORDER BY due_ts DESC
                LIMIT ?
            """, (state.value, limit))
        else:
            cursor = conn.execute("""
                SELECT 
                    id, watch_type, watch_key, camera_id, scene_track_id, event_id,
                    created_ts, due_ts, evaluated_ts, expires_ts,
                    state, context_json, trigger_reason, created_by_policy_id, last_updated_ts
                FROM watches
                ORDER BY due_ts DESC
                LIMIT ?
            """, (limit,))
        
        watches = []
        for row in cursor.fetchall():
            watches.append(Watch(
                id=row[0],
                watch_type=row[1],
                watch_key=row[2],
                camera_id=row[3],
                scene_track_id=row[4],
                event_id=row[5],
                created_ts=row[6],
                due_ts=row[7],
                evaluated_ts=row[8],
                expires_ts=row[9],
                state=WatchState(row[10]),
                context_json=row[11],
                trigger_reason=row[12],
                created_by_policy_id=row[13],
                last_updated_ts=row[14]
            ))
        
        return watches

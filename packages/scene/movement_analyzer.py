# packages/scene/movement_analyzer.py
"""
Movement Analysis for Scene Tracking

Analyzes object movement patterns and generates movement-based evidence:
- Position changes (movement detected)
- Loitering (stationary behavior)
- Object exits (scene departures)

This module extracts movement detection logic from the API layer,
making it testable, configurable, and reusable.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple

from packages.common.types import Evidence


@dataclass
class MovementConfig:
    """Configuration for movement detection thresholds."""
    significant_movement_px: float = 50.0
    """Minimum pixel distance to consider as significant movement"""
    
    loitering_movement_px: float = 20.0
    """Maximum pixel distance while still considered stationary"""
    
    loitering_time_s: int = 30
    """Minimum time (seconds) stationary to trigger loitering alert"""


@dataclass
class ObservedObject:
    """Object currently observed in the scene."""
    object_id: int
    label: str  # person, vehicle, package
    bbox: Tuple[float, float, float, float]  # [x1, y1, x2, y2]
    scene_track_key: Optional[str] = None


class MovementAnalyzer:
    """
    Analyzes object movement patterns and generates evidence.
    
    Responsibilities:
    - Detect position changes (movement)
    - Detect loitering (stationary behavior)
    - Detect object exits (departures from scene)
    
    Example:
        config = MovementConfig(
            significant_movement_px=50,
            loitering_movement_px=20,
            loitering_time_s=30
        )
        analyzer = MovementAnalyzer(config)
        
        evidence = analyzer.analyze_movement(
            conn=db_conn,
            camera_id=1,
            current_objects=observed_objects,
            timestamp=int(time.time())
        )
    """
    
    def __init__(self, config: Optional[MovementConfig] = None):
        """
        Initialize movement analyzer.
        
        Args:
            config: Movement detection configuration. Uses defaults if None.
        """
        self.config = config or MovementConfig()
    
    def analyze_movement(
        self,
        conn: sqlite3.Connection,
        camera_id: int,
        current_objects: List[ObservedObject],
        timestamp: int
    ) -> List[Dict[str, any]]:
        """
        Analyze movement for currently observed objects.
        
        Args:
            conn: Database connection
            camera_id: Camera ID
            current_objects: List of currently observed objects
            timestamp: Current timestamp (Unix seconds)
        
        Returns:
            List of movement evidence dicts with keys:
            - source: "movement"
            - feature: "position_changed", "loitering", etc.
            - value: Movement metrics (distance, duration, etc.)
            - conf: Confidence (1.0)
            - object_id: Associated object ID
        """
        evidence = []
        
        # Analyze position changes for tracked objects
        for obj in current_objects:
            if not obj.scene_track_key:
                continue
            
            # Get historical position from scene_tracks
            cursor = conn.execute("""
                SELECT last_box_json, last_seen_ts, first_seen_ts
                FROM scene_tracks
                WHERE camera_id = ? AND track_key = ? AND active = 1
            """, (camera_id, obj.scene_track_key))
            
            row = cursor.fetchone()
            if not row:
                continue
            
            last_box_json, last_seen_ts, first_seen_ts = row
            
            # Analyze movement from previous position
            movement_ev = self._analyze_position_change(
                obj=obj,
                prev_box_json=last_box_json,
                first_seen_ts=first_seen_ts,
                timestamp=timestamp
            )
            
            evidence.extend(movement_ev)
        
        return evidence
    
    def detect_exits(
        self,
        conn: sqlite3.Connection,
        camera_id: int,
        current_track_keys: set[str],
        timestamp: int
    ) -> Tuple[List[Dict[str, any]], List[int]]:
        """
        Detect objects that have exited the scene.
        
        Args:
            conn: Database connection
            camera_id: Camera ID
            current_track_keys: Set of track_keys currently in scene
            timestamp: Current timestamp (Unix seconds)
        
        Returns:
            Tuple of:
            - List of exit evidence dicts
            - List of track IDs to mark as inactive
        """
        evidence = []
        inactive_track_ids = []
        
        # Get all active tracks for this camera
        cursor = conn.execute("""
            SELECT track_key, track_type, id
            FROM scene_tracks
            WHERE camera_id = ? AND active = 1
        """, (camera_id,))
        
        active_tracks = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}
        
        # Find tracks that are no longer present
        missing_track_keys = set(active_tracks.keys()) - current_track_keys
        
        for track_key in missing_track_keys:
            track_type, track_id = active_tracks[track_key]
            
            # Generate exit evidence
            evidence.append({
                "source": "movement",
                "feature": f"{track_type}_exited",
                "value": track_key,
                "conf": 1.0,
                "object_id": None
            })
            
            inactive_track_ids.append(track_id)
        
        return evidence, inactive_track_ids
    
    def mark_tracks_inactive(
        self,
        conn: sqlite3.Connection,
        track_ids: List[int],
        timestamp: int
    ) -> None:
        """
        Mark tracks as inactive in the database.
        
        Args:
            conn: Database connection
            track_ids: List of track IDs to deactivate
            timestamp: Timestamp to record as last_seen_ts
        """
        if not track_ids:
            return
        
        placeholders = ','.join('?' * len(track_ids))
        conn.execute(f"""
            UPDATE scene_tracks
            SET active = 0, last_seen_ts = ?
            WHERE id IN ({placeholders})
        """, [timestamp] + track_ids)
    
    def _analyze_position_change(
        self,
        obj: ObservedObject,
        prev_box_json: Optional[str],
        first_seen_ts: int,
        timestamp: int
    ) -> List[Dict[str, any]]:
        """
        Analyze position change for a single object.
        
        Returns movement and/or loitering evidence.
        """
        if not prev_box_json:
            return []
        
        evidence = []
        
        try:
            prev_bbox = json.loads(prev_box_json)
            
            # Calculate movement distance
            curr_center_x = (obj.bbox[0] + obj.bbox[2]) / 2
            curr_center_y = (obj.bbox[1] + obj.bbox[3]) / 2
            prev_center_x = (prev_bbox['x1'] + prev_bbox['x2']) / 2
            prev_center_y = (prev_bbox['y1'] + prev_bbox['y2']) / 2
            
            dx = curr_center_x - prev_center_x
            dy = curr_center_y - prev_center_y
            distance = (dx**2 + dy**2)**0.5
            
            # Check for significant movement
            if distance > self.config.significant_movement_px:
                evidence.append({
                    "source": "movement",
                    "feature": "position_changed",
                    "value": f"{distance:.1f}px",
                    "conf": 1.0,
                    "object_id": obj.object_id
                })
            
            # Check for loitering (stationary for extended time)
            time_in_scene = timestamp - first_seen_ts
            if (distance < self.config.loitering_movement_px and 
                time_in_scene > self.config.loitering_time_s):
                evidence.append({
                    "source": "movement",
                    "feature": "loitering",
                    "value": f"{time_in_scene}s",
                    "conf": 1.0,
                    "object_id": obj.object_id
                })
        
        except (json.JSONDecodeError, KeyError, TypeError):
            # Invalid box data, skip analysis
            pass
        
        return evidence


def build_observed_objects(
    objects: List[any],
) -> List[ObservedObject]:
    """
    Convert API object format to ObservedObject format.
    
    Args:
        objects: List of objects from API request (with bbox and props)
    
    Returns:
        List of ObservedObject instances
    """
    observed = []
    
    for obj in objects:
        # Handle different bbox formats
        if hasattr(obj, 'bbox') and isinstance(obj.bbox, (list, tuple)):
            bbox = tuple(obj.bbox)
        else:
            continue
        
        # Extract scene_track_key from props
        track_key = None
        if hasattr(obj, 'props') and isinstance(obj.props, dict):
            track_key = obj.props.get('scene_track_key')
        
        observed.append(ObservedObject(
            object_id=obj.object_id if hasattr(obj, 'object_id') else 0,
            label=obj.label if hasattr(obj, 'label') else 'unknown',
            bbox=bbox,
            scene_track_key=track_key
        ))
    
    return observed

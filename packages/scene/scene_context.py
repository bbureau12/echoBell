# packages/scene/scene_context.py
"""
Scene context queries for policy evaluation.

Provides helpers to understand the CURRENT scene state (not just individual events),
enabling policies to react to scene complexity and concurrent intents.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional


@dataclass
class ActiveIntent:
    """Represents an intent that's currently active in the scene."""
    intent: str
    urgency: int
    confidence: float
    event_id: str
    visitor_id: Optional[str]
    plate_hmac: Optional[str]
    detected_ts: int
    track_key: str
    track_type: str  # "vehicle" or "person"
    camera_id: int  # Which camera detected this intent


def get_active_scene_intents(
    conn: sqlite3.Connection,
    *,
    camera_id: int,
    now_ts: int,
    grace_period_s: int = 6,
    lookback_window_s: int = 3600,
) -> list[ActiveIntent]:
    """
    Get all intents for entities currently present in the scene.
    
    This is the key function for understanding scene complexity:
    - "What intents are active RIGHT NOW?"
    - "Is there both a technician AND authority present?"
    - "What's the highest urgency in the current scene?"
    
    Args:
        conn: Database connection
        camera_id: Camera to query
        now_ts: Current timestamp
        grace_period_s: Scene tracker grace period (default 6s)
        lookback_window_s: How far back to look for events (default 1 hour)
    
    Returns:
        List of ActiveIntent objects for currently present entities
    """
    cutoff_ts = now_ts - grace_period_s
    event_window = now_ts - lookback_window_s
    
    # Query active tracks and join with their most recent events
    rows = conn.execute(
        """
        SELECT 
            ve.intent_inferred,
            ve.urgency,
            ve.intent_confidence,
            ve.event_id,
            ve.visitor_id,
            st.track_key,
            st.track_type,
            ve.detected_ts,
            ve.camera_id
        FROM scene_tracks st
        LEFT JOIN visitor_event_plate_sightings veps 
          ON st.track_key = veps.plate_hmac 
          AND st.track_type = 'vehicle'
        LEFT JOIN visitor_events ve 
          ON veps.event_id = ve.event_id
          AND ve.detected_ts >= ?
        WHERE st.camera_id = ?
          AND st.active = 1
          AND st.last_seen_ts >= ?
          AND ve.intent_inferred IS NOT NULL
        
        UNION
        
        SELECT 
            ve.intent_inferred,
            ve.urgency,
            ve.intent_confidence,
            ve.event_id,
            ve.visitor_id,
            st.track_key,
            st.track_type,
            ve.detected_ts,
            ve.camera_id
        FROM scene_tracks st
        LEFT JOIN visitor_events ve 
          ON st.track_key = ve.visitor_id
          AND st.track_type = 'person'
          AND ve.detected_ts >= ?
        WHERE st.camera_id = ?
          AND st.active = 1
          AND st.last_seen_ts >= ?
          AND ve.intent_inferred IS NOT NULL
        
        ORDER BY urgency DESC, detected_ts DESC
        """,
        (event_window, camera_id, cutoff_ts, event_window, camera_id, cutoff_ts),
    ).fetchall()
    
    intents = []
    seen_tracks = set()  # Avoid duplicates
    
    for intent, urgency, conf, event_id, visitor_id, track_key, track_type, detected_ts, cam_id in rows:
        # Only include the most recent event per track
        if track_key in seen_tracks:
            continue
        seen_tracks.add(track_key)
        
        plate_hmac = track_key if track_type == "vehicle" else None
        
        intents.append(
            ActiveIntent(
                intent=str(intent),
                urgency=int(urgency or 10),
                confidence=float(conf or 0.0),
                event_id=str(event_id),
                visitor_id=str(visitor_id) if visitor_id else None,
                plate_hmac=plate_hmac,
                detected_ts=int(detected_ts),
                track_key=str(track_key),
                track_type=str(track_type),
                camera_id=int(cam_id) if cam_id is not None else camera_id,
            )
        )
    
    return intents


def get_scene_urgency_level(
    conn: sqlite3.Connection,
    *,
    camera_id: int,
    now_ts: int,
    grace_period_s: int = 6,
) -> tuple[int, str, list[str]]:
    """
    Get the highest urgency level and description for the current scene.
    
    Returns:
        (max_urgency, description, active_intent_list)
    
    Examples:
        (90, "URGENT: Authority on scene", ["authority_urgent"])
        (30, "COMPLEX: 2 concurrent visitors", ["technician_visit", "authority_urgent"])
        (10, "normal", ["neighbor_help"])
    """
    active_intents = get_active_scene_intents(
        conn,
        camera_id=camera_id,
        now_ts=now_ts,
        grace_period_s=grace_period_s,
    )
    
    if not active_intents:
        return (0, "empty scene", [])
    
    max_urgency = max(ai.urgency for ai in active_intents)
    intent_names = [ai.intent for ai in active_intents]
    
    # Generate description
    if max_urgency >= 90:
        desc = f"URGENT: {active_intents[0].intent.replace('_', ' ').title()}"
    elif len(active_intents) > 1:
        desc = f"COMPLEX: {len(active_intents)} concurrent visitors"
    else:
        desc = "normal"
    
    return (max_urgency, desc, intent_names)


def check_concurrent_intents(
    conn: sqlite3.Connection,
    *,
    camera_id: int,
    now_ts: int,
    required_intents: list[str],
    grace_period_s: int = 6,
) -> bool:
    """
    Check if multiple specific intents are SIMULTANEOUSLY active.
    
    Example use cases:
        - Authority arrived WHILE technician present
        - Delivery WHILE resident present
        - Multiple unknown vehicles present
    
    Args:
        required_intents: List of intents that must all be present
        
    Returns:
        True if ALL required intents are currently active
    """
    active_intents = get_active_scene_intents(
        conn,
        camera_id=camera_id,
        now_ts=now_ts,
        grace_period_s=grace_period_s,
    )
    
    active_intent_names = {ai.intent for ai in active_intents}
    
    return all(intent in active_intent_names for intent in required_intents)

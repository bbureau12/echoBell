"""
Core service layer for policy API.

This module contains the business logic for policy management, scene tracking,
scheduled events, and evidence analysis. It provides a DRY foundation that can
be used by both the FastAPI HTTP endpoints and the MCP server.

All functions take a database connection as the first parameter to maintain
flexibility and testability.
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime

from packages.policy.evaluator import PolicyEvaluator
from packages.scene.movement_analyzer import MovementAnalyzer, MovementConfig


# ============================================================================
# Policy Management Services
# ============================================================================

def list_policies(conn: sqlite3.Connection, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    List all policies, optionally filtered by status.
    
    Args:
        conn: Database connection
        status: Optional filter ("active" or "disabled")
    
    Returns:
        List of policy dicts with id, name, description, conditions, actions, priority, status
    """
    query = """
        SELECT id, name, description, conditions_json, actions_json, priority, status, created_ts, updated_ts
        FROM policy_rules
    """
    params = []
    
    if status:
        query += " WHERE status = ?"
        params.append(status)
    
    query += " ORDER BY priority DESC, id ASC"
    
    cursor = conn.execute(query, params)
    policies = []
    
    for row in cursor.fetchall():
        policies.append({
            "id": row[0],
            "name": row[1],
            "description": row[2] or "",
            "conditions": json.loads(row[3]) if row[3] else {},
            "actions": json.loads(row[4]) if row[4] else {},
            "priority": row[5],
            "status": row[6],
            "created_ts": row[7],
            "updated_ts": row[8]
        })
    
    return policies


def get_policy(conn: sqlite3.Connection, policy_id: int) -> Optional[Dict[str, Any]]:
    """
    Get a single policy by ID.
    
    Args:
        conn: Database connection
        policy_id: Policy ID
    
    Returns:
        Policy dict or None if not found
    """
    cursor = conn.execute(
        """
        SELECT id, name, description, conditions_json, actions_json, priority, status, created_ts, updated_ts
        FROM policy_rules WHERE id = ?
        """,
        (policy_id,)
    )
    row = cursor.fetchone()
    
    if not row:
        return None
    
    return {
        "id": row[0],
        "name": row[1],
        "description": row[2] or "",
        "conditions": json.loads(row[3]) if row[3] else {},
        "actions": json.loads(row[4]) if row[4] else {},
        "priority": row[5],
        "status": row[6],
        "created_ts": row[7],
        "updated_ts": row[8]
    }


def create_policy(
    conn: sqlite3.Connection,
    name: str,
    conditions: Dict[str, Any],
    actions: Dict[str, Any],
    priority: int = 50,
    description: str = "",
    status: str = "active"
) -> Dict[str, Any]:
    """
    Create a new policy.
    
    Args:
        conn: Database connection
        name: Policy name
        conditions: Policy conditions dict
        actions: Policy actions dict
        priority: Priority (higher = more important)
        description: Optional description
        status: "active" or "disabled"
    
    Returns:
        Created policy dict
    """
    now = int(time.time())
    
    cursor = conn.execute(
        """
        INSERT INTO policy_rules (name, description, conditions_json, actions_json, priority, status, created_ts, updated_ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (name, description, json.dumps(conditions), json.dumps(actions), priority, status, now, now)
    )
    
    policy_id = cursor.lastrowid
    conn.commit()
    
    return {
        "id": policy_id,
        "name": name,
        "description": description,
        "conditions": conditions,
        "actions": actions,
        "priority": priority,
        "status": status,
        "created_ts": now,
        "updated_ts": now
    }


def update_policy(
    conn: sqlite3.Connection,
    policy_id: int,
    name: Optional[str] = None,
    description: Optional[str] = None,
    conditions: Optional[Dict[str, Any]] = None,
    actions: Optional[Dict[str, Any]] = None,
    priority: Optional[int] = None,
    status: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Update an existing policy (partial update).
    
    Args:
        conn: Database connection
        policy_id: Policy ID
        name: Optional new name
        description: Optional new description
        conditions: Optional new conditions
        actions: Optional new actions
        priority: Optional new priority
        status: Optional new status
    
    Returns:
        Updated policy dict or None if not found
    """
    # Check if policy exists
    existing = get_policy(conn, policy_id)
    if not existing:
        return None
    
    # Build update query dynamically
    updates = []
    params = []
    
    if name is not None:
        updates.append("name = ?")
        params.append(name)
    
    if description is not None:
        updates.append("description = ?")
        params.append(description)
    
    if conditions is not None:
        updates.append("conditions_json = ?")
        params.append(json.dumps(conditions))
    
    if actions is not None:
        updates.append("actions_json = ?")
        params.append(json.dumps(actions))
    
    if priority is not None:
        updates.append("priority = ?")
        params.append(priority)
    
    if status is not None:
        updates.append("status = ?")
        params.append(status)
    
    if not updates:
        return existing
    
    # Add updated_ts
    updates.append("updated_ts = ?")
    params.append(int(time.time()))
    
    # Add policy_id for WHERE clause
    params.append(policy_id)
    
    query = f"UPDATE policy_rules SET {', '.join(updates)} WHERE id = ?"
    conn.execute(query, params)
    conn.commit()
    
    return get_policy(conn, policy_id)


def delete_policy(conn: sqlite3.Connection, policy_id: int) -> bool:
    """
    Delete a policy by ID.
    
    Args:
        conn: Database connection
        policy_id: Policy ID
    
    Returns:
        True if deleted, False if not found
    """
    cursor = conn.execute("DELETE FROM policy_rules WHERE id = ?", (policy_id,))
    conn.commit()
    return cursor.rowcount > 0


def evaluate_policy_conditions(
    conn: sqlite3.Connection,
    policy_id: int,
    evidence: List[Dict[str, Any]],
    timestamp: Optional[int] = None
) -> Dict[str, Any]:
    """
    Evaluate a policy's conditions against given evidence.
    
    Args:
        conn: Database connection
        policy_id: Policy ID to evaluate
        evidence: List of evidence dicts
        timestamp: Optional timestamp for evaluation (defaults to now)
    
    Returns:
        Dict with:
        - matched: bool (whether policy conditions matched)
        - policy: policy dict
        - evidence: evidence list
        - evaluation_details: detailed evaluation results
    """
    policy = get_policy(conn, policy_id)
    if not policy:
        raise ValueError(f"Policy {policy_id} not found")
    
    if timestamp is None:
        timestamp = int(time.time())
    
    evaluator = PolicyEvaluator(conn, timestamp)
    matched = evaluator.evaluate_conditions(policy["conditions"], evidence)
    
    return {
        "matched": matched,
        "policy": policy,
        "evidence": evidence,
        "timestamp": timestamp,
        "evaluation_details": {
            "conditions": policy["conditions"],
            "evidence_count": len(evidence)
        }
    }


# ============================================================================
# Scene Tracking Services
# ============================================================================

def get_active_tracks(conn: sqlite3.Connection, camera_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Get all active scene tracks, optionally filtered by camera.
    
    Args:
        conn: Database connection
        camera_id: Optional camera ID filter
    
    Returns:
        List of active track dicts
    """
    query = """
        SELECT id, camera_id, track_key, track_type, last_box_json, first_seen_ts, last_seen_ts, active
        FROM scene_tracks
        WHERE active = 1
    """
    params = []
    
    if camera_id is not None:
        query += " AND camera_id = ?"
        params.append(camera_id)
    
    query += " ORDER BY last_seen_ts DESC"
    
    cursor = conn.execute(query, params)
    tracks = []
    
    for row in cursor.fetchall():
        bbox = json.loads(row[4]) if row[4] else None
        tracks.append({
            "id": row[0],
            "camera_id": row[1],
            "track_key": row[2],
            "track_type": row[3],
            "bbox": bbox,
            "first_seen_ts": row[5],
            "last_seen_ts": row[6],
            "active": bool(row[7])
        })
    
    return tracks


def query_scene_context(
    conn: sqlite3.Connection,
    camera_id: int,
    time_range_s: int = 300
) -> Dict[str, Any]:
    """
    Query recent scene context for a camera.
    
    Args:
        conn: Database connection
        camera_id: Camera ID
        time_range_s: Time range in seconds (default 5 minutes)
    
    Returns:
        Dict with active_tracks, recent_alerts, and visit_history
    """
    now = int(time.time())
    since_ts = now - time_range_s
    
    # Get active tracks
    active_tracks = get_active_tracks(conn, camera_id)
    
    # Get recent alerts
    cursor = conn.execute(
        """
        SELECT id, camera_id, timestamp, policy_name, evidence_json, delivered
        FROM alert_history
        WHERE camera_id = ? AND timestamp >= ?
        ORDER BY timestamp DESC
        """,
        (camera_id, since_ts)
    )
    
    recent_alerts = []
    for row in cursor.fetchall():
        recent_alerts.append({
            "id": row[0],
            "camera_id": row[1],
            "timestamp": row[2],
            "policy_name": row[3],
            "evidence": json.loads(row[4]) if row[4] else [],
            "delivered": bool(row[5])
        })
    
    # Get visit history (using scene_linkages if available)
    visit_history = get_visit_history(conn, camera_id, time_range_s)
    
    return {
        "camera_id": camera_id,
        "time_range_s": time_range_s,
        "active_tracks": active_tracks,
        "recent_alerts": recent_alerts,
        "visit_history": visit_history
    }


def get_visit_history(
    conn: sqlite3.Connection,
    camera_id: int,
    time_range_s: int = 86400
) -> List[Dict[str, Any]]:
    """
    Get visit history for a camera.
    
    Args:
        conn: Database connection
        camera_id: Camera ID
        time_range_s: Time range in seconds (default 24 hours)
    
    Returns:
        List of visit dicts with linkage information
    """
    now = int(time.time())
    since_ts = now - time_range_s
    
    # Check if scene_linkages table exists
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='scene_linkages'"
    )
    
    if not cursor.fetchone():
        # Fallback to scene_tracks if no linkages table
        cursor = conn.execute(
            """
            SELECT track_key, track_type, first_seen_ts, last_seen_ts
            FROM scene_tracks
            WHERE camera_id = ? AND first_seen_ts >= ?
            ORDER BY first_seen_ts DESC
            """,
            (camera_id, since_ts)
        )
        
        visits = []
        for row in cursor.fetchall():
            visits.append({
                "track_key": row[0],
                "track_type": row[1],
                "first_seen_ts": row[2],
                "last_seen_ts": row[3],
                "entity_id": None
            })
        
        return visits
    
    # Use scene_linkages for richer visit history
    cursor = conn.execute(
        """
        SELECT sl.entity_id, sl.track_key, st.track_type, st.first_seen_ts, st.last_seen_ts
        FROM scene_linkages sl
        JOIN scene_tracks st ON sl.track_key = st.track_key AND sl.camera_id = st.camera_id
        WHERE sl.camera_id = ? AND st.first_seen_ts >= ?
        ORDER BY st.first_seen_ts DESC
        """,
        (camera_id, since_ts)
    )
    
    visits = []
    for row in cursor.fetchall():
        visits.append({
            "entity_id": row[0],
            "track_key": row[1],
            "track_type": row[2],
            "first_seen_ts": row[3],
            "last_seen_ts": row[4]
        })
    
    return visits


# ============================================================================
# Scheduled Event Services
# ============================================================================

def list_scheduled_events(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """
    List all scheduled events (sorted by start time).
    
    Args:
        conn: Database connection
    
    Returns:
        List of scheduled event dicts
    """
    cursor = conn.execute("""
        SELECT id, name, description, start_ts, end_ts, policy_hint, created_ts, updated_ts
        FROM scheduled_event
        ORDER BY start_ts ASC
    """)
    
    events = []
    for row in cursor.fetchall():
        events.append({
            "id": row[0],
            "name": row[1],
            "description": row[2] or "",
            "start_ts": row[3],
            "end_ts": row[4],
            "policy_hint": row[5] or "",
            "created_ts": row[6],
            "updated_ts": row[7]
        })
    
    return events


def get_scheduled_event(conn: sqlite3.Connection, event_id: int) -> Optional[Dict[str, Any]]:
    """
    Get a scheduled event by ID.
    
    Args:
        conn: Database connection
        event_id: Event ID
    
    Returns:
        Event dict or None if not found
    """
    cursor = conn.execute(
        """
        SELECT id, name, description, start_ts, end_ts, policy_hint, created_ts, updated_ts
        FROM scheduled_event WHERE id = ?
        """,
        (event_id,)
    )
    row = cursor.fetchone()
    
    if not row:
        return None
    
    return {
        "id": row[0],
        "name": row[1],
        "description": row[2] or "",
        "start_ts": row[3],
        "end_ts": row[4],
        "policy_hint": row[5] or "",
        "created_ts": row[6],
        "updated_ts": row[7]
    }


def create_scheduled_event(
    conn: sqlite3.Connection,
    name: str,
    start_ts: int,
    end_ts: int,
    description: str = "",
    policy_hint: str = ""
) -> Dict[str, Any]:
    """
    Create a new scheduled event.
    
    Args:
        conn: Database connection
        name: Event name
        start_ts: Start timestamp
        end_ts: End timestamp
        description: Optional description
        policy_hint: Optional policy hint
    
    Returns:
        Created event dict
    """
    now = int(time.time())
    
    cursor = conn.execute(
        """
        INSERT INTO scheduled_event (name, description, start_ts, end_ts, policy_hint, created_ts, updated_ts)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (name, description, start_ts, end_ts, policy_hint, now, now)
    )
    
    event_id = cursor.lastrowid
    conn.commit()
    
    return {
        "id": event_id,
        "name": name,
        "description": description,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "policy_hint": policy_hint,
        "created_ts": now,
        "updated_ts": now
    }


def update_scheduled_event(
    conn: sqlite3.Connection,
    event_id: int,
    name: Optional[str] = None,
    description: Optional[str] = None,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    policy_hint: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Update a scheduled event (partial update).
    
    Args:
        conn: Database connection
        event_id: Event ID
        name: Optional new name
        description: Optional new description
        start_ts: Optional new start timestamp
        end_ts: Optional new end timestamp
        policy_hint: Optional new policy hint
    
    Returns:
        Updated event dict or None if not found
    """
    # Check if event exists
    existing = get_scheduled_event(conn, event_id)
    if not existing:
        return None
    
    # Build update query dynamically
    updates = []
    params = []
    
    if name is not None:
        updates.append("name = ?")
        params.append(name)
    
    if description is not None:
        updates.append("description = ?")
        params.append(description)
    
    if start_ts is not None:
        updates.append("start_ts = ?")
        params.append(start_ts)
    
    if end_ts is not None:
        updates.append("end_ts = ?")
        params.append(end_ts)
    
    if policy_hint is not None:
        updates.append("policy_hint = ?")
        params.append(policy_hint)
    
    if not updates:
        return existing
    
    # Add updated_ts
    updates.append("updated_ts = ?")
    params.append(int(time.time()))
    
    # Add event_id for WHERE clause
    params.append(event_id)
    
    query = f"UPDATE scheduled_event SET {', '.join(updates)} WHERE id = ?"
    conn.execute(query, params)
    conn.commit()
    
    return get_scheduled_event(conn, event_id)


def delete_scheduled_event(conn: sqlite3.Connection, event_id: int) -> bool:
    """
    Delete a scheduled event by ID.
    
    Args:
        conn: Database connection
        event_id: Event ID
    
    Returns:
        True if deleted, False if not found
    """
    cursor = conn.execute("DELETE FROM scheduled_event WHERE id = ?", (event_id,))
    conn.commit()
    return cursor.rowcount > 0


def get_active_events(conn: sqlite3.Connection, timestamp: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Get all events active at a given timestamp.
    
    Args:
        conn: Database connection
        timestamp: Timestamp to check (defaults to now)
    
    Returns:
        List of active event dicts
    """
    if timestamp is None:
        timestamp = int(time.time())
    
    cursor = conn.execute(
        """
        SELECT id, name, description, start_ts, end_ts, policy_hint, created_ts, updated_ts
        FROM scheduled_event
        WHERE start_ts <= ? AND end_ts >= ?
        ORDER BY start_ts ASC
        """,
        (timestamp, timestamp)
    )
    
    events = []
    for row in cursor.fetchall():
        events.append({
            "id": row[0],
            "name": row[1],
            "description": row[2] or "",
            "start_ts": row[3],
            "end_ts": row[4],
            "policy_hint": row[5] or "",
            "created_ts": row[6],
            "updated_ts": row[7]
        })
    
    return events


# ============================================================================
# Alert History Services
# ============================================================================

def get_alert_history(
    conn: sqlite3.Connection,
    camera_id: Optional[int] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """
    Get recent alert history.
    
    Args:
        conn: Database connection
        camera_id: Optional camera ID filter
        limit: Maximum number of alerts to return
    
    Returns:
        List of alert dicts
    """
    query = """
        SELECT id, camera_id, timestamp, policy_name, evidence_json, delivered
        FROM alert_history
    """
    params = []
    
    if camera_id is not None:
        query += " WHERE camera_id = ?"
        params.append(camera_id)
    
    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    
    cursor = conn.execute(query, params)
    alerts = []
    
    for row in cursor.fetchall():
        alerts.append({
            "id": row[0],
            "camera_id": row[1],
            "timestamp": row[2],
            "policy_name": row[3],
            "evidence": json.loads(row[4]) if row[4] else [],
            "delivered": bool(row[5])
        })
    
    return alerts

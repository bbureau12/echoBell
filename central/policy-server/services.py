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
import os
import sys
import sqlite3
import time
import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime

from packages.policy.evaluator import PolicyEvaluator
from packages.scene.movement_analyzer import MovementAnalyzer, MovementConfig

# Setup logging
logger = logging.getLogger(__name__)

# Project root for imports
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

# Import Echonet mode service (lazy-loaded)
_echonet_mode_service = None

def get_echonet_mode_service():
    """Get Echonet mode service (lazy-loaded)"""
    global _echonet_mode_service
    if _echonet_mode_service is None:
        try:
            from echonet_mode_service import get_echonet_mode_service as _get_svc
            _echonet_mode_service = _get_svc()
        except Exception:
            pass
    return _echonet_mode_service


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
        logger.error(f"Policy evaluation failed: policy {policy_id} not found")
        raise ValueError(f"Policy {policy_id} not found")
    
    if timestamp is None:
        timestamp = int(time.time())
    
    logger.info(f"Evaluating policy {policy_id} ('{policy['name']}') against {len(evidence)} evidence items")
    
    evaluator = PolicyEvaluator(conn, timestamp)
    matched = evaluator.evaluate_conditions(policy["conditions"], evidence)
    
    if matched:
        logger.info(f"Policy {policy_id} MATCHED: {policy['name']}")
    else:
        logger.debug(f"Policy {policy_id} did not match: {policy['name']}")
    
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


# ============================================================================
# Voice Command Services
# ============================================================================

def get_voiceprint_person_mapping(
    conn: sqlite3.Connection,
    voiceprint_user_id: str
) -> Optional[int]:
    """
    Get trusted_person_id for a given voiceprint_user_id.
    
    Args:
        conn: Database connection
        voiceprint_user_id: Echonet voiceprint user ID
    
    Returns:
        trusted_person_id if mapping exists, None otherwise
    """
    cursor = conn.execute(
        "SELECT trusted_person_id FROM voiceprint_person_mapping WHERE voiceprint_user_id = ?",
        (voiceprint_user_id,)
    )
    row = cursor.fetchone()
    return row[0] if row else None


def create_voiceprint_person_mapping(
    conn: sqlite3.Connection,
    voiceprint_user_id: str,
    trusted_person_id: int,
    notes: Optional[str] = None
) -> int:
    """
    Create a mapping between Echonet voiceprint ID and trusted person.
    
    Args:
        conn: Database connection
        voiceprint_user_id: Echonet voiceprint user ID
        trusted_person_id: Our trusted person ID
        notes: Optional notes
    
    Returns:
        Mapping ID
    """
    now = int(time.time())
    cursor = conn.execute(
        """
        INSERT INTO voiceprint_person_mapping (voiceprint_user_id, trusted_person_id, created_ts, updated_ts, notes)
        VALUES (?, ?, ?, ?, ?)
        """,
        (voiceprint_user_id, trusted_person_id, now, now, notes)
    )
    conn.commit()
    return cursor.lastrowid


def list_voiceprint_mappings(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """
    List all voiceprint to person mappings.
    
    Args:
        conn: Database connection
    
    Returns:
        List of mapping dicts with person names
    """
    cursor = conn.execute(
        """
        SELECT 
            vpm.id,
            vpm.voiceprint_user_id,
            vpm.trusted_person_id,
            tp.name as person_name,
            vpm.created_ts,
            vpm.updated_ts,
            vpm.notes
        FROM voiceprint_person_mapping vpm
        LEFT JOIN trusted_person tp ON vpm.trusted_person_id = tp.trusted_id
        ORDER BY vpm.created_ts DESC
        """
    )
    
    mappings = []
    for row in cursor.fetchall():
        mappings.append({
            "id": row[0],
            "voiceprint_user_id": row[1],
            "trusted_person_id": row[2],
            "person_name": row[3],
            "created_ts": row[4],
            "updated_ts": row[5],
            "notes": row[6]
        })
    
    return mappings


def create_voice_command(
    conn: sqlite3.Connection,
    correlation_id: str,
    echonet_event: Dict[str, Any],
    trusted_person_id: Optional[int] = None,
    auth_result: str = "pending",
    auth_reason: Optional[str] = None,
    client_ip: Optional[str] = None
) -> int:
    """
    Create a voice command record.
    
    Args:
        conn: Database connection
        correlation_id: Our internal correlation ID
        echonet_event: Echonet event payload dict
        trusted_person_id: Mapped trusted person ID
        auth_result: Authorization result ('allowed', 'denied', '2fa_required')
        auth_reason: Why allowed/denied
        client_ip: Client IP address for audit trail
    
    Returns:
        Voice command ID
    """
    now = int(time.time())
    cursor = conn.execute(
        """
        INSERT INTO voice_commands (
            correlation_id, echonet_event_id, session_id,
            voiceprint_user_id, voiceprint_confidence, trusted_person_id,
            text, speech_confidence, mode,
            source_device, room, timestamp, received_ts,
            auth_result, auth_reason, client_ip, created_ts
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            correlation_id,
            echonet_event.get("event_id"),
            echonet_event.get("session_id"),
            echonet_event.get("voiceprint_user_id"),
            echonet_event.get("voiceprint_confidence"),
            trusted_person_id,
            echonet_event.get("text"),
            echonet_event.get("confidence"),
            echonet_event.get("mode"),
            echonet_event.get("source_id"),
            echonet_event.get("room"),
            echonet_event.get("ts"),
            now,
            auth_result,
            auth_reason,
            client_ip,
            now
        )
    )
    conn.commit()
    return cursor.lastrowid


def update_voice_command_result(
    conn: sqlite3.Connection,
    voice_command_id: int,
    policy_matched: Optional[str] = None,
    llm_used: bool = False,
    response_text: Optional[str] = None,
    actions_taken: Optional[List[str]] = None,
    processing_time_ms: Optional[int] = None
) -> None:
    """
    Update voice command with processing results.
    
    Args:
        conn: Database connection
        voice_command_id: Voice command ID to update
        policy_matched: Policy ID that handled this
        llm_used: Whether LLM was used
        response_text: Response sent to user
        actions_taken: List of actions executed
        processing_time_ms: Processing time in milliseconds
    """
    actions_json = json.dumps(actions_taken) if actions_taken else None
    
    conn.execute(
        """
        UPDATE voice_commands
        SET policy_matched = ?,
            llm_used = ?,
            response_text = ?,
            actions_taken = ?,
            processing_time_ms = ?
        WHERE id = ?
        """,
        (policy_matched, 1 if llm_used else 0, response_text, actions_json, processing_time_ms, voice_command_id)
    )
    conn.commit()


def get_voice_command_by_correlation(
    conn: sqlite3.Connection,
    correlation_id: str
) -> Optional[Dict[str, Any]]:
    """
    Get voice command by correlation ID.
    
    Args:
        conn: Database connection
        correlation_id: Correlation ID to look up
    
    Returns:
        Voice command dict if found, None otherwise
    """
    cursor = conn.execute(
        """
        SELECT 
            id, correlation_id, echonet_event_id, session_id,
            voiceprint_user_id, voiceprint_confidence, trusted_person_id,
            text, speech_confidence, mode,
            source_device, room, timestamp, received_ts,
            policy_matched, llm_used, response_text, actions_taken,
            auth_result, auth_reason, created_ts, processing_time_ms
        FROM voice_commands
        WHERE correlation_id = ?
        """,
        (correlation_id,)
    )
    row = cursor.fetchone()
    if not row:
        return None
    
    return {
        "id": row[0],
        "correlation_id": row[1],
        "echonet_event_id": row[2],
        "session_id": row[3],
        "voiceprint_user_id": row[4],
        "voiceprint_confidence": row[5],
        "trusted_person_id": row[6],
        "text": row[7],
        "speech_confidence": row[8],
        "mode": row[9],
        "source_device": row[10],
        "room": row[11],
        "timestamp": row[12],
        "received_ts": row[13],
        "policy_matched": row[14],
        "llm_used": bool(row[15]),
        "response_text": row[16],
        "actions_taken": json.loads(row[17]) if row[17] else None,
        "auth_result": row[18],
        "auth_reason": row[19],
        "created_ts": row[20],
        "processing_time_ms": row[21]
    }


def get_mcp_tool_permission(
    conn: sqlite3.Connection,
    tool_name: str
) -> Optional[Dict[str, Any]]:
    """
    Get MCP tool permission settings for voice commands.
    
    Args:
        conn: Database connection
        tool_name: Name of MCP tool
    
    Returns:
        Permission dict if exists, None otherwise
    """
    cursor = conn.execute(
        """
        SELECT tool_name, voice_enabled, requires_confidence, requires_2fa, security_level, notes, created_ts, updated_ts
        FROM mcp_tool_permissions
        WHERE tool_name = ?
        """,
        (tool_name,)
    )
    row = cursor.fetchone()
    if not row:
        return None
    
    return {
        "tool_name": row[0],
        "voice_enabled": bool(row[1]),
        "requires_confidence": row[2],
        "requires_2fa": bool(row[3]),
        "security_level": row[4],
        "notes": row[5],
        "created_ts": row[6],
        "updated_ts": row[7]
    }


def list_mcp_tool_permissions(
    conn: sqlite3.Connection,
    voice_enabled_only: bool = False
) -> List[Dict[str, Any]]:
    """
    List all MCP tool permissions.
    
    Args:
        conn: Database connection
        voice_enabled_only: Only return voice-enabled tools
    
    Returns:
        List of permission dicts
    """
    query = """
        SELECT tool_name, voice_enabled, requires_confidence, requires_2fa, security_level, notes, created_ts, updated_ts
        FROM mcp_tool_permissions
    """
    params = []
    
    if voice_enabled_only:
        query += " WHERE voice_enabled = 1"
    
    query += " ORDER BY security_level, tool_name"
    
    cursor = conn.execute(query, params)
    permissions = []
    
    for row in cursor.fetchall():
        permissions.append({
            "tool_name": row[0],
            "voice_enabled": bool(row[1]),
            "requires_confidence": row[2],
            "requires_2fa": bool(row[3]),
            "security_level": row[4],
            "notes": row[5],
            "created_ts": row[6],
            "updated_ts": row[7]
        })
    
    return permissions


def check_voice_authorization(
    conn: sqlite3.Connection,
    text: str,
    voiceprint_confidence: Optional[float],
    tool_name: Optional[str] = None
) -> Tuple[bool, str, Optional[str]]:
    """
    Check if a voice command is authorized.
    
    Args:
        conn: Database connection
        text: Command text
        voiceprint_confidence: Voiceprint match confidence (0-1)
        tool_name: MCP tool name if calling a tool
    
    Returns:
        Tuple of (allowed, reason, action_required)
    """
    logger.info(f"Checking voice authorization: text='{text[:50]}...', confidence={voiceprint_confidence}, tool={tool_name}")
    
    # Check voiceprint confidence threshold
    if voiceprint_confidence is None or voiceprint_confidence < 0.75:
        logger.warning(f"Voice authorization DENIED: voiceprint confidence {voiceprint_confidence} below 0.75 threshold")
        return (False, "voiceprint_confidence_too_low", "request_telegram_confirmation")
    
    # If calling a specific MCP tool, check its permissions
    if tool_name:
        permission = get_mcp_tool_permission(conn, tool_name)
        if not permission:
            logger.warning(f"Voice authorization DENIED: tool '{tool_name}' not found")
            return (False, "tool_not_found", None)
        
        if not permission["voice_enabled"]:
            logger.warning(f"Voice authorization DENIED: tool '{tool_name}' not voice-enabled")
            return (False, "tool_not_voice_enabled", None)
        
        if voiceprint_confidence < permission["requires_confidence"]:
            logger.warning(f"Voice authorization DENIED: confidence {voiceprint_confidence} below tool threshold {permission['requires_confidence']}")
            return (False, f"confidence_below_tool_threshold_{permission['requires_confidence']}", "request_telegram_confirmation")
        
        if permission["requires_2fa"]:
            logger.info(f"Voice authorization DEFERRED: tool '{tool_name}' requires 2FA")
            return (False, "tool_requires_2fa", "request_telegram_confirmation")
        
        # Check for security actions in text
        if permission["security_level"] in ["high", "critical"]:
            security_keywords = ["unlock", "disable", "delete", "remove", "open"]
            if any(keyword in text.lower() for keyword in security_keywords):
                if voiceprint_confidence < 0.95:
                    logger.warning(f"Voice authorization DENIED: security action requires confidence >= 0.95, got {voiceprint_confidence}")
                    return (False, "security_action_requires_high_confidence", "request_telegram_confirmation")
    
    logger.info(f"Voice authorization ALLOWED: confidence={voiceprint_confidence}, tool={tool_name}")
    return (True, "authorized", None)


# ============================================================================
# Echonet Mode Control Services
# ============================================================================

async def activate_echonet_listening(
    echonet_url: str,
    target_name: str = "echobell",
    source: str = "llm",
    reason: str = "Requesting additional information"
) -> Dict[str, Any]:
    """
    Activate open listening mode on an Echonet instance.
    
    Allows the LLM to request voice input from the user without requiring
    the wake word to be said again.
    
    Args:
        echonet_url: Base URL of Echonet instance (e.g., http://192.168.1.50:8123)
        target_name: Target name registered with Echonet (default: "echobell")
        source: Source of the request (default: "llm")
        reason: Human-readable reason for activation
    
    Returns:
        Dict with success status and message
    """
    service = get_echonet_mode_service()
    if not service:
        return {
            "success": False,
            "error": "Echonet mode service not available",
            "message": "Service not initialized"
        }
    
    return await service.activate_listening(
        echonet_url=echonet_url,
        target_name=target_name,
        source=source,
        reason=reason
    )


async def deactivate_echonet_listening(
    echonet_url: str,
    target_name: str = "echobell",
    source: str = "llm",
    reason: str = "Conversation complete"
) -> Dict[str, Any]:
    """
    Deactivate open listening mode (return to trigger mode).
    
    Args:
        echonet_url: Base URL of Echonet instance
        target_name: Target name (default: "echobell")
        source: Source of the request (default: "llm")
        reason: Human-readable reason for deactivation
    
    Returns:
        Dict with success status and message
    """
    service = get_echonet_mode_service()
    if not service:
        return {
            "success": False,
            "error": "Echonet mode service not available",
            "message": "Service not initialized"
        }
    
    return await service.deactivate_listening(
        echonet_url=echonet_url,
        target_name=target_name,
        source=source,
        reason=reason
    )


async def get_echonet_instances_status(
    conn: sqlite3.Connection
) -> List[Dict[str, Any]]:
    """
    Get status of all discovered Echonet instances.
    
    Combines Echonet discovery information with their current state.
    
    Args:
        conn: Database connection (for future use with caching)
    
    Returns:
        List of Echonet instances with their status
    """
    # Import here to avoid circular dependencies
    try:
        from echonet_service import get_echonet_service
        echonet_svc = get_echonet_service()
        
        if not echonet_svc or not echonet_svc.listener:
            return []
        
        instances = []
        for inst in echonet_svc.listener.instances.values():
            # Get state from Echonet
            mode_service = get_echonet_mode_service()
            state = None
            if mode_service:
                state_data = await mode_service.get_echonet_state(inst.base_url)
                if state_data:
                    state = state_data.get("listen_mode")
            
            instances.append({
                "name": inst.display_name,
                "url": inst.base_url,
                "zone": inst.zone,
                "subzone": inst.subzone,
                "current_mode": state,
                "registered": inst.name in echonet_svc.registered_instances
            })
        
        return instances
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to get Echonet instances: {e}")
        return []


# ============================================================================
# Visitor Intent Reclassification Services
# ============================================================================

def reclassify_visitor_intent(
    conn: sqlite3.Connection,
    event_id: str,
    additional_evidence: Optional[List[Dict[str, Any]]] = None,
    override_intent: Optional[str] = None,
    override_confidence: Optional[float] = None,
    reason: Optional[str] = None,
    reclassified_by: str = "llm"
) -> Dict[str, Any]:
    """
    Reclassify a visitor event's intent with additional evidence or direct override.
    
    This allows the LLM to correct misclassifications by either:
    1. Adding evidence and re-running classification (respects existing rules)
    2. Directly overriding the intent (bypasses rules, use sparingly)
    
    The function maintains full audit trail by:
    - Incrementing reclassification_count
    - Storing original intent before changes
    - Recording who/why reclassified
    - Preserving evidence trace
    
    Args:
        conn: Database connection
        event_id: Visitor event ID to reclassify
        additional_evidence: Evidence to inject (e.g., [{"source": "llm", "feature": "uniform_type", "value": "ups", "conf": 0.95}])
        override_intent: If provided, directly set intent without re-classification
        override_confidence: Confidence for override (required if override_intent provided)
        reason: Human-readable reason for reclassification
        reclassified_by: Source identifier (default: "llm")
    
    Returns:
        Dict with:
        - success: bool
        - original_intent: str
        - new_intent: str
        - original_confidence: float
        - new_confidence: float
        - method: str ("evidence_injection" or "direct_override")
        - trace: List[str] (classification reasoning)
    """
    import json
    from datetime import datetime
    
    logger.info(f"Reclassifying visitor event {event_id} by {reclassified_by}: override={override_intent}, evidence_count={len(additional_evidence) if additional_evidence else 0}")
    
    # Validate inputs
    if override_intent and override_confidence is None:
        logger.error(f"Reclassification failed: override_confidence required when override_intent is provided")
        return {
            "success": False,
            "error": "override_confidence required when override_intent is provided"
        }
    
    # Fetch the visitor event
    cursor = conn.execute("""
        SELECT event_id, visitor_id, camera_id, detected_ts, 
               intent_inferred, intent_confidence, evidence_json, urgency
        FROM visitor_events
        WHERE event_id = ?
    """, (event_id,))
    
    row = cursor.fetchone()
    if not row:
        return {
            "success": False,
            "error": f"Visitor event not found: {event_id}"
        }
    
    (event_id, visitor_id, camera_id, detected_ts, 
     original_intent, original_confidence, evidence_json, urgency) = row
    
    # Parse existing evidence
    try:
        evidence_data = json.loads(evidence_json) if evidence_json else {}
    except (json.JSONDecodeError, TypeError):
        evidence_data = {}
    
    # Store original values for audit
    original_values = {
        "intent": original_intent,
        "confidence": original_confidence,
        "evidence": evidence_data.copy()
    }
    
    new_intent = original_intent
    new_confidence = original_confidence
    new_urgency = urgency
    trace = []
    method = None
    
    # OPTION 1: Direct Override (bypasses classification rules)
    if override_intent is not None:
        logger.info(f"Using direct override method: {original_intent} → {override_intent} (conf {override_confidence})")
        new_intent = override_intent
        new_confidence = override_confidence
        method = "direct_override"
        trace.append(f"Intent directly overridden by {reclassified_by}: {original_intent} → {new_intent}")
        trace.append(f"Confidence: {original_confidence:.2f} → {new_confidence:.2f}")
        if reason:
            trace.append(f"Reason: {reason}")
    
    # OPTION 2: Evidence Injection + Re-classification (respects rules)
    elif additional_evidence:
        logger.info(f"Using evidence injection method: adding {len(additional_evidence)} evidence items")
        method = "evidence_injection"
        
        # Import classification logic
        try:
            sys.path.insert(0, os.path.join(PROJECT_ROOT, "packages"))
            from packages.common.types import VisionResult, Evidence, SceneObject
            from packages.classify.intent import classify
            
            # Reconstruct VisionResult from stored evidence
            # Get vision objects from evidence_data if available
            stored_objects = evidence_data.get("objects", [])
            vision_objects = []
            
            for obj_data in stored_objects:
                # Reconstruct SceneObject
                obj = SceneObject(
                    object_id=obj_data.get("object_id", 0),
                    label=obj_data.get("label", "unknown"),
                    conf=obj_data.get("conf", 0.0),
                    box=obj_data.get("box", [0, 0, 0, 0]),
                    props=obj_data.get("props", {})
                )
                vision_objects.append(obj)
            
            # Reconstruct existing evidence
            stored_evidence = evidence_data.get("evidence", [])
            vision_evidence = []
            
            for ev_data in stored_evidence:
                ev = Evidence(
                    source=ev_data.get("source", "unknown"),
                    key=ev_data.get("key", ""),
                    value=ev_data.get("value", ""),
                    confidence=ev_data.get("confidence", 0.0),
                    object_id=ev_data.get("object_id"),
                    metadata=ev_data.get("metadata", {})
                )
                vision_evidence.append(ev)
            
            # Add LLM-provided evidence
            for llm_ev in additional_evidence:
                ev = Evidence(
                    source=llm_ev.get("source", "llm"),
                    key=llm_ev.get("key") or llm_ev.get("feature", ""),
                    value=str(llm_ev.get("value", "")),
                    confidence=float(llm_ev.get("conf") or llm_ev.get("confidence", 0.95)),
                    object_id=llm_ev.get("object_id"),
                    metadata={
                        "injected_by": reclassified_by,
                        "reason": reason or "Evidence correction"
                    }
                )
                vision_evidence.append(ev)
                trace.append(f"Added evidence: {ev.source}.{ev.key} = {ev.value} (conf={ev.confidence:.2f})")
            
            # Create VisionResult with enriched evidence
            vision = VisionResult(
                objects=vision_objects,
                evidence=vision_evidence,
                snapshot_path=evidence_data.get("snapshot_path")
            )
            
            # Re-classify with enriched evidence
            db_path = os.getenv("ECHOBELL_DB_PATH", os.path.join(PROJECT_ROOT, "echoBell.db"))
            text = evidence_data.get("text", "")
            
            classified = classify(text=text, vision=vision, db_path=db_path)
            
            new_intent = classified.intent
            new_confidence = classified.conf
            new_urgency = classified.urgency
            trace.extend(classified.trace)
            
            trace.insert(0, f"Re-classified with {len(additional_evidence)} additional evidence items")
            trace.insert(1, f"Result: {original_intent} (conf={original_confidence:.2f}) → {new_intent} (conf={new_confidence:.2f})")
            
        except ImportError as e:
            return {
                "success": False,
                "error": f"Failed to import classification modules: {e}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Re-classification failed: {e}",
                "trace": trace
            }
    else:
        return {
            "success": False,
            "error": "Must provide either additional_evidence or override_intent"
        }
    
    # Update visitor_events with new intent
    now_ts = int(datetime.now().timestamp())
    
    # Check if reclassification columns exist
    cursor = conn.execute("PRAGMA table_info(visitor_events)")
    columns = {row[1] for row in cursor.fetchall()}
    
    has_reclass_count = "reclassification_count" in columns
    has_reclass_by = "reclassified_by" in columns
    has_reclass_reason = "reclassification_reason" in columns
    has_reclass_ts = "reclassified_ts" in columns
    
    # Build update query based on available columns
    update_parts = [
        "intent_inferred = ?",
        "intent_confidence = ?",
        "urgency = ?"
    ]
    params = [new_intent, new_confidence, new_urgency]
    
    if has_reclass_count:
        update_parts.append("reclassification_count = COALESCE(reclassification_count, 0) + 1")
    if has_reclass_by:
        update_parts.append("reclassified_by = ?")
        params.append(reclassified_by)
    if has_reclass_reason:
        update_parts.append("reclassification_reason = ?")
        params.append(reason or "LLM reclassification")
    if has_reclass_ts:
        update_parts.append("reclassified_ts = ?")
        params.append(now_ts)
    
    params.append(event_id)
    
    update_query = f"""
        UPDATE visitor_events
        SET {", ".join(update_parts)}
        WHERE event_id = ?
    """
    
    conn.execute(update_query, params)
    
    # Update visitor intent memory if visitor_id exists
    if visitor_id:
        try:
            sys.path.insert(0, os.path.join(PROJECT_ROOT, "packages"))
            from packages.perception.visitor import update_visitor_intent_memory
            
            update_visitor_intent_memory(
                conn=conn,
                visitor_id=visitor_id,
                intent=new_intent,
                conf=new_confidence,
                now_ts=now_ts
            )
        except Exception as e:
            # Don't fail if visitor memory update fails
            trace.append(f"Warning: Failed to update visitor memory: {e}")
    
    conn.commit()
    
    changed = (new_intent != original_intent) or (abs(float(new_confidence or 0) - float(original_confidence or 0)) > 0.01)
    
    if changed:
        logger.info(f"Reclassification SUCCESS: event {event_id} changed from '{original_intent}' (conf={original_confidence:.2f}) to '{new_intent}' (conf={new_confidence:.2f}) via {method}")
    else:
        logger.info(f"Reclassification complete: event {event_id} remains '{new_intent}' (conf={new_confidence:.2f}), no change")
    
    return {
        "success": True,
        "event_id": event_id,
        "visitor_id": visitor_id,
        "original_intent": original_intent,
        "new_intent": new_intent,
        "original_confidence": float(original_confidence) if original_confidence else 0.0,
        "new_confidence": float(new_confidence),
        "original_urgency": urgency,
        "new_urgency": new_urgency,
        "method": method,
        "reclassified_by": reclassified_by,
        "reason": reason,
        "trace": trace,
        "changed": changed
    }


def get_visitor_event(
    conn: sqlite3.Connection,
    event_id: str
) -> Optional[Dict[str, Any]]:
    """
    Get details of a specific visitor event.
    
    Args:
        conn: Database connection
        event_id: Visitor event ID
    
    Returns:
        Dict with event details or None if not found
    """
    cursor = conn.execute("""
        SELECT event_id, visitor_id, camera_id, detected_ts,
               intent_inferred, intent_confidence, evidence_json,
               urgency, intent_locked, snapshot_path,
               duration_s
        FROM visitor_events
        WHERE event_id = ?
    """, (event_id,))
    
    row = cursor.fetchone()
    if not row:
        return None
    
    # Check for reclassification columns
    cursor = conn.execute("PRAGMA table_info(visitor_events)")
    columns = {row[1] for row in cursor.fetchall()}
    
    event_data = {
        "event_id": row[0],
        "visitor_id": row[1],
        "camera_id": row[2],
        "detected_ts": row[3],
        "intent": row[4],
        "intent_confidence": row[5],
        "evidence_json": row[6],
        "urgency": row[7],
        "intent_locked": row[8],
        "snapshot_path": row[9],
        "duration_s": row[10]
    }
    
    # Add reclassification data if available
    if "reclassification_count" in columns:
        cursor = conn.execute("""
            SELECT reclassification_count, reclassified_by, 
                   reclassification_reason, reclassified_ts
            FROM visitor_events
            WHERE event_id = ?
        """, (event_id,))
        reclass_row = cursor.fetchone()
        if reclass_row:
            event_data["reclassification_count"] = reclass_row[0]
            event_data["reclassified_by"] = reclass_row[1]
            event_data["reclassification_reason"] = reclass_row[2]
            event_data["reclassified_ts"] = reclass_row[3]
    
    return event_data

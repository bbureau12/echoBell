"""
Evidence Logging Integration Example

This module demonstrates how to integrate evidence_service into the existing
classify_and_log workflow. This is NOT production code - it's a reference
implementation showing where to add evidence logging calls.

Integration Points:
1. After vision.py generates evidence → log to evidence_log table
2. After classify_and_log enriches evidence → log enriched evidence
3. Associate evidence with event_id, camera_id, and track info

Usage in classify_and_log.py:
    from packages.data.evidence_service import create_evidence_service
    
    # Create service (once, at module level or in __init__)
    evidence_service = create_evidence_service(retention_days=30)
    
    # Inside classify_and_log():
    # ... after vision detection ...
    evidence_service.log_evidence(
        conn=conn,
        event_id=event_id,
        camera_id=camera_id,
        evidence_list=vision.evidence,
    )
    
    # ... after enrichment (plates, scene, linkage) ...
    evidence_service.log_evidence(
        conn=conn,
        event_id=event_id,
        camera_id=camera_id,
        evidence_list=enriched_evidence,
        track_type='vehicle',  # or 'person'
        track_key=plate_hmac,  # or visitor_id
    )

Query Examples:
    # Get all evidence for an event
    evidence = evidence_service.get_evidence_for_event(conn, event_id="evt_123")
    
    # Get evidence timeline for a vehicle
    evidence = evidence_service.get_evidence_for_track(
        conn, 
        track_type='vehicle', 
        track_key=plate_hmac,
        since_ts=int(time()) - 3600  # Last hour
    )
    
    # Find all bicycle detections
    bicycles = evidence_service.get_evidence_by_source_feature(
        conn,
        source='vision',
        feature='vehicle_type',
        value='bicycle',
        since_ts=int(time()) - 86400  # Last 24 hours
    )
    
    # Get summary stats for a person
    summary = evidence_service.get_evidence_summary_by_track(
        conn,
        track_type='person',
        track_key=visitor_id
    )
    print(f"Total evidence: {summary['total_evidence_count']}")
    print(f"Most common: {summary['most_common_values']}")
"""

import sqlite3
from time import time
from typing import List

from packages.common.types import Evidence, SceneObject
from packages.data.evidence_service import create_evidence_service


def example_log_vision_evidence(
    conn: sqlite3.Connection,
    event_id: str,
    camera_id: int,
    evidence_list: List[Evidence],
):
    """
    Example: Log evidence from vision detection.
    
    Called after snapshot_and_detect() returns VisionResult.
    """
    service = create_evidence_service(retention_days=30)
    
    count = service.log_evidence(
        conn=conn,
        event_id=event_id,
        camera_id=camera_id,
        evidence_list=evidence_list,
    )
    
    print(f"Logged {count} evidence records for event {event_id}")


def example_log_vehicle_evidence(
    conn: sqlite3.Connection,
    event_id: str,
    camera_id: int,
    vehicle_obj: SceneObject,
    plate_hmac: str,
):
    """
    Example: Log evidence specifically for a vehicle with plate.
    
    Called after plate detection and trusted plate check.
    Includes track_type and track_key for queryability.
    """
    service = create_evidence_service(retention_days=30)
    
    # Filter evidence related to this vehicle
    vehicle_evidence = [
        ev for ev in vehicle_obj.evidence
        if ev.object_id == vehicle_obj.object_id
    ]
    
    count = service.log_evidence(
        conn=conn,
        event_id=event_id,
        camera_id=camera_id,
        evidence_list=vehicle_evidence,
        track_type='vehicle',
        track_key=plate_hmac,
        metadata={'color': vehicle_obj.color, 'raw_class': vehicle_obj.props.get('raw_class')},
    )
    
    print(f"Logged {count} vehicle evidence records (plate: {plate_hmac[:8]}...)")


def example_log_person_evidence(
    conn: sqlite3.Connection,
    event_id: str,
    camera_id: int,
    person_obj: SceneObject,
    visitor_id: str,
):
    """
    Example: Log evidence for a recognized person.
    
    Called after face recognition matches a visitor.
    """
    service = create_evidence_service(retention_days=30)
    
    person_evidence = [
        ev for ev in person_obj.evidence
        if ev.object_id == person_obj.object_id
    ]
    
    count = service.log_evidence(
        conn=conn,
        event_id=event_id,
        camera_id=camera_id,
        evidence_list=person_evidence,
        track_type='person',
        track_key=visitor_id,
    )
    
    print(f"Logged {count} person evidence records (visitor: {visitor_id})")


def example_query_vehicle_history(
    conn: sqlite3.Connection,
    plate_hmac: str,
):
    """
    Example: Query all historical evidence for a vehicle.
    
    Useful for debugging "why did this vehicle get classified as X?"
    """
    service = create_evidence_service(retention_days=30)
    
    # Get summary
    summary = service.get_evidence_summary_by_track(
        conn,
        track_type='vehicle',
        track_key=plate_hmac
    )
    
    print(f"Vehicle {plate_hmac[:8]}... history:")
    print(f"  Total evidence: {summary['total_evidence_count']}")
    print(f"  Sources: {summary['unique_sources']}")
    print(f"  Features: {summary['unique_features']}")
    print(f"  Avg confidence: {summary['avg_confidence']:.2f}")
    print(f"  First seen: {summary['first_seen_ts']}")
    print(f"  Most common values:")
    for item in summary['most_common_values']:
        print(f"    - {item['value']}: {item['count']} times")
    
    # Get recent evidence details
    recent = service.get_evidence_for_track(
        conn,
        track_type='vehicle',
        track_key=plate_hmac,
        limit=10
    )
    
    print(f"\n  Recent evidence (last 10):")
    for ev in recent:
        print(f"    - {ev['source']}.{ev['feature']} = {ev['value']} ({ev['conf']:.2f})")


def example_query_bicycle_detections(
    conn: sqlite3.Connection,
    hours: int = 24,
):
    """
    Example: Find all bicycle detections in the last N hours.
    
    Demonstrates source/feature querying.
    """
    service = create_evidence_service(retention_days=30)
    
    since_ts = int(time()) - (hours * 3600)
    
    bicycles = service.get_evidence_by_source_feature(
        conn,
        source='vision',
        feature='vehicle_type',
        value='bicycle',
        since_ts=since_ts,
        limit=100
    )
    
    print(f"Found {len(bicycles)} bicycle detections in last {hours} hours:")
    for ev in bicycles[:5]:  # Show first 5
        print(f"  - Event {ev['event_id']}, Camera {ev['camera_id']}, "
              f"Conf {ev['conf']:.2f}, Track {ev['track_key']}")


# Example integration into classify_and_log.py
# (Pseudo-code showing where to add calls)

def example_classify_and_log_integration():
    """
    Pseudo-code showing where to integrate evidence logging.
    
    This is NOT executable - it's a reference for integration.
    """
    
    # At module level:
    # from packages.data.evidence_service import create_evidence_service
    # evidence_service = create_evidence_service(retention_days=30)
    
    # Inside classify_and_log():
    
    # 1. After vision detection
    # vision = snapshot_and_detect(...)
    # evidence_service.log_evidence(conn, event_id, camera_id, vision.evidence)
    
    # 2. After plate linkage (for each vehicle with plate)
    # for vehicle in vehicles_with_plates:
    #     evidence_service.log_evidence(
    #         conn, event_id, camera_id,
    #         vehicle.evidence,
    #         track_type='vehicle',
    #         track_key=plate_hmac_mapping[vehicle.object_id]
    #     )
    
    # 3. After scene tracking (for scene evidence)
    # scene_evidence = [...scene tracking evidence...]
    # evidence_service.log_evidence(conn, event_id, camera_id, scene_evidence)
    
    # 4. After person-vehicle linkage
    # for person in people_with_visitor_id:
    #     evidence_service.log_evidence(
    #         conn, event_id, camera_id,
    #         person.evidence,
    #         track_type='person',
    #         track_key=person.visitor_id
    #     )
    
    pass  # Not executable


if __name__ == '__main__':
    print(__doc__)
    print("\nThis is a reference implementation. See docstrings for usage.")

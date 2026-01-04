"""
Example: Cross-camera person tracking usage

Demonstrates how to use the new cross-camera tracking functionality
to detect when a person is active anywhere in the scene, track camera
handoffs, and get global visitor presence information.
"""

import sqlite3
import time
from packages.scene.scene_tracker import SceneTracker


def example_cross_camera_tracking():
    """Example showing cross-camera person tracking in action."""
    
    # Setup
    conn = sqlite3.connect(":memory:")
    tracker = SceneTracker(grace_period_s=6)
    tracker.ensure_schema(conn)
    
    now = int(time.time())
    
    print("=" * 80)
    print("Cross-Camera Person Tracking Example")
    print("=" * 80)
    
    # -------------------------------------------------------------------------
    # Scenario 1: Check if specific person is active anywhere
    # -------------------------------------------------------------------------
    print("\n[Scenario 1] Is visitor_001 currently active?")
    
    is_active = tracker.is_person_active_anywhere(
        conn,
        visitor_id="visitor_001",
        now_ts=now,
    )
    
    print(f"  Result: {is_active}")
    print("  Note: No tracks yet, so person is not active")
    
    # -------------------------------------------------------------------------
    # Scenario 2: Person appears on camera 1
    # -------------------------------------------------------------------------
    print("\n[Scenario 2] Person appears on camera 1")
    
    from packages.scene.scene_tracker import Observation
    
    obs = [
        Observation(
            track_type="person",
            box=(100, 100, 200, 300),
            visitor_id="visitor_001",
        )
    ]
    
    tracker.update(conn, camera_id=1, now_ts=now, observations=obs)
    
    is_active = tracker.is_person_active_anywhere(
        conn,
        visitor_id="visitor_001",
        now_ts=now,
    )
    
    print(f"  Is active anywhere: {is_active}")
    
    cameras = tracker.get_person_cameras(
        conn,
        visitor_id="visitor_001",
        now_ts=now,
    )
    
    print(f"  Cameras seeing person: {cameras}")
    
    # -------------------------------------------------------------------------
    # Scenario 3: Person moves to camera 2 (camera handoff)
    # -------------------------------------------------------------------------
    print("\n[Scenario 3] Person moves from camera 1 to camera 2")
    
    handoff_time = now + 3
    
    # Disappears from camera 1
    tracker.update(conn, camera_id=1, now_ts=handoff_time, observations=[])
    
    # Appears on camera 2
    obs_cam2 = [
        Observation(
            track_type="person",
            box=(150, 150, 250, 350),
            visitor_id="visitor_001",
        )
    ]
    
    tracker.update(conn, camera_id=2, now_ts=handoff_time, observations=obs_cam2)
    
    is_active = tracker.is_person_active_anywhere(
        conn,
        visitor_id="visitor_001",
        now_ts=handoff_time,
    )
    
    cameras = tracker.get_person_cameras(
        conn,
        visitor_id="visitor_001",
        now_ts=handoff_time,
    )
    
    print(f"  Is active anywhere: {is_active}")
    print(f"  Cameras seeing person: {cameras}")
    print("  Note: Person successfully tracked across camera handoff!")
    
    # -------------------------------------------------------------------------
    # Scenario 4: Multiple visitors across multiple cameras
    # -------------------------------------------------------------------------
    print("\n[Scenario 4] Multiple visitors on different cameras")
    
    multi_time = now + 5
    
    # visitor_002 on camera 3
    obs_visitor2 = [
        Observation(
            track_type="person",
            box=(200, 200, 300, 400),
            visitor_id="visitor_002",
        )
    ]
    
    tracker.update(conn, camera_id=3, now_ts=multi_time, observations=obs_visitor2)
    
    # Get all active visitors
    all_visitors = tracker.get_active_visitors_all_cameras(
        conn,
        now_ts=multi_time,
    )
    
    print(f"  All active visitors:")
    for visitor_id, cam_list in all_visitors.items():
        print(f"    {visitor_id}: cameras {cam_list}")
    
    # -------------------------------------------------------------------------
    # Scenario 5: Check for specific visitor's presence
    # -------------------------------------------------------------------------
    print("\n[Scenario 5] Policy decision based on visitor presence")
    
    # Example: Suppress visitor notifications if trusted family member is home
    trusted_family = ["visitor_001", "visitor_002", "visitor_003"]
    
    any_family_home = any(
        tracker.is_person_active_anywhere(conn, visitor_id=vid, now_ts=multi_time)
        for vid in trusted_family
    )
    
    print(f"  Is any family member home: {any_family_home}")
    print(f"  Policy: {'Suppress notification' if any_family_home else 'Send notification'}")
    
    # -------------------------------------------------------------------------
    # Scenario 6: Person exits all cameras
    # -------------------------------------------------------------------------
    print("\n[Scenario 6] All visitors exit the scene")
    
    exit_time = multi_time + 10  # Beyond grace period
    
    # Update all cameras with no observations
    for cam_id in [1, 2, 3]:
        tracker.update(conn, camera_id=cam_id, now_ts=exit_time, observations=[])
    
    all_visitors_after_exit = tracker.get_active_visitors_all_cameras(
        conn,
        now_ts=exit_time,
    )
    
    print(f"  Active visitors after exit: {all_visitors_after_exit}")
    print("  Note: All visitors have exited (beyond grace period)")
    
    print("\n" + "=" * 80)
    print("Cross-camera tracking enables:")
    print("  ✓ Global person presence detection")
    print("  ✓ Camera handoff tracking")
    print("  ✓ Multi-camera coverage analysis")
    print("  ✓ Scene-wide policy decisions")
    print("=" * 80)


if __name__ == "__main__":
    example_cross_camera_tracking()

#!/usr/bin/env python3
"""
Test harness for snapshot service integration with visitor tracking.
"""
import os
import sys
import sqlite3
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from packages.data.snapshot_service import SnapshotService
from packages.perception.vision import snapshot_and_detect


def test_snapshot_integration():
    """Test that snapshots are saved during visitor detection."""
    print("=" * 80)
    print("Testing Snapshot Service Integration")
    print("=" * 80)
    
    # Setup
    db_path = os.path.join(ROOT, "data", "doorbell.db")
    test_image = os.path.join(ROOT, "data", "test", "police", "Dep.-A-Fox-3-scaled-e1670953812693.jpg")
    
    if not os.path.exists(test_image):
        print(f"✗ Test image not found: {test_image}")
        return
    
    # Create snapshot service
    snapshot_service = SnapshotService(
        output_dir=os.path.join(ROOT, "data", "img_log"),
        max_size=1920
    )
    
    print(f"\nSnapshot service:")
    print(f"  Output dir: {snapshot_service.output_dir}")
    print(f"  Max size: {snapshot_service.max_size}")
    
    # Count existing snapshots
    with sqlite3.connect(db_path) as conn:
        before_count = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
        print(f"\nSnapshots before: {before_count}")
    
    # Run vision detection with snapshot service
    print("\n" + "-" * 80)
    print("Running vision detection...")
    print("-" * 80)
    
    vr = snapshot_and_detect(
        db=db_path,
        rtsp=test_image,
        camera_id="1",
        debug=False,
        snapshot_service=snapshot_service,
        event_id="test_event_001",
    )
    
    print(f"\n✓ Vision detection complete")
    print(f"  Objects detected: {len(vr.objects)}")
    print(f"  Evidence items: {len(vr.evidence)}")
    
    # Check for person and visitor_id
    person_found = False
    visitor_id = None
    for obj in vr.objects:
        if obj.label == "person":
            person_found = True
            visitor_id = obj.props.get("visitor_id")
            visitor_kind = obj.props.get("visitor_kind")
            print(f"\n  Person detected:")
            print(f"    visitor_id: {visitor_id}")
            print(f"    visitor_kind: {visitor_kind}")
            break
    
    # Count snapshots after
    with sqlite3.connect(db_path) as conn:
        after_count = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
        print(f"\nSnapshots after: {after_count}")
        print(f"New snapshots: {after_count - before_count}")
        
        # Show latest snapshot
        if after_count > before_count:
            row = conn.execute(
                """
                SELECT id, filename, timestamp, camera_id, visitor_event_id
                FROM snapshots
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
            
            if row:
                snapshot_id, filename, ts, cam_id, event_id = row
                print(f"\n✓ Latest snapshot:")
                print(f"    ID: {snapshot_id}")
                print(f"    Filename: {filename}")
                print(f"    Timestamp: {ts}")
                print(f"    Camera ID: {cam_id}")
                print(f"    Event ID: {event_id}")
                
                # Check if file exists
                filepath = os.path.join(snapshot_service.output_dir, filename)
                if os.path.exists(filepath):
                    print(f"    ✓ File exists on disk")
                    file_size = os.path.getsize(filepath)
                    print(f"    File size: {file_size:,} bytes")
                else:
                    print(f"    ✗ File NOT found on disk: {filepath}")
    
    print("\n" + "=" * 80)
    print("✓ Test complete!")
    print("=" * 80)


if __name__ == "__main__":
    test_snapshot_integration()

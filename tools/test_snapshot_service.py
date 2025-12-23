#!/usr/bin/env python3
"""
Test harness for snapshot service.
"""
import os
import sys
import sqlite3
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import cv2
import numpy as np
from packages.data.snapshot import SnapshotService, SnapshotMetadata


def test_snapshot_service():
    """Test the snapshot service."""
    print("=" * 80)
    print("Testing Snapshot Service")
    print("=" * 80)
    
    # Create a test image (blue gradient)
    test_image = np.zeros((2000, 3000, 3), dtype=np.uint8)
    test_image[:, :] = [255, 100, 50]  # BGR: orange-ish color
    
    # Add some text to make it interesting
    cv2.putText(
        test_image,
        "Test Snapshot",
        (100, 100),
        cv2.FONT_HERSHEY_SIMPLEX,
        3,
        (255, 255, 255),
        5
    )
    
    print(f"\n[TEST IMAGE] Created test image: {test_image.shape[1]}x{test_image.shape[0]}")
    
    # Initialize service
    service = SnapshotService(img_log_dir="data/img_log", max_size=1920)
    print(f"[SERVICE] Initialized with max_size=1920, img_log_dir={service.img_log_dir}")
    
    # Connect to database
    db_path = os.path.join(ROOT, "data", "doorbell.db")
    
    with sqlite3.connect(db_path) as conn:
        # Create metadata
        metadata = SnapshotMetadata(
            camera_id=1,
            visitor_event_id="test-event-123",
            timestamp=int(time.time())
        )
        
        print(f"\n[METADATA] camera_id={metadata.camera_id}, visitor_event_id={metadata.visitor_event_id}")
        
        # Save snapshot
        print("\n[SAVING] Saving snapshot...")
        filename, snapshot_id = service.save_snapshot(
            conn,
            test_image,
            metadata,
            original_filename="test.jpg"
        )
        
        print(f"✓ Snapshot saved!")
        print(f"  ID: {snapshot_id}")
        print(f"  Filename: {filename}")
        print(f"  Path: {service.get_snapshot_path(filename)}")
        
        # Verify file exists and check size
        filepath = service.get_snapshot_path(filename)
        if filepath.exists():
            saved_image = cv2.imread(str(filepath))
            print(f"  Saved size: {saved_image.shape[1]}x{saved_image.shape[0]}")
            print(f"  File size: {filepath.stat().st_size:,} bytes")
            
            # Verify resizing worked
            max_dim = max(saved_image.shape[:2])
            if max_dim <= 1920:
                print(f"  ✓ Image properly resized (max dimension: {max_dim})")
            else:
                print(f"  ✗ Image NOT properly resized (max dimension: {max_dim})")
        else:
            print(f"  ✗ File not found!")
        
        # Retrieve from database
        print("\n[RETRIEVING] Getting snapshot from database...")
        snapshot_data = service.get_snapshot(conn, snapshot_id)
        
        if snapshot_data:
            print(f"✓ Snapshot retrieved!")
            print(f"  ID: {snapshot_data['id']}")
            print(f"  Filename: {snapshot_data['filename']}")
            print(f"  Camera ID: {snapshot_data['camera_id']}")
            print(f"  Visitor Event ID: {snapshot_data['visitor_event_id']}")
            print(f"  Timestamp: {snapshot_data['timestamp']}")
        else:
            print(f"  ✗ Snapshot not found in database!")
        
        # List snapshots
        print("\n[LISTING] Recent snapshots for camera 1...")
        snapshots = service.list_snapshots(conn, camera_id=1, limit=5)
        print(f"✓ Found {len(snapshots)} snapshot(s)")
        for i, snap in enumerate(snapshots, 1):
            print(f"  {i}. {snap['filename']} (ID: {snap['id']}, Event: {snap['visitor_event_id']})")
        
        conn.commit()
    
    print("\n" + "=" * 80)
    print("✓ Snapshot service test completed!")
    print("=" * 80)


if __name__ == "__main__":
    test_snapshot_service()

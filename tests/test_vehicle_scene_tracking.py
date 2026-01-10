"""
Integration test for vehicle scene tracking.

Tests the SceneTracker's ability to:
- Detect and track vehicles entering/exiting the scene
- Maintain active/inactive status correctly
- Handle multiple vehicles simultaneously
- Track vehicles across frames with same/similar positions

Test Flow:
1. No cars → No active tracks
2. Car A appears → Car A active
3. Car A + B appear → Both cars active
4. Car B only → Car A inactive, Car B active
5. No cars → All cars inactive
"""

import pytest
import sqlite3
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from packages.perception.vision import snapshot_and_detect
from packages.scene.scene_tracker import SceneTracker, build_observations_from_vision
from tests.helpers.db_setup import create_test_schema, create_test_cameras


@pytest.fixture
def test_db(tmp_path):
    """Create a temporary database with all required schemas."""
    db_path = tmp_path / "test_scene_tracking.db"
    conn = sqlite3.connect(str(db_path))
    
    # Create all required tables (no facial recognition needed)
    create_test_schema(conn, include_facial_recognition=False)
    
    # Insert test camera
    create_test_cameras(conn, [
        {'id': 1, 'name': 'Test Camera - Scene Tracking', 'capability_level_id': 1, 'stream_url': 'rtsp://test'}
    ])
    
    yield str(db_path), conn
    
    conn.close()


def test_vehicle_scene_tracking_lifecycle(test_db):
    """
    Test complete vehicle tracking lifecycle:
    1. Empty scene → No active vehicles
    2. Car A appears → Car A tracked and active
    3. Car A + B appear → Both cars tracked and active
    4. Car B only → Car A inactive, Car B still active
    5. Empty scene → All vehicles inactive
    """
    db_path, conn = test_db
    
    # Get test images
    fixtures_dir = Path(__file__).parent / "fixtures" / "vehicle_scene_tracking"
    no_cars = fixtures_dir / "no_cars.jpg"
    car_a = fixtures_dir / "car_a.jpg"
    car_a_and_b = fixtures_dir / "car_a_and_b.jpg"
    car_b = fixtures_dir / "car_b.jpg"
    
    assert no_cars.exists(), f"Missing test image: {no_cars}"
    assert car_a.exists(), f"Missing test image: {car_a}"
    assert car_a_and_b.exists(), f"Missing test image: {car_a_and_b}"
    assert car_b.exists(), f"Missing test image: {car_b}"
    
    # Initialize scene tracker
    scene_tracker = SceneTracker(iou_match_threshold=0.3, grace_period_s=6)
    
    camera_id = 1
    now_ts = int(time.time())
    
    # STEP 1: Process empty scene (no cars)
    print("\n[TEST] Step 1: Processing no_cars.jpg (empty scene)...")
    
    vision1 = snapshot_and_detect(
        db=db_path,
        rtsp=str(no_cars),
        camera_id=str(camera_id),
        debug=True,
        enable_ocr=True,
    )
    
    # Update scene tracker
    scene_tracker.ensure_schema(conn)
    observations1 = build_observations_from_vision(vision1)
    scene_tracker.update(
        conn,
        camera_id=camera_id,
        now_ts=now_ts,
        observations=observations1,
    )
    
    # Verify: No vehicles detected
    vehicles1 = [obj for obj in vision1.objects if obj.label and "vehicle" in obj.label.lower()]
    print(f"[TEST] Step 1: Detected objects: {[obj.label for obj in vision1.objects]}")
    print(f"[TEST] Step 1: Vehicles: {len(vehicles1)}")
    
    assert len(vehicles1) == 0, f"Should detect NO vehicles in empty scene. Got: {len(vehicles1)}"
    
    # Check active vehicle tracks
    active_tracks1 = conn.execute("""
        SELECT track_key, track_type, active, first_seen_ts, last_seen_ts
        FROM scene_tracks
        WHERE camera_id = ? AND track_type = 'vehicle' AND active = 1
        ORDER BY first_seen_ts ASC
    """, (camera_id,)).fetchall()
    
    print(f"[TEST] Step 1: Active vehicle tracks: {len(active_tracks1)}")
    assert len(active_tracks1) == 0, "Should have NO active vehicle tracks"
    
    print("[TEST] ✓ Step 1 passed: Empty scene, no vehicles\n")
    
    # STEP 2: Car A appears
    print("[TEST] Step 2: Processing car_a.jpg (first car appears)...")
    now_ts += 2
    
    vision2 = snapshot_and_detect(
        db=db_path,
        rtsp=str(car_a),
        camera_id=str(camera_id),
        debug=True,
        enable_ocr=True,
    )
    
    # Update scene tracker
    observations2 = build_observations_from_vision(vision2)
    scene_tracker.update(
        conn,
        camera_id=camera_id,
        now_ts=now_ts,
        observations=observations2,
    )
    
    # Verify: One vehicle detected
    vehicles2 = [obj for obj in vision2.objects if obj.label and "vehicle" in obj.label.lower()]
    print(f"[TEST] Step 2: Detected objects: {[obj.label for obj in vision2.objects]}")
    print(f"[TEST] Step 2: Vehicles: {len(vehicles2)}")
    
    assert len(vehicles2) == 1, f"Should detect 1 vehicle (Car A). Got: {len(vehicles2)}"
    
    # Check active vehicle tracks
    active_tracks2 = conn.execute("""
        SELECT track_key, track_type, active, first_seen_ts, last_seen_ts
        FROM scene_tracks
        WHERE camera_id = ? AND track_type = 'vehicle' AND active = 1
        ORDER BY first_seen_ts ASC
    """, (camera_id,)).fetchall()
    
    print(f"[TEST] Step 2: Active vehicle tracks: {len(active_tracks2)}")
    for track in active_tracks2:
        print(f"  Track: {track[0]} (type: {track[1]}, active: {track[2]}, first: {track[3]}, last: {track[4]})")
    
    assert len(active_tracks2) == 1, f"Should have 1 active vehicle track (Car A). Got: {len(active_tracks2)}"
    
    car_a_track_key = active_tracks2[0][0]
    car_a_first_seen = active_tracks2[0][3]
    
    print(f"[TEST] ✓ Step 2 passed: Car A tracked")
    print(f"  Track key: {car_a_track_key}")
    print(f"  First seen: {car_a_first_seen}\n")
    
    # STEP 3: Both Car A and Car B appear
    print("[TEST] Step 3: Processing car_a_and_b.jpg (both cars present)...")
    now_ts += 2
    
    vision3 = snapshot_and_detect(
        db=db_path,
        rtsp=str(car_a_and_b),
        camera_id=str(camera_id),
        debug=True,
        enable_ocr=True,
    )
    
    # Update scene tracker
    observations3 = build_observations_from_vision(vision3)
    scene_tracker.update(
        conn,
        camera_id=camera_id,
        now_ts=now_ts,
        observations=observations3,
    )
    
    # Verify: Two vehicles detected
    vehicles3 = [obj for obj in vision3.objects if obj.label and "vehicle" in obj.label.lower()]
    print(f"[TEST] Step 3: Detected objects: {[obj.label for obj in vision3.objects]}")
    print(f"[TEST] Step 3: Vehicles: {len(vehicles3)}")
    
    assert len(vehicles3) == 2, f"Should detect 2 vehicles (Car A + Car B). Got: {len(vehicles3)}"
    
    # Check active vehicle tracks
    active_tracks3 = conn.execute("""
        SELECT track_key, track_type, active, first_seen_ts, last_seen_ts
        FROM scene_tracks
        WHERE camera_id = ? AND track_type = 'vehicle' AND active = 1
        ORDER BY first_seen_ts ASC
    """, (camera_id,)).fetchall()
    
    print(f"[TEST] Step 3: Active vehicle tracks: {len(active_tracks3)}")
    for track in active_tracks3:
        print(f"  Track: {track[0]} (type: {track[1]}, active: {track[2]}, first: {track[3]}, last: {track[4]})")
    
    assert len(active_tracks3) == 2, f"Should have 2 active vehicle tracks (Car A + Car B). Got: {len(active_tracks3)}"
    
    # Verify Car A track is still the same (matched via IoU)
    car_a_still_tracked = any(track[0] == car_a_track_key for track in active_tracks3)
    assert car_a_still_tracked, f"Car A should still be tracked with same key: {car_a_track_key}"
    
    # Find Car B track (the new one)
    car_b_track = None
    for track in active_tracks3:
        if track[0] != car_a_track_key:
            car_b_track = track
            break
    
    assert car_b_track is not None, "Should have identified Car B track"
    car_b_track_key = car_b_track[0]
    car_b_first_seen = car_b_track[3]
    
    print(f"[TEST] ✓ Step 3 passed: Both cars tracked")
    print(f"  Car A track: {car_a_track_key} (same as before)")
    print(f"  Car B track: {car_b_track_key} (new)")
    print(f"  Car B first seen: {car_b_first_seen}\n")
    
    # STEP 4: Only Car B remains (Car A leaves)
    # Wait longer than grace period (6 seconds) to ensure Car A is marked inactive
    print("[TEST] Step 4: Processing car_b.jpg (Car A leaves, Car B remains)...")
    now_ts += 8  # Wait 8 seconds (> 6 second grace period)
    
    vision4 = snapshot_and_detect(
        db=db_path,
        rtsp=str(car_b),
        camera_id=str(camera_id),
        debug=True,
        enable_ocr=True,
    )
    
    # Update scene tracker
    observations4 = build_observations_from_vision(vision4)
    scene_tracker.update(
        conn,
        camera_id=camera_id,
        now_ts=now_ts,
        observations=observations4,
    )
    
    # Verify: One vehicle detected
    vehicles4 = [obj for obj in vision4.objects if obj.label and "vehicle" in obj.label.lower()]
    print(f"[TEST] Step 4: Detected objects: {[obj.label for obj in vision4.objects]}")
    print(f"[TEST] Step 4: Vehicles: {len(vehicles4)}")
    
    assert len(vehicles4) == 1, f"Should detect 1 vehicle (Car B only). Got: {len(vehicles4)}"
    
    # Check active vehicle tracks
    active_tracks4 = conn.execute("""
        SELECT track_key, track_type, active, first_seen_ts, last_seen_ts
        FROM scene_tracks
        WHERE camera_id = ? AND track_type = 'vehicle' AND active = 1
        ORDER BY first_seen_ts ASC
    """, (camera_id,)).fetchall()
    
    print(f"[TEST] Step 4: Active vehicle tracks: {len(active_tracks4)}")
    for track in active_tracks4:
        print(f"  Track: {track[0]} (type: {track[1]}, active: {track[2]}, first: {track[3]}, last: {track[4]})")
    
    # Car A should be inactive (within grace period, so might still exist but marked inactive)
    # Car B should still be active
    assert len(active_tracks4) == 1, f"Should have 1 active vehicle track (Car B only). Got: {len(active_tracks4)}"
    assert active_tracks4[0][0] == car_b_track_key, f"Active track should be Car B: {car_b_track_key}"
    
    # Check Car A status (should be inactive)
    car_a_status = conn.execute("""
        SELECT track_key, active, last_seen_ts
        FROM scene_tracks
        WHERE camera_id = ? AND track_key = ?
    """, (camera_id, car_a_track_key)).fetchone()
    
    print(f"[TEST] Step 4: Car A status: active={car_a_status[1]}, last_seen={car_a_status[2]}")
    
    # Car A should exist but be inactive (or removed after grace period)
    if car_a_status:
        assert car_a_status[1] == 0, f"Car A should be INACTIVE. Got active={car_a_status[1]}"
        print(f"[TEST] ✓ Car A correctly marked INACTIVE")
    else:
        print(f"[TEST] ✓ Car A removed from tracks (grace period expired)")
    
    print(f"[TEST] ✓ Step 4 passed: Car A inactive, Car B active")
    print(f"  Car B track: {car_b_track_key} (still active)\n")
    
    # STEP 5: Empty scene again (all cars leave)
    # Wait longer than grace period to ensure Car B is marked inactive
    print("[TEST] Step 5: Processing no_cars.jpg again (all cars leave)...")
    now_ts += 8  # Wait 8 seconds (> 6 second grace period)
    
    vision5 = snapshot_and_detect(
        db=db_path,
        rtsp=str(no_cars),
        camera_id=str(camera_id),
        debug=True,
        enable_ocr=True,
    )
    
    # Update scene tracker
    observations5 = build_observations_from_vision(vision5)
    scene_tracker.update(
        conn,
        camera_id=camera_id,
        now_ts=now_ts,
        observations=observations5,
    )
    
    # Verify: No vehicles detected
    vehicles5 = [obj for obj in vision5.objects if obj.label and "vehicle" in obj.label.lower()]
    print(f"[TEST] Step 5: Detected objects: {[obj.label for obj in vision5.objects]}")
    print(f"[TEST] Step 5: Vehicles: {len(vehicles5)}")
    
    assert len(vehicles5) == 0, f"Should detect NO vehicles. Got: {len(vehicles5)}"
    
    # Check active vehicle tracks
    active_tracks5 = conn.execute("""
        SELECT track_key, track_type, active, first_seen_ts, last_seen_ts
        FROM scene_tracks
        WHERE camera_id = ? AND track_type = 'vehicle' AND active = 1
        ORDER BY first_seen_ts ASC
    """, (camera_id,)).fetchall()
    
    print(f"[TEST] Step 5: Active vehicle tracks: {len(active_tracks5)}")
    
    assert len(active_tracks5) == 0, f"Should have NO active vehicle tracks. Got: {len(active_tracks5)}"
    
    # Check all tracks (including inactive)
    all_tracks = conn.execute("""
        SELECT track_key, active, first_seen_ts, last_seen_ts
        FROM scene_tracks
        WHERE camera_id = ? AND track_type = 'vehicle'
        ORDER BY first_seen_ts ASC
    """, (camera_id,)).fetchall()
    
    print(f"[TEST] Step 5: All vehicle tracks (active + inactive): {len(all_tracks)}")
    for track in all_tracks:
        print(f"  Track: {track[0]} (active: {track[1]}, first: {track[2]}, last: {track[3]})")
    
    print(f"[TEST] ✓ Step 5 passed: All vehicles inactive\n")
    
    print("[TEST] ✓✓✓ ALL TESTS PASSED ✓✓✓")
    print("[TEST] Summary:")
    print("  ✓ Empty scene correctly detected (no vehicles)")
    print("  ✓ Car A tracked when it appears")
    print("  ✓ Car B tracked when it appears (2 active tracks)")
    print("  ✓ Car A deactivated when it leaves")
    print("  ✓ Car B remains active while present")
    print("  ✓ All vehicles deactivated when scene is empty")
    print(f"  ✓ Vehicle tracking lifecycle complete: {len(all_tracks)} total tracks created")

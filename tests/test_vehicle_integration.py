"""
Consolidated Integration Tests for Vehicle Tracking and Person-Vehicle Linkage

This file consolidates three previously separate test files:
- test_vehicle_linkage_integration.py (basic person-vehicle linkage)
- test_vehicle_linkage_persistence.py (ReID persistence across frames)
- test_vehicle_scene_tracking.py (vehicle tracking lifecycle)

Tests the complete vehicle tracking system including:
1. Vehicle scene tracking (entry/exit, multi-vehicle)
2. Person-to-vehicle linkage (proximity + timing)
3. ReID persistence across frames (same person, different poses)
4. Cross-camera ReID with facial recognition
5. Temporal window filtering (old arrivals not linked)
6. Proximity filtering (distant people not linked)
"""

import pytest
import sqlite3
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from packages.perception.vision import snapshot_and_detect
from packages.data.camera_service import CameraService
from packages.common.types import Camera, CameraCapabilities
from packages.classify.classify_and_log import classify_and_log
from packages.scene.scene_tracker import SceneTracker, build_observations_from_vision
from packages.common.config_models import RetentionSettings
from tests.helpers.db_setup import create_test_schema, create_test_cameras


@pytest.fixture
def test_db_single_camera(tmp_path):
    """Create a temporary database with single camera (no facial recognition)."""
    db_path = tmp_path / "test_vehicle_single.db"
    conn = sqlite3.connect(str(db_path))
    
    create_test_schema(conn, include_facial_recognition=False)
    create_test_cameras(conn, [
        {'id': 1, 'name': 'Test Camera', 'capability_level_id': 1, 'stream_url': 'rtsp://test'}
    ])
    
    yield str(db_path), conn
    conn.close()


@pytest.fixture
def test_db_multi_camera(tmp_path):
    """Create a temporary database with multiple cameras (with facial recognition)."""
    db_path = tmp_path / "test_vehicle_multi.db"
    conn = sqlite3.connect(str(db_path))
    
    create_test_schema(conn, include_facial_recognition=True)
    create_test_cameras(conn, [
        {'id': 1, 'name': 'Camera 1 - Vehicle ID Only', 'capability_level_id': 1, 'stream_url': 'rtsp://test1'},
        {'id': 2, 'name': 'Camera 2 - Facial Recognition', 'capability_level_id': 2, 'stream_url': 'rtsp://test2'}
    ])
    
    yield str(db_path), conn
    conn.close()


class TestVehicleSceneTracking:
    """Test vehicle tracking lifecycle (entry, exit, multi-vehicle)"""
    
    def test_vehicle_tracking_lifecycle(self, test_db_single_camera):
        """
        Test complete vehicle tracking lifecycle:
        1. Empty scene → No active vehicles
        2. Car A appears → Car A tracked and active
        3. Car A + B appear → Both cars tracked and active
        4. Car B only → Car A inactive, Car B still active
        5. Empty scene → All vehicles inactive
        """
        db_path, conn = test_db_single_camera
        
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
        
        scene_tracker = SceneTracker(iou_match_threshold=0.3, grace_period_s=6)
        camera_id = 1
        now_ts = int(time.time())
        
        # STEP 1: Empty scene
        print("\n[TEST] Step 1: Empty scene...")
        vision1 = snapshot_and_detect(db=db_path, rtsp=str(no_cars), camera_id=str(camera_id), debug=True, enable_ocr=True)
        scene_tracker.ensure_schema(conn)
        observations1 = build_observations_from_vision(vision1)
        scene_tracker.update(conn, camera_id=camera_id, now_ts=now_ts, observations=observations1)
        
        vehicles1 = [obj for obj in vision1.objects if obj.label and "vehicle" in obj.label.lower()]
        assert len(vehicles1) == 0, "Should detect NO vehicles in empty scene"
        
        active_tracks1 = conn.execute(
            "SELECT track_key FROM scene_tracks WHERE camera_id = ? AND track_type = 'vehicle' AND active = 1",
            (camera_id,)
        ).fetchall()
        assert len(active_tracks1) == 0, "Should have NO active vehicle tracks"
        print("[TEST] ✓ Step 1 passed: Empty scene, no vehicles")
        
        # STEP 2: Car A appears
        print("[TEST] Step 2: Car A appears...")
        now_ts += 2
        vision2 = snapshot_and_detect(db=db_path, rtsp=str(car_a), camera_id=str(camera_id), debug=True, enable_ocr=True)
        observations2 = build_observations_from_vision(vision2)
        scene_tracker.update(conn, camera_id=camera_id, now_ts=now_ts, observations=observations2)
        
        vehicles2 = [obj for obj in vision2.objects if obj.label and "vehicle" in obj.label.lower()]
        assert len(vehicles2) == 1, "Should detect 1 vehicle (Car A)"
        
        active_tracks2 = conn.execute(
            "SELECT track_key FROM scene_tracks WHERE camera_id = ? AND track_type = 'vehicle' AND active = 1",
            (camera_id,)
        ).fetchall()
        assert len(active_tracks2) == 1, "Should have 1 active vehicle track (Car A)"
        car_a_track_key = active_tracks2[0][0]
        print(f"[TEST] ✓ Step 2 passed: Car A tracked ({car_a_track_key})")
        
        # STEP 3: Both cars present
        print("[TEST] Step 3: Both cars present...")
        now_ts += 2
        vision3 = snapshot_and_detect(db=db_path, rtsp=str(car_a_and_b), camera_id=str(camera_id), debug=True, enable_ocr=True)
        observations3 = build_observations_from_vision(vision3)
        scene_tracker.update(conn, camera_id=camera_id, now_ts=now_ts, observations=observations3)
        
        vehicles3 = [obj for obj in vision3.objects if obj.label and "vehicle" in obj.label.lower()]
        assert len(vehicles3) == 2, "Should detect 2 vehicles (Car A + Car B)"
        
        active_tracks3 = conn.execute(
            "SELECT track_key FROM scene_tracks WHERE camera_id = ? AND track_type = 'vehicle' AND active = 1 ORDER BY first_seen_ts",
            (camera_id,)
        ).fetchall()
        assert len(active_tracks3) == 2, "Should have 2 active vehicle tracks"
        assert active_tracks3[0][0] == car_a_track_key, "Car A should still be tracked"
        car_b_track_key = active_tracks3[1][0]
        print(f"[TEST] ✓ Step 3 passed: Both cars tracked (A: {car_a_track_key}, B: {car_b_track_key})")
        
        # STEP 4: Only Car B remains
        print("[TEST] Step 4: Car A leaves...")
        now_ts += 8  # > grace period
        vision4 = snapshot_and_detect(db=db_path, rtsp=str(car_b), camera_id=str(camera_id), debug=True, enable_ocr=True)
        observations4 = build_observations_from_vision(vision4)
        scene_tracker.update(conn, camera_id=camera_id, now_ts=now_ts, observations=observations4)
        
        vehicles4 = [obj for obj in vision4.objects if obj.label and "vehicle" in obj.label.lower()]
        assert len(vehicles4) == 1, "Should detect 1 vehicle (Car B only)"
        
        active_tracks4 = conn.execute(
            "SELECT track_key FROM scene_tracks WHERE camera_id = ? AND track_type = 'vehicle' AND active = 1",
            (camera_id,)
        ).fetchall()
        assert len(active_tracks4) == 1, "Should have 1 active vehicle track (Car B only)"
        assert active_tracks4[0][0] == car_b_track_key, "Active track should be Car B"
        print(f"[TEST] ✓ Step 4 passed: Car A inactive, Car B active")
        
        # STEP 5: Empty scene again
        print("[TEST] Step 5: All cars leave...")
        now_ts += 8  # > grace period
        vision5 = snapshot_and_detect(db=db_path, rtsp=str(no_cars), camera_id=str(camera_id), debug=True, enable_ocr=True)
        observations5 = build_observations_from_vision(vision5)
        scene_tracker.update(conn, camera_id=camera_id, now_ts=now_ts, observations=observations5)
        
        vehicles5 = [obj for obj in vision5.objects if obj.label and "vehicle" in obj.label.lower()]
        assert len(vehicles5) == 0, "Should detect NO vehicles"
        
        active_tracks5 = conn.execute(
            "SELECT track_key FROM scene_tracks WHERE camera_id = ? AND track_type = 'vehicle' AND active = 1",
            (camera_id,)
        ).fetchall()
        assert len(active_tracks5) == 0, "Should have NO active vehicle tracks"
        print("[TEST] ✓ Step 5 passed: All vehicles inactive")
        
        print("\n[TEST] ✓✓✓ Vehicle tracking lifecycle test PASSED ✓✓✓")


class TestPersonVehicleLinkage:
    """Test person-to-vehicle linkage (basic proximity + timing)"""
    
    def test_basic_person_vehicle_linkage(self, test_db_single_camera):
        """
        Test the complete person-to-vehicle linkage flow:
        1. Vehicle arrives and gets tracked
        2. Person appears next to vehicle shortly after
        3. System links person to vehicle based on proximity and timing
        """
        db_path, conn = test_db_single_camera
        
        # Get test images
        fixtures_dir = Path(__file__).parent / "fixtures" / "vehicle_linkage"
        image1 = fixtures_dir / "1.jpg"
        image2 = fixtures_dir / "2.jpg"
        
        assert image1.exists(), f"Missing test image: {image1}"
        assert image2.exists(), f"Missing test image: {image2}"
        
        scene_tracker = SceneTracker(iou_match_threshold=0.3, grace_period_s=6)
        retention = RetentionSettings()
        camera_id = 1
        now_ts = int(time.time())
        
        # STEP 1: Process vehicle only
        print("\n[TEST] Processing image 1 (vehicle only)...")
        vr1 = snapshot_and_detect(db=db_path, rtsp=str(image1), camera_id=str(camera_id), debug=True, enable_ocr=False)
        
        vehicle_detections = [d for d in vr1.detections if d.cls.lower() == "vehicle"]
        assert len(vehicle_detections) > 0, "No vehicle detected in image 1"
        
        classified1, event_id1 = classify_and_log(
            db_path=db_path, vision=vr1, text="", now_ts=now_ts,
            camera_id=camera_id, retention=retention, scene_tracker=scene_tracker
        )
        
        tracks1 = conn.execute(
            "SELECT track_key FROM scene_tracks WHERE camera_id = ? AND track_type = 'vehicle' AND active = 1",
            (camera_id,)
        ).fetchall()
        assert len(tracks1) > 0, "Vehicle track not created"
        print(f"[TEST] ✓ Vehicle track created")
        
        # STEP 2: Wait 5 seconds, then process vehicle + person
        print("\n[TEST] Processing image 2 (vehicle + person) after 5 seconds...")
        now_ts_2 = now_ts + 5
        
        vr2 = snapshot_and_detect(db=db_path, rtsp=str(image2), camera_id=str(camera_id), debug=True, enable_ocr=False)
        
        vehicle_detections_2 = [d for d in vr2.detections if d.cls.lower() == "vehicle"]
        person_detections_2 = [d for d in vr2.detections if d.cls.lower() == "person"]
        assert len(vehicle_detections_2) > 0, "No vehicle detected in image 2"
        assert len(person_detections_2) > 0, "No person detected in image 2"
        
        classified2, event_id2 = classify_and_log(
            db_path=db_path, vision=vr2, text="", now_ts=now_ts_2,
            camera_id=camera_id, retention=retention, scene_tracker=scene_tracker
        )
        
        # STEP 3: Verify person-vehicle linkage was created
        links = conn.execute(
            "SELECT relation, subject_type, object_type, confidence FROM visit_entity_links WHERE camera_id = ? AND relation = 'arrived_with_vehicle'",
            (camera_id,)
        ).fetchall()
        
        assert len(links) > 0, "No person-to-vehicle linkage created"
        link = links[0]
        assert link[1] == "person", f"Expected subject to be 'person', got '{link[1]}'"
        assert link[2] == "vehicle", f"Expected object to be 'vehicle', got '{link[2]}'"
        assert link[3] > 0.15, f"Link confidence too low: {link[3]}"
        
        print(f"\n[TEST] ✓ Person-to-vehicle linkage verified! Confidence: {link[3]:.2f}")
        
        # Verify linkage evidence was added
        linkage_evidence = [ev for ev in vr2.evidence if ev.source == "scene" and "link.arrived_with_vehicle" in ev.feature]
        assert len(linkage_evidence) > 0, "Linkage evidence not added to vision result"
        
        print("\n[TEST] ✓✓✓ Basic person-vehicle linkage test PASSED ✓✓✓")


class TestPersonVehicleLinkagePersistence:
    """Test ReID persistence and advanced linkage scenarios"""
    
    def test_reid_persistence_and_temporal_filtering(self, test_db_multi_camera):
        """
        Comprehensive test of person-vehicle linkage with ReID:
        1. Vehicle arrives (no person)
        2. Person appears next to vehicle → linkage created
        3. Same person (different pose) → linkage persists via ReID
        4. Different person (far from vehicle) → NOT linked (proximity filter)
        5. Cross-camera with facial recognition → ReID works
        6. Person 1 hour later → NOT linked (temporal filter)
        """
        db_path, conn = test_db_multi_camera
        
        # Get test images
        fixtures_dir = Path(__file__).parent / "fixtures" / "verhicle_linkage_persistance"
        image1 = fixtures_dir / "1.png"
        image2 = fixtures_dir / "2.png"
        image3 = fixtures_dir / "3.png"
        image3_5 = fixtures_dir / "3.5.png"
        image4 = fixtures_dir / "4.png"
        image5 = fixtures_dir / "5.png"
        
        for img in [image1, image2, image3, image3_5, image4, image5]:
            assert img.exists(), f"Missing test image: {img}"
        
        scene_tracker = SceneTracker(iou_match_threshold=0.3, grace_period_s=6)
        retention = RetentionSettings()
        camera_id_1 = 1
        camera_id_2 = 2
        now_ts = int(time.time())
        
        # STEP 1: Vehicle only
        print("\n[TEST] Step 1: Vehicle only...")
        vision1 = snapshot_and_detect(db=db_path, rtsp=str(image1), camera_id=str(camera_id_1), debug=True, enable_ocr=True)
        classify_and_log(db_path=db_path, vision=vision1, text="", now_ts=now_ts, camera_id=camera_id_1, retention=retention, scene_tracker=scene_tracker)
        
        vehicles1 = [obj for obj in vision1.objects if obj.label and "vehicle" in obj.label.lower()]
        assert len(vehicles1) > 0, "Image 1 should detect vehicle"
        print(f"[TEST] ✓ Vehicle tracked")
        
        # STEP 2: Person + vehicle (linkage created)
        print("\n[TEST] Step 2: Person + vehicle...")
        now_ts += 2
        vision2 = snapshot_and_detect(db=db_path, rtsp=str(image2), camera_id=str(camera_id_1), debug=True, enable_ocr=True)
        classify_and_log(db_path=db_path, vision=vision2, text="", now_ts=now_ts, camera_id=camera_id_1, retention=retention, scene_tracker=scene_tracker)
        
        links2 = conn.execute("SELECT subject_key, object_key, confidence FROM visit_entity_links WHERE camera_id = ?", (camera_id_1,)).fetchall()
        assert len(links2) > 0, "Should have created person-vehicle link"
        person_track_key = links2[0][0]
        vehicle_track_key = links2[0][1]
        print(f"[TEST] ✓ Linkage created (person: {person_track_key}, vehicle: {vehicle_track_key}, conf: {links2[0][2]:.3f})")
        
        # STEP 3: Same person, different pose (ReID persistence)
        print("\n[TEST] Step 3: Same person, different pose (ReID)...")
        now_ts += 2
        vision3 = snapshot_and_detect(db=db_path, rtsp=str(image3), camera_id=str(camera_id_1), debug=True, enable_ocr=True)
        classify_and_log(db_path=db_path, vision=vision3, text="", now_ts=now_ts, camera_id=camera_id_1, retention=retention, scene_tracker=scene_tracker)
        
        person_tracks = conn.execute(
            "SELECT track_key FROM scene_tracks WHERE camera_id = ? AND track_type = 'person' AND active = 1",
            (camera_id_1,)
        ).fetchall()
        assert len(person_tracks) == 1, "Should have ONE person track (ReID matched)"
        assert person_tracks[0][0] == person_track_key, "ReID should match person across frames"
        print(f"[TEST] ✓ ReID matched person across frames")
        
        # STEP 4: Different person (far from vehicle) - NOT linked
        print("\n[TEST] Step 4: Different person (far from vehicle)...")
        now_ts += 2
        vision3_5 = snapshot_and_detect(db=db_path, rtsp=str(image3_5), camera_id=str(camera_id_1), debug=True, enable_ocr=True)
        classify_and_log(db_path=db_path, vision=vision3_5, text="", now_ts=now_ts, camera_id=camera_id_1, retention=retention, scene_tracker=scene_tracker)
        
        person_tracks_after = conn.execute(
            "SELECT track_key FROM scene_tracks WHERE camera_id = ? AND track_type = 'person' AND active = 1 ORDER BY first_seen_ts",
            (camera_id_1,)
        ).fetchall()
        assert len(person_tracks_after) == 2, "Should have TWO person tracks (original + new)"
        
        new_person_track = [t[0] for t in person_tracks_after if t[0] != person_track_key][0]
        new_person_links = conn.execute(
            "SELECT * FROM visit_entity_links WHERE camera_id = ? AND subject_key = ?",
            (camera_id_1, new_person_track)
        ).fetchall()
        assert len(new_person_links) == 0, "New person should NOT be linked (too far from vehicle)"
        print(f"[TEST] ✓ Proximity filter works (distant person not linked)")
        
        # STEP 5: Cross-camera with facial recognition
        print("\n[TEST] Step 5: Cross-camera ReID...")
        now_ts += 8
        vision4 = snapshot_and_detect(db=db_path, rtsp=str(image4), camera_id=str(camera_id_2), debug=True, enable_ocr=False)
        classify_and_log(db_path=db_path, vision=vision4, text="", now_ts=now_ts, camera_id=camera_id_2, retention=retention, scene_tracker=scene_tracker)
        
        person_tracks_cam2 = conn.execute(
            "SELECT track_key, key_kind FROM scene_tracks WHERE camera_id = ? AND track_type = 'person' AND active = 1",
            (camera_id_2,)
        ).fetchall()
        assert len(person_tracks_cam2) == 1, "Should have ONE person track on camera 2"
        assert person_tracks_cam2[0][1] == "visitor", "Should use visitor_id key kind"
        assert person_tracks_cam2[0][0] == person_track_key, "Cross-camera ReID should match same visitor"
        print(f"[TEST] ✓ Cross-camera ReID works (visitor_id: {person_track_key})")
        
        # STEP 6: Person 1 hour later - NOT linked (temporal filter)
        print("\n[TEST] Step 6: Person 1 hour later (temporal filter)...")
        now_ts += 3600  # 1 hour
        vision5 = snapshot_and_detect(db=db_path, rtsp=str(image5), camera_id=str(camera_id_1), debug=True, enable_ocr=True)
        classify_and_log(db_path=db_path, vision=vision5, text="", now_ts=now_ts, camera_id=camera_id_1, retention=retention, scene_tracker=scene_tracker)
        
        all_person_tracks = conn.execute(
            "SELECT track_key, first_seen_ts, last_seen_ts FROM scene_tracks WHERE camera_id = ? AND track_type = 'person' AND active = 1 ORDER BY first_seen_ts",
            (camera_id_1,)
        ).fetchall()
        
        late_person_track = [t for t in all_person_tracks if t[2] == now_ts][0]
        late_person_links = conn.execute(
            "SELECT * FROM visit_entity_links WHERE camera_id = ? AND subject_key = ?",
            (camera_id_1, late_person_track[0])
        ).fetchall()
        assert len(late_person_links) == 0, "Person 1 hour later should NOT be linked (outside time window)"
        print(f"[TEST] ✓ Temporal filter works (late arrival not linked)")
        
        print("\n[TEST] ✓✓✓ ReID persistence and filtering test PASSED ✓✓✓")
        print("[TEST] Summary:")
        print("  ✓ Person-vehicle linkage created")
        print("  ✓ ReID persistence (same person, different pose)")
        print("  ✓ Proximity filtering (distant person not linked)")
        print("  ✓ Cross-camera ReID with facial recognition")
        print("  ✓ Temporal filtering (late arrival not linked)")

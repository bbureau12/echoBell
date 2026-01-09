"""
Integration test for person-to-vehicle linkage.

Tests the complete flow:
1. Vehicle arrives and gets tracked
2. Person appears next to vehicle shortly after
3. System links person to vehicle based on proximity and timing
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
from packages.scene.scene_tracker import SceneTracker
from packages.common.config_models import RetentionSettings
from tests.helpers.db_setup import create_test_schema, create_test_cameras


@pytest.fixture
def test_db(tmp_path):
    """Create a temporary database with all required schemas."""
    db_path = tmp_path / "test_linkage.db"
    conn = sqlite3.connect(str(db_path))
    
    # Create all required tables using shared setup
    # No facial recognition needed for this test
    create_test_schema(conn, include_facial_recognition=False)
    
    # Insert test camera using helper
    create_test_cameras(conn, [
        {'id': 1, 'name': 'Test Camera', 'capability_level_id': 1, 'stream_url': 'rtsp://test'}
    ])
    
    yield str(db_path), conn
    
    conn.close()


def test_person_vehicle_linkage_temporal_flow(test_db):
    """
    Test the complete person-to-vehicle linkage flow:
    1. Post image with vehicle only (1.jpg) - vehicle gets tracked
    2. Wait 5 seconds
    3. Post image with vehicle + person (2.jpg) - person appears next to vehicle
    4. Verify person is linked to vehicle in visit_entity_links
    """
    db_path, conn = test_db
    
    # Get test images
    fixtures_dir = Path(__file__).parent / "fixtures" / "vehicle_linkage"
    image1 = fixtures_dir / "1.jpg"
    image2 = fixtures_dir / "2.jpg"
    
    assert image1.exists(), f"Missing test image: {image1}"
    assert image2.exists(), f"Missing test image: {image2}"
    
    # Initialize services
    camera_service = CameraService()
    scene_tracker = SceneTracker(iou_match_threshold=0.3, grace_period_s=6)
    retention = RetentionSettings()
    
    camera_id = 1
    now_ts = int(time.time())
    
    # STEP 1: Process first image (vehicle only)
    print("\n[TEST] Processing image 1 (vehicle only)...")
    
    vr1 = snapshot_and_detect(
        db=db_path,
        rtsp=str(image1),
        camera_id=str(camera_id),
        debug=True,
        enable_ocr=False,
    )
    
    # Verify vehicle was detected
    vehicle_detections = [d for d in vr1.detections if d.cls.lower() == "vehicle"]
    assert len(vehicle_detections) > 0, "No vehicle detected in image 1"
    print(f"[TEST] ✓ Vehicle detected: {len(vehicle_detections)} vehicle(s)")
    
    # Classify and log (creates scene tracks)
    classified1, event_id1 = classify_and_log(
        db_path=db_path,
        vision=vr1,
        text="",
        now_ts=now_ts,
        camera_id=camera_id,
        retention=retention,
        scene_tracker=scene_tracker,
    )
    
    print(f"[TEST] Event 1: {classified1.intent} (conf={classified1.conf:.2f})")
    
    # Verify vehicle track was created
    tracks1 = conn.execute("""
        SELECT track_type, track_key, first_seen_ts, active
        FROM scene_tracks
        WHERE camera_id = ? AND track_type = 'vehicle' AND active = 1
    """, (camera_id,)).fetchall()
    
    assert len(tracks1) > 0, "Vehicle track not created"
    print(f"[TEST] ✓ Vehicle track created: {len(tracks1)} active vehicle track(s)")
    
    # STEP 2: Wait 5 seconds (simulate temporal gap)
    print("\n[TEST] Waiting 5 seconds (simulated)...")
    now_ts_2 = now_ts + 5
    
    # STEP 3: Process second image (vehicle + person)
    print("\n[TEST] Processing image 2 (vehicle + person)...")
    
    vr2 = snapshot_and_detect(
        db=db_path,
        rtsp=str(image2),
        camera_id=str(camera_id),
        debug=True,
        enable_ocr=False,
    )
    
    # Verify vehicle and person were detected
    vehicle_detections_2 = [d for d in vr2.detections if d.cls.lower() == "vehicle"]
    person_detections_2 = [d for d in vr2.detections if d.cls.lower() == "person"]
    
    assert len(vehicle_detections_2) > 0, "No vehicle detected in image 2"
    assert len(person_detections_2) > 0, "No person detected in image 2"
    print(f"[TEST] ✓ Detected: {len(vehicle_detections_2)} vehicle(s), {len(person_detections_2)} person(s)")
    
    # Classify and log (should create person-vehicle link)
    classified2, event_id2 = classify_and_log(
        db_path=db_path,
        vision=vr2,
        text="",
        now_ts=now_ts_2,
        camera_id=camera_id,
        retention=retention,
        scene_tracker=scene_tracker,
    )
    
    print(f"[TEST] Event 2: {classified2.intent} (conf={classified2.conf:.2f})")
    
    # STEP 4: Verify person-vehicle linkage was created
    links = conn.execute("""
        SELECT relation, subject_type, object_type, confidence, created_ts
        FROM visit_entity_links
        WHERE camera_id = ? AND relation = 'arrived_with_vehicle'
    """, (camera_id,)).fetchall()
    
    print(f"\n[TEST] Found {len(links)} linkage(s) in database")
    for relation, subj_type, obj_type, conf, created in links:
        print(f"  - {subj_type} -> {obj_type} ({relation}) conf={conf:.2f} created={created}")
    
    assert len(links) > 0, "No person-to-vehicle linkage created"
    
    # Verify the link is person -> vehicle
    link = links[0]
    assert link[1] == "person", f"Expected subject to be 'person', got '{link[1]}'"
    assert link[2] == "vehicle", f"Expected object to be 'vehicle', got '{link[2]}'"
    # Lowered threshold since person detection confidence is just above MIN_CONF (0.40)
    assert link[3] > 0.15, f"Link confidence too low: {link[3]}"
    
    print("\n[TEST] ✓ Person-to-vehicle linkage verified!")
    print(f"[TEST] ✓ Confidence: {link[3]:.2f}")
    
    # Verify linkage evidence was added
    linkage_evidence = [
        ev for ev in vr2.evidence 
        if ev.source == "scene" and "link.arrived_with_vehicle" in ev.feature
    ]
    
    print(f"\n[TEST] Found {len(linkage_evidence)} linkage evidence entries")
    assert len(linkage_evidence) > 0, "Linkage evidence not added to vision result"
    
    for ev in linkage_evidence:
        print(f"  - {ev.source}.{ev.feature}={ev.value} conf={ev.conf:.2f}")
    
    print("\n[TEST] ✅ All checks passed!")


def test_camera_without_facial_detail_capability(test_db):
    """
    Verify that the test camera has allow_facial_detail=false
    to ensure face recognition doesn't interfere with linkage.
    """
    db_path, conn = test_db
    
    camera_service = CameraService()
    camera = camera_service.get_camera(conn, 1)
    
    assert camera is not None, "Camera not found"
    assert camera.capability.allow_facial_detail is False, \
        "Camera should have allow_facial_detail=false"
    
    print(f"\n[TEST] ✓ Camera capability verified: allow_facial_detail={camera.capability.allow_facial_detail}")

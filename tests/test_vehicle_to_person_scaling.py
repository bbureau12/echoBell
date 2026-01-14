"""
Integration test for vehicle-to-person size ratio validation.

Tests that the linkage system correctly rejects person-vehicle associations
when the size ratios are unrealistic (person too large or too small relative
to vehicle).

Uses real images with YOLO detection to validate end-to-end behavior:
- human_too_big.jpg: Person unreasonably large compared to vehicle → NO LINK
- human_too_small.jpg: Person unreasonably small compared to vehicle → NO LINK
"""

import pytest
import sqlite3
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from packages.perception.vision import snapshot_and_detect
from packages.classify.classify_and_log import classify_and_log
from packages.scene.scene_tracker import SceneTracker
from packages.common.config_models import RetentionSettings
from tests.helpers.db_setup import create_test_schema, create_test_cameras


@pytest.fixture
def test_db(tmp_path):
    """Create a temporary database with required schemas."""
    db_path = tmp_path / "test_scaling.db"
    conn = sqlite3.connect(str(db_path))
    
    # Create all required tables (include facial recognition for visitor_embeddings)
    create_test_schema(conn, include_facial_recognition=True)
    
    # Insert test camera
    create_test_cameras(conn, [
        {'id': 1, 'name': 'Test Camera', 'capability_level_id': 1, 'stream_url': 'rtsp://test'}
    ])
    
    yield str(db_path), conn
    
    conn.close()


class TestVehicleToPersonScaling:
    """Test size ratio validation prevents unrealistic linkages."""
    
    def test_person_too_big_relative_to_vehicle_no_link(self, test_db):
        """
        Test that person unreasonably large compared to vehicle is NOT linked.
        
        Scenario: Person appears much larger than vehicle (e.g., toy car, 
        misdetection, or perspective issue). The size ratio check should 
        reject this linkage.
        """
        db_path, conn = test_db
        
        # Get test image
        fixtures_dir = Path(__file__).parent / "fixtures" / "vehicle_to_person_scaling"
        image_path = fixtures_dir / "human_too_big.jpg"
        
        assert image_path.exists(), f"Missing test image: {image_path}"
        
        # Initialize services
        scene_tracker = SceneTracker(iou_match_threshold=0.3, grace_period_s=6)
        retention = RetentionSettings()
        camera_id = 1
        now_ts = int(time.time())
        
        print("\n[TEST] Processing human_too_big.jpg...")
        
        # Run vision detection
        vr = snapshot_and_detect(
            db=db_path,
            rtsp=str(image_path),
            camera_id=str(camera_id),
            debug=True,
            enable_ocr=False,
        )
        
        # Verify both person and vehicle were detected
        person_objs = [obj for obj in vr.objects if obj.label == "person"]
        vehicle_objs = [obj for obj in vr.objects if obj.label == "vehicle"]
        
        assert len(person_objs) > 0, "No person detected in image"
        assert len(vehicle_objs) > 0, "No vehicle detected in image"
        
        print(f"[TEST] ✓ Detected {len(person_objs)} person(s), {len(vehicle_objs)} vehicle(s)")
        
        # Check the size ratio
        person = person_objs[0]
        vehicle = vehicle_objs[0]
        
        # Calculate sizes for debugging
        p_w = person.box[2] - person.box[0]
        p_h = person.box[3] - person.box[1]
        v_w = vehicle.box[2] - vehicle.box[0]
        v_h = vehicle.box[3] - vehicle.box[1]
        
        import math
        p_diag = math.hypot(p_w, p_h)
        v_diag = math.hypot(v_w, v_h)
        ratio = p_diag / v_diag
        
        print(f"[TEST] Person diagonal: {p_diag:.1f}px")
        print(f"[TEST] Vehicle diagonal: {v_diag:.1f}px")
        print(f"[TEST] Size ratio: {ratio:.2f}")
        
        # Classify and log
        classified, event_id = classify_and_log(
            db_path=db_path,
            vision=vr,
            text="",
            now_ts=now_ts,
            camera_id=camera_id,
            retention=retention,
            scene_tracker=scene_tracker,
        )
        
        print(f"[TEST] Event ID: {event_id}")
        print(f"[TEST] Intent: {classified.intent} (conf={classified.conf:.2f})")
        
        # Check visit_entity_links - should NOT have person-vehicle link
        links = conn.execute("""
            SELECT visit_id, relation, subject_type, object_type, confidence
            FROM visit_entity_links
            WHERE visit_id = ?
        """, (event_id,)).fetchall()
        
        print(f"[TEST] Found {len(links)} links")
        for link in links:
            print(f"[TEST]   - {link[1]}: {link[2]} → {link[3]} (conf={link[4]:.2f})")
        
        # Filter for person-vehicle linkage
        person_vehicle_links = [
            link for link in links 
            if link[1] == "arrived_with_vehicle"  # relation
        ]
        
        # ASSERTION: Person should NOT be linked to vehicle due to size ratio
        assert len(person_vehicle_links) == 0, \
            f"Expected NO person-vehicle link due to size ratio, but found {len(person_vehicle_links)}"
        
        print("[TEST] ✓ Person correctly NOT linked to vehicle (size ratio check passed)")
    
    def test_person_too_small_relative_to_vehicle_no_link(self, test_db):
        """
        Test that person unreasonably small compared to vehicle is NOT linked.
        
        Scenario: Person appears much smaller than vehicle (e.g., just a head 
        visible in corner, partial detection). The size ratio check should 
        reject this linkage.
        """
        db_path, conn = test_db
        
        # Get test image
        fixtures_dir = Path(__file__).parent / "fixtures" / "vehicle_to_person_scaling"
        image_path = fixtures_dir / "human_too_small.jpg"
        
        assert image_path.exists(), f"Missing test image: {image_path}"
        
        # Initialize services
        scene_tracker = SceneTracker(iou_match_threshold=0.3, grace_period_s=6)
        retention = RetentionSettings()
        camera_id = 1
        now_ts = int(time.time())
        
        print("\n[TEST] Processing human_too_small.jpg...")
        
        # Run vision detection
        vr = snapshot_and_detect(
            db=db_path,
            rtsp=str(image_path),
            camera_id=str(camera_id),
            debug=True,
            enable_ocr=False,
        )
        
        # Verify both person and vehicle were detected
        person_objs = [obj for obj in vr.objects if obj.label == "person"]
        vehicle_objs = [obj for obj in vr.objects if obj.label == "vehicle"]
        
        # Skip test if person not detected (YOLO confidence too low or person too small)
        if len(person_objs) == 0:
            pytest.skip("Person not detected in image (may be too small for YOLO threshold)")
        
        assert len(vehicle_objs) > 0, "No vehicle detected in image"
        
        print(f"[TEST] ✓ Detected {len(person_objs)} person(s), {len(vehicle_objs)} vehicle(s)")
        
        # Check the size ratio
        person = person_objs[0]
        vehicle = vehicle_objs[0]
        
        # Calculate sizes for debugging
        p_w = person.box[2] - person.box[0]
        p_h = person.box[3] - person.box[1]
        v_w = vehicle.box[2] - vehicle.box[0]
        v_h = vehicle.box[3] - vehicle.box[1]
        
        import math
        p_diag = math.hypot(p_w, p_h)
        v_diag = math.hypot(v_w, v_h)
        ratio = p_diag / v_diag
        
        print(f"[TEST] Person diagonal: {p_diag:.1f}px")
        print(f"[TEST] Vehicle diagonal: {v_diag:.1f}px")
        print(f"[TEST] Size ratio: {ratio:.2f}")
        
        # Classify and log
        classified, event_id = classify_and_log(
            db_path=db_path,
            vision=vr,
            text="",
            now_ts=now_ts,
            camera_id=camera_id,
            retention=retention,
            scene_tracker=scene_tracker,
        )
        
        print(f"[TEST] Event ID: {event_id}")
        print(f"[TEST] Intent: {classified.intent} (conf={classified.conf:.2f})")
        
        # Check visit_entity_links - should NOT have person-vehicle link
        links = conn.execute("""
            SELECT visit_id, relation, subject_type, object_type, confidence
            FROM visit_entity_links
            WHERE visit_id = ?
        """, (event_id,)).fetchall()
        
        print(f"[TEST] Found {len(links)} links")
        for link in links:
            print(f"[TEST]   - {link[1]}: {link[2]} → {link[3]} (conf={link[4]:.2f})")
        
        # Filter for person-vehicle linkage
        person_vehicle_links = [
            link for link in links 
            if link[1] == "arrived_with_vehicle"  # relation
        ]
        
        # ASSERTION: Person should NOT be linked to vehicle due to size ratio
        assert len(person_vehicle_links) == 0, \
            f"Expected NO person-vehicle link due to size ratio, but found {len(person_vehicle_links)}"
        
        print("[TEST] ✓ Person correctly NOT linked to vehicle (size ratio check passed)")


if __name__ == "__main__":
    # Allow running this test directly for debugging
    pytest.main([__file__, "-v", "-s"])

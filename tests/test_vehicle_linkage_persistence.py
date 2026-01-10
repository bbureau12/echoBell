"""
Integration test for person-to-vehicle linkage PERSISTENCE.

Tests that linkage persists across frames using ReID:
1. Image 1: Vehicle arrives (no person)
2. Image 2: Person appears next to vehicle → linkage created
3. Image 3: Same person (different position) → linkage persists via ReID
4. Image 4: Different camera with facial recognition → cross-camera ReID

Cameras:
- Camera 1: Vehicle ID only, NO facial recognition
- Camera 2: Vehicle ID + facial recognition enabled
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
    """Create a temporary database with all required schemas and cameras."""
    db_path = tmp_path / "test_linkage_persistence.db"
    conn = sqlite3.connect(str(db_path))
    
    # Create all required tables using shared setup
    create_test_schema(conn, include_facial_recognition=True)
    
    # Insert both cameras using helper
    create_test_cameras(conn, [
        {'id': 1, 'name': 'Test Camera - Vehicle ID Only', 'capability_level_id': 1, 'stream_url': 'rtsp://test1'},
        {'id': 2, 'name': 'Test Camera - Facial Recognition', 'capability_level_id': 2, 'stream_url': 'rtsp://test2'}
    ])
    
    yield str(db_path), conn
    
    conn.close()


def test_person_vehicle_linkage_persists_via_reid(test_db):
    """
    Test that person-vehicle linkage persists across frames using ReID:
    1. Image 1: Vehicle only → vehicle tracked
    2. Image 2: Person + vehicle → linkage created
    3. Image 3: Same person (different pose) → linkage persists via ReID
    3.5. Image 3.5: Different person (NOT near vehicle) → separate individual, NOT linked
    4. Image 4: Different camera with facial recognition → cross-camera ReID
    5. Image 5: Person walks past car 1 hour later → NOT linked (outside time window)
    
    Camera has vehicle ID capabilities but NO facial recognition.
    """
    db_path, conn = test_db
    
    # Get test images
    fixtures_dir = Path(__file__).parent / "fixtures" / "verhicle_linkage_persistance"
    image1 = fixtures_dir / "1.png"
    image2 = fixtures_dir / "2.png"
    image3 = fixtures_dir / "3.png"
    image3_5 = fixtures_dir / "3.5.png"
    image5 = fixtures_dir / "5.png"
    
    assert image1.exists(), f"Missing test image: {image1}"
    assert image2.exists(), f"Missing test image: {image2}"
    assert image3.exists(), f"Missing test image: {image3}"
    assert image3_5.exists(), f"Missing test image: {image3_5}"
    assert image5.exists(), f"Missing test image: {image5}"
    
    # Initialize services
    scene_tracker = SceneTracker(iou_match_threshold=0.3, grace_period_s=6)
    retention = RetentionSettings()
    
    camera_id = 1
    now_ts = int(time.time())
    
    # STEP 1: Process first image (vehicle only)
    print("\n[TEST] Processing image 1 (vehicle only)...")
    
    vision1 = snapshot_and_detect(
        db=db_path,
        rtsp=str(image1),
        camera_id=str(camera_id),
        debug=True,
        enable_ocr=True,
    )
    
    # Process through full pipeline
    classified1, event_id1 = classify_and_log(
        db_path=db_path,
        vision=vision1,
        text="",
        now_ts=now_ts,
        camera_id=camera_id,
        retention=retention,
        scene_tracker=scene_tracker,
    )
    
    # Verify: Should have vehicle, no person
    vehicles1 = [obj for obj in vision1.objects if obj.label and "vehicle" in obj.label.lower()]
    persons1 = [obj for obj in vision1.objects if obj.label and obj.label.lower() == "person"]
    
    print(f"[TEST] Image 1: All objects: {[obj.label for obj in vision1.objects]}")
    
    assert len(vehicles1) > 0, f"Image 1 should detect vehicle. Got: {[obj.label for obj in vision1.objects]}"
    assert len(persons1) == 0, "Image 1 should have no person"
    
    print(f"[TEST] Image 1: {len(vehicles1)} vehicle(s), {len(persons1)} person(s)")
    
    #Step 2: Process second image (person + vehicle) - 2 seconds later
    print("\n[TEST] Processing image 2 (person + vehicle)...")
    now_ts += 2
    
    vision2 = snapshot_and_detect(
        db=db_path,
        rtsp=str(image2),
        camera_id=str(camera_id),
        debug=True,
        enable_ocr=True,
    )
    
    # Process through full pipeline
    classified2, event_id2 = classify_and_log(
        db_path=db_path,
        vision=vision2,
        text="",
        now_ts=now_ts,
        camera_id=camera_id,
        retention=retention,
        scene_tracker=scene_tracker,
    )
    
    # Verify: Should have vehicle + person
    vehicles2 = [obj for obj in vision2.objects if obj.label and "vehicle" in obj.label.lower()]
    persons2 = [obj for obj in vision2.objects if obj.label and obj.label.lower() == "person"]
    
    print(f"[TEST] Image 2: All objects: {[obj.label for obj in vision2.objects]}")
    
    assert len(vehicles2) > 0, f"Image 2 should detect vehicle. Got: {[obj.label for obj in vision2.objects]}"
    assert len(persons2) > 0, f"Image 2 should detect person. Got: {[obj.label for obj in vision2.objects]}"
    
    print(f"[TEST] Image 2: {len(vehicles2)} vehicle(s), {len(persons2)} person(s)")
    
    # Check linkage was created
    links2 = conn.execute("""
        SELECT subject_type, object_type, relation, confidence, subject_key, object_key
        FROM visit_entity_links
        WHERE camera_id = ?
        ORDER BY created_ts DESC
    """, (camera_id,)).fetchall()
    
    assert len(links2) > 0, "Should have created person-vehicle link in image 2"
    
    link2 = links2[0]
    assert link2[0] == "person", "Subject should be person"
    assert link2[1] == "vehicle", "Object should be vehicle"
    assert link2[2] == "arrived_with_vehicle", "Relation should be arrived_with_vehicle"
    
    # Store the person's track key for verification
    person_track_key_img2 = link2[4]  # subject_key
    vehicle_track_key_img2 = link2[5]  # object_key
    
    print(f"[TEST] Image 2 created linkage:")
    print(f"  Person track: {person_track_key_img2}")
    print(f"  Vehicle track: {vehicle_track_key_img2}")
    print(f"  Confidence: {link2[3]:.3f}")
    
    # STEP 3: Process third image (same person, different pose) - 2 seconds later
    print("\n[TEST] Processing image 3 (same person, different pose)...")
    now_ts += 2
    
    vision3 = snapshot_and_detect(
        db=db_path,
        rtsp=str(image3),
        camera_id=str(camera_id),
        debug=True,
        enable_ocr=True,
    )
    
    # Process through full pipeline
    classified3, event_id3 = classify_and_log(
        db_path=db_path,
        vision=vision3,
        text="",
        now_ts=now_ts,
        camera_id=camera_id,
        retention=retention,
        scene_tracker=scene_tracker,
    )
    
    # Verify: Should have person
    persons3 = [obj for obj in vision3.objects if obj.label == "person"]
    assert len(persons3) > 0, "Image 3 should detect person"
    
    print(f"[TEST] Image 3: {len(persons3)} person(s)")
    
    # Check scene_tracks - person should be matched to same track via ReID
    person_tracks = conn.execute("""
        SELECT track_key, key_kind, first_seen_ts, last_seen_ts
        FROM scene_tracks
        WHERE camera_id = ? AND track_type = 'person' AND active = 1
        ORDER BY last_seen_ts DESC
    """, (camera_id,)).fetchall()
    
    print(f"\n[TEST] Active person tracks: {len(person_tracks)}")
    for track in person_tracks:
        print(f"  Track: {track[0]} (kind: {track[1]}, first: {track[2]}, last: {track[3]})")
    
    # The person should be tracked as the SAME person across images 2 and 3
    # ReID should identify them as the same person using temp: track key
    assert len(person_tracks) == 1, "Should have ONE person track (ReID matched them)"
    
    person_track = person_tracks[0]
    person_track_key_img3 = person_track[0]
    
    # Verify it's the same track from image 2
    assert person_track_key_img3 == person_track_key_img2, \
        f"ReID should match person across frames: {person_track_key_img2} vs {person_track_key_img3}"
    
    print(f"\n[TEST] ✓ ReID successfully matched person across images 2 and 3")
    print(f"  Track key: {person_track_key_img3}")
    
    # Check that linkage still exists and references the same person track
    links3 = conn.execute("""
        SELECT subject_type, object_type, relation, confidence, subject_key, object_key
        FROM visit_entity_links
        WHERE camera_id = ? AND subject_key = ?
        ORDER BY created_ts DESC
    """, (camera_id, person_track_key_img3)).fetchall()
    
    assert len(links3) > 0, "Linkage should persist for the same person track"
    
    link3 = links3[0]
    assert link3[4] == person_track_key_img2, "Person track should be the same"
    assert link3[5] == vehicle_track_key_img2, "Vehicle track should be the same"
    
    print(f"\n[TEST] ✓ Linkage persisted across frames:")
    print(f"  Person: {link3[4]}")
    print(f"  Vehicle: {link3[5]}")
    print(f"  Confidence: {link3[3]:.3f}")
    
    # STEP 3.5: Process image 3.5 (different person, NOT near vehicle) - 2 seconds later
    print("\n[TEST] Processing image 3.5 (different person, NOT near vehicle)...")
    now_ts += 2
    
    vision3_5 = snapshot_and_detect(
        db=db_path,
        rtsp=str(image3_5),
        camera_id=str(camera_id),
        debug=True,
        enable_ocr=True,
    )
    
    # Process through full pipeline
    classified3_5, event_id3_5 = classify_and_log(
        db_path=db_path,
        vision=vision3_5,
        text="",
        now_ts=now_ts,
        camera_id=camera_id,
        retention=retention,
        scene_tracker=scene_tracker,
    )
    
    # Verify: Should have detected person(s)
    persons3_5 = [obj for obj in vision3_5.objects if obj.label and obj.label.lower() == "person"]
    assert len(persons3_5) > 0, f"Image 3.5 should detect person. Got: {[obj.label for obj in vision3_5.objects]}"
    
    print(f"[TEST] Image 3.5: {len(persons3_5)} person(s)")
    
    # Check scene_tracks - should now have TWO active person tracks
    person_tracks_after_3_5 = conn.execute("""
        SELECT track_key, key_kind, first_seen_ts, last_seen_ts
        FROM scene_tracks
        WHERE camera_id = ? AND track_type = 'person' AND active = 1
        ORDER BY first_seen_ts ASC
    """, (camera_id,)).fetchall()
    
    print(f"\n[TEST] Active person tracks after image 3.5: {len(person_tracks_after_3_5)}")
    for track in person_tracks_after_3_5:
        print(f"  Track: {track[0]} (kind: {track[1]}, first: {track[2]}, last: {track[3]})")
    
    # Should have TWO person tracks: original person and new person
    assert len(person_tracks_after_3_5) == 2, \
        f"Should have TWO person tracks (original + new person), got {len(person_tracks_after_3_5)}"
    
    # Find the new person's track (the one that's NOT the original person)
    new_person_track = None
    for track in person_tracks_after_3_5:
        if track[0] != person_track_key_img2:
            new_person_track = track
            break
    
    assert new_person_track is not None, "Should have identified new person track"
    new_person_track_key = new_person_track[0]
    
    print(f"\n[TEST] New person identified:")
    print(f"  Original person track: {person_track_key_img2}")
    print(f"  New person track: {new_person_track_key}")
    
    # CRITICAL: Check that new person is NOT linked to the vehicle
    new_person_links = conn.execute("""
        SELECT subject_type, object_type, relation, confidence, subject_key, object_key
        FROM visit_entity_links
        WHERE camera_id = ? AND subject_key = ?
    """, (camera_id, new_person_track_key)).fetchall()
    
    assert len(new_person_links) == 0, \
        f"New person should NOT be linked to vehicle (too far away). Found {len(new_person_links)} links"
    
    print(f"\n[TEST] ✓ New person correctly NOT linked to vehicle:")
    print(f"  New person track: {new_person_track_key}")
    print(f"  Links to vehicle: {len(new_person_links)} (expected 0)")
    
    # Verify original person is STILL linked to vehicle
    original_person_links = conn.execute("""
        SELECT subject_type, object_type, relation, subject_key, object_key
        FROM visit_entity_links
        WHERE camera_id = ? AND subject_key = ?
    """, (camera_id, person_track_key_img2)).fetchall()
    
    assert len(original_person_links) > 0, "Original person should still be linked to vehicle"
    print(f"[TEST] ✓ Original person still linked to vehicle: {len(original_person_links)} link(s)")
    
    # STEP 4: Process fourth image on DIFFERENT camera with facial recognition - 8 seconds later
    print("\n[TEST] Processing image 4 (different camera with facial recognition)...")
    now_ts += 8
    
    camera_id_2 = 2  # Camera 2 already created in fixture with facial recognition
    
    vision4 = snapshot_and_detect(
        db=db_path,
        rtsp=str(fixtures_dir / "4.png"),
        camera_id=str(camera_id_2),
        debug=True,
        enable_ocr=False,
    )
    
    # Process through full pipeline
    classified4, event_id4 = classify_and_log(
        db_path=db_path,
        vision=vision4,
        text="",
        now_ts=now_ts,
        camera_id=camera_id_2,
        retention=retention,
        scene_tracker=scene_tracker,
    )
    
    # Verify: Should have detected person
    persons4 = [obj for obj in vision4.objects if obj.label and obj.label.lower() == "person"]
    assert len(persons4) > 0, f"Image 4 should detect person. Got: {[obj.label for obj in vision4.objects]}"
    
    print(f"[TEST] Image 4: {len(persons4)} person(s)")
    
    # Check that ReID matched this to the SAME visitor_id across cameras
    person_tracks_cam2 = conn.execute("""
        SELECT track_key, key_kind, first_seen_ts, last_seen_ts
        FROM scene_tracks
        WHERE camera_id = ? AND track_type = 'person' AND active = 1
        ORDER BY last_seen_ts DESC
    """, (camera_id_2,)).fetchall()
    
    print(f"\n[TEST] Camera 2 person tracks: {len(person_tracks_cam2)}")
    for track in person_tracks_cam2:
        print(f"  Track: {track[0]} (kind: {track[1]})")
    
    # The person should be tracked with the SAME visitor_id from camera 1
    # ReID should have matched them across cameras
    assert len(person_tracks_cam2) == 1, "Should have ONE person track on camera 2"
    
    person_track_cam2 = person_tracks_cam2[0]
    person_track_key_img4 = person_track_cam2[0]
    person_key_kind_img4 = person_track_cam2[1]
    
    # The key_kind should be "visitor" (same visitor_id from ReID)
    assert person_key_kind_img4 == "visitor", f"Should use visitor_id key kind, got: {person_key_kind_img4}"
    
    # The visitor_id should match the one from camera 1
    assert person_track_key_img4 == person_track_key_img2, \
        f"Cross-camera ReID should match same visitor: {person_track_key_img2} vs {person_track_key_img4}"
    
    print(f"\n[TEST] ✓ Cross-camera ReID successful:")
    print(f"  Camera 1 visitor_id: {person_track_key_img2}")
    print(f"  Camera 2 visitor_id: {person_track_key_img4}")
    print(f"  Match: {person_track_key_img2 == person_track_key_img4}")
    
    # Check if facial recognition was performed and visitor_id was set
    visitor_check = conn.execute("""
        SELECT visitor_id, first_seen_ts, last_seen_ts
        FROM known_visitors
        WHERE visitor_id = ?
    """, (person_track_key_img4,)).fetchone()
    
    assert visitor_check is not None, "Visitor should be registered in known_visitors table"
    print(f"\n[TEST] ✓ Visitor registered:")
    print(f"  visitor_id: {visitor_check[0]}")
    print(f"  First seen: {visitor_check[1]}")
    print(f"  Last seen: {visitor_check[2]}")
    
    # Check if facial embedding was stored
    embeddings = conn.execute("""
        SELECT embedding_id, visitor_id, model_name, camera_id
        FROM visitor_embeddings
        WHERE visitor_id = ?
        ORDER BY created_ts DESC
    """, (person_track_key_img4,)).fetchall()
    
    print(f"\n[TEST] Facial embeddings stored: {len(embeddings)}")
    for emb in embeddings:
        print(f"  Embedding: {emb[0][:16]}... (visitor: {emb[1]}, model: {emb[2]}, camera: {emb[3]})")
    
    assert len(embeddings) > 0, "Should have at least one facial embedding stored"
    
    print("\n[TEST] ✓ Test Step 4 passed: Cross-camera ReID with facial recognition works!")
    
    # STEP 5: Process image 5 (person walks past car) - 1 HOUR later on camera 1
    print("\n[TEST] Processing image 5 (person walks past car 1 hour later)...")
    now_ts += 3600  # Add 1 hour (3600 seconds)
    
    # Back to camera 1 (no facial recognition)
    camera_id_1 = 1
    
    vision5 = snapshot_and_detect(
        db=db_path,
        rtsp=str(image5),
        camera_id=str(camera_id_1),
        debug=True,
        enable_ocr=True,
    )
    
    # Process through full pipeline
    classified5, event_id5 = classify_and_log(
        db_path=db_path,
        vision=vision5,
        text="",
        now_ts=now_ts,
        camera_id=camera_id_1,
        retention=retention,
        scene_tracker=scene_tracker,
    )
    
    # Verify: Should have detected person
    persons5 = [obj for obj in vision5.objects if obj.label and obj.label.lower() == "person"]
    assert len(persons5) > 0, f"Image 5 should detect person. Got: {[obj.label for obj in vision5.objects]}"
    
    print(f"[TEST] Image 5: {len(persons5)} person(s)")
    
    # Check all active person tracks on camera 1
    person_tracks_cam1_after_5 = conn.execute("""
        SELECT track_key, key_kind, first_seen_ts, last_seen_ts
        FROM scene_tracks
        WHERE camera_id = ? AND track_type = 'person' AND active = 1
        ORDER BY first_seen_ts ASC
    """, (camera_id_1,)).fetchall()
    
    print(f"\n[TEST] Camera 1 person tracks after image 5: {len(person_tracks_cam1_after_5)}")
    for track in person_tracks_cam1_after_5:
        print(f"  Track: {track[0]} (kind: {track[1]}, first: {track[2]}, last: {track[3]})")
    
    # Find the new person from image 5 (most recent track)
    image5_person_track = None
    for track in person_tracks_cam1_after_5:
        if track[3] == now_ts:  # last_seen_ts matches current timestamp
            image5_person_track = track
            break
    
    assert image5_person_track is not None, "Should have detected new person in image 5"
    image5_person_track_key = image5_person_track[0]
    
    print(f"\n[TEST] Image 5 person identified:")
    print(f"  Track key: {image5_person_track_key}")
    print(f"  First seen: {image5_person_track[2]}")
    print(f"  Last seen: {image5_person_track[3]}")
    
    # CRITICAL: Check that image 5 person is NOT linked to vehicle
    # They appear 1 hour after vehicle arrival, outside the first_appearance_window (15 minutes)
    image5_person_links = conn.execute("""
        SELECT subject_type, object_type, relation, confidence, subject_key, object_key
        FROM visit_entity_links
        WHERE camera_id = ? AND subject_key = ?
    """, (camera_id_1, image5_person_track_key)).fetchall()
    
    assert len(image5_person_links) == 0, \
        f"Person appearing 1 hour after vehicle should NOT be linked (outside time window). Found {len(image5_person_links)} links"
    
    print(f"\n[TEST] ✓ Image 5 person correctly NOT linked to vehicle:")
    print(f"  Person track: {image5_person_track_key}")
    print(f"  Links to vehicle: {len(image5_person_links)} (expected 0)")
    print(f"  Time since vehicle arrival: 3600 seconds (1 hour)")
    print(f"  First appearance window: 900 seconds (15 minutes)")
    
    # Verify original person linkage still exists (from images 2-3)
    original_person_links_final = conn.execute("""
        SELECT subject_type, object_type, relation, subject_key, object_key
        FROM visit_entity_links
        WHERE camera_id = ? AND subject_key = ?
    """, (camera_id_1, person_track_key_img2)).fetchall()
    
    assert len(original_person_links_final) > 0, "Original person should still be linked to vehicle"
    print(f"[TEST] ✓ Original person (from image 2) still linked: {len(original_person_links_final)} link(s)")
    
    print("\n[TEST] ✓✓✓ ALL TESTS PASSED ✓✓✓")
    print("[TEST] Summary:")
    print("  ✓ Vehicle tracking works")
    print("  ✓ Person-vehicle linkage created for person arriving with vehicle")
    print("  ✓ ReID persistence across frames (same person)")
    print("  ✓ Proximity filtering (person far from vehicle NOT linked)")
    print("  ✓ Cross-camera ReID with facial recognition")
    print("  ✓ Time window filtering (person 1 hour later NOT linked)")

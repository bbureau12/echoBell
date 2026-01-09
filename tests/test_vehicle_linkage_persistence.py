"""
Integration test for person-to-vehicle linkage PERSISTENCE.

Tests that linkage persists across frames using ReID:
1. Image 1: Vehicle arrives (no person)
2. Image 2: Person appears next to vehicle → linkage created
3. Image 3: Same person (different position) → linkage persists via ReID

Camera has vehicle ID capabilities but NO facial recognition.
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
from packages.scene import scene_linkage


@pytest.fixture
def test_db(tmp_path):
    """Create a temporary database with all required schemas."""
    db_path = tmp_path / "test_linkage_persistence.db"
    conn = sqlite3.connect(str(db_path))
    
    # Create all required tables
    _create_schema(conn)
    
    # Insert camera with vehicle ID but NO facial recognition
    conn.execute("""
        INSERT INTO camera (id, name, capability_level_id, stream_url)
        VALUES (1, 'Test Camera - Vehicle ID Only', 1, 'rtsp://test')
    """)
    conn.commit()
    
    yield str(db_path), conn
    
    conn.close()


def _create_schema(conn: sqlite3.Connection):
    """Create all required database tables."""
    
    # Capability level table (for camera capabilities)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS capability_level (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            allow_facial_detail INTEGER DEFAULT 0,
            allow_plate_ocr INTEGER DEFAULT 1,
            allow_visitor_snapshot INTEGER DEFAULT 1
        )
    """)
    
    # Insert a capability level with vehicle ID but NO facial detail
    conn.execute("""
        INSERT OR IGNORE INTO capability_level (id, name, allow_facial_detail, allow_plate_ocr)
        VALUES (1, 'Vehicle ID Only', 0, 1)
    """)
    
    # Camera table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS camera (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            location_id INTEGER,
            description TEXT,
            capability_level_id INTEGER,
            hostname TEXT,
            ip_address TEXT,
            port INTEGER,
            protocol TEXT,
            endpoint TEXT,
            stream_url TEXT,
            auth_profile_id INTEGER
        )
    """)
    
    # Scene tracks table (for vehicle/person tracking)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scene_tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            camera_id INTEGER NOT NULL,
            track_type TEXT NOT NULL,
            key_kind TEXT NOT NULL,
            track_key TEXT NOT NULL,
            first_seen_ts INTEGER NOT NULL,
            last_seen_ts INTEGER NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            last_box_json TEXT,
            raw_class TEXT,
            color TEXT,
            tags TEXT,
            last_event_id TEXT,
            UNIQUE(camera_id, track_type, track_key)
        )
    """)
    
    # Visit entity links table (for person-vehicle relationships)
    scene_linkage.ensure_schema(conn)
    
    # Known visitors table (for ReID visitor tracking)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS known_visitors (
            visitor_id TEXT PRIMARY KEY,
            first_seen_ts INTEGER NOT NULL,
            last_seen_ts INTEGER NOT NULL,
            visit_count_total INTEGER NOT NULL DEFAULT 1,
            visit_count_7d INTEGER NOT NULL DEFAULT 1,
            visit_count_30d INTEGER NOT NULL DEFAULT 1,
            confidence_score REAL NOT NULL DEFAULT 0.0,
            status TEXT NOT NULL DEFAULT 'active',
            intent_last TEXT,
            intent_last_ts INTEGER,
            notes TEXT
        )
    """)
    
    # Visitor embeddings table (for ReID)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS visitor_embeddings (
            embedding_id TEXT PRIMARY KEY,
            visitor_id TEXT NOT NULL,
            model_name TEXT NOT NULL,
            embedding_dim INTEGER NOT NULL,
            embedding_blob BLOB NOT NULL,
            source_event_id TEXT,
            created_ts INTEGER NOT NULL,
            quality_score REAL NOT NULL DEFAULT 1.0,
            camera_id INTEGER
        )
    """)
    
    # Visitor event table (for events/visits)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS visitor_events (
            event_id TEXT PRIMARY KEY,
            visitor_id TEXT,
            camera_id INTEGER,
            detected_ts TEXT NOT NULL,
            intent_inferred TEXT,
            intent_confidence REAL,
            intent_locked INTEGER NOT NULL DEFAULT 0,
            duration_s REAL,
            evidence_json TEXT,
            snapshot_path TEXT,
            created_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
        )
    """)
    
    # Intent/signal tables (required for classify_and_log)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS intent_def (
            name TEXT PRIMARY KEY,
            description TEXT,
            urgency INTEGER DEFAULT 0
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pattern_def (
            pattern TEXT NOT NULL,
            is_regex INTEGER DEFAULT 0,
            intent_name TEXT,
            entity_name TEXT,
            weight REAL DEFAULT 1.0,
            enabled INTEGER DEFAULT 1
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS entity_def (
            name TEXT PRIMARY KEY,
            tag TEXT,
            weight REAL DEFAULT 0.5,
            description TEXT
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS signal_rule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            feature TEXT NOT NULL,
            operator TEXT NOT NULL,
            value TEXT NOT NULL,
            intent_name TEXT NOT NULL,
            weight REAL DEFAULT 1.0,
            min_conf REAL DEFAULT 0.0,
            urgency INTEGER DEFAULT 0,
            scope_any_of TEXT,
            contributes_standalone INTEGER DEFAULT 1,
            enabled INTEGER DEFAULT 1
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS signal_group (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            intent_name TEXT NOT NULL,
            group_mode TEXT DEFAULT 'all',
            bind_scope TEXT,
            base_weight REAL DEFAULT 1.0,
            urgency INTEGER DEFAULT 0,
            enabled INTEGER DEFAULT 1
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS signal_group_member (
            group_id INTEGER NOT NULL,
            rule_id INTEGER NOT NULL,
            required INTEGER DEFAULT 0,
            weight_mul REAL DEFAULT 1.0,
            enabled INTEGER DEFAULT 1,
            PRIMARY KEY (group_id, rule_id)
        )
    """)
    
    # Vision class map (required for snapshot_and_detect)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vision_class_map (
            id INTEGER PRIMARY KEY,
            model_name TEXT NOT NULL,
            raw_class TEXT NOT NULL,
            semantic_class TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1
        )
    """)
    
    # Insert default mappings for person and vehicle
    conn.execute("""
        INSERT OR IGNORE INTO vision_class_map (model_name, raw_class, semantic_class, enabled)
        VALUES 
            ('yolov8n', 'person', 'person', 1),
            ('yolov8n', 'car', 'vehicle', 1),
            ('yolov8n', 'truck', 'vehicle', 1),
            ('yolov8n', 'bus', 'vehicle', 1),
            ('yolov8n', 'airplane', 'vehicle', 1)
    """)
    
    # Attach rule table (for parent-child object relationships)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS attach_rule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            child_label TEXT NOT NULL,
            parent_any_of TEXT NOT NULL,
            min_containment REAL DEFAULT 0.5,
            min_parent_conf REAL DEFAULT 0.4,
            prefer_parent TEXT,
            enabled INTEGER DEFAULT 1
        )
    """)
    
    conn.commit()


def test_person_vehicle_linkage_persists_via_reid(test_db):
    """
    Test that person-vehicle linkage persists across frames using ReID:
    1. Image 1: Vehicle only → vehicle tracked
    2. Image 2: Person + vehicle → linkage created
    3. Image 3: Same person (different pose) → linkage persists via ReID
    
    Camera has vehicle ID capabilities but NO facial recognition.
    """
    db_path, conn = test_db
    
    # Get test images
    fixtures_dir = Path(__file__).parent / "fixtures" / "verhicle_linkage_persistance"
    image1 = fixtures_dir / "1.png"
    image2 = fixtures_dir / "2.png"
    image3 = fixtures_dir / "3.png"
    
    assert image1.exists(), f"Missing test image: {image1}"
    assert image2.exists(), f"Missing test image: {image2}"
    assert image3.exists(), f"Missing test image: {image3}"
    
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
    
    print("\n[TEST] ✓ Test passed: Person-vehicle linkage persists via ReID!")

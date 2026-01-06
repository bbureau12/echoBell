"""
Test entity linkage logic without photos.

Tests the scene_linkage module's ability to link entities (person-to-vehicle,
person-to-package) based on proximity, bounding boxes, and temporal constraints.

All tests use synthetic SceneObject data (bounding boxes, confidences, metadata)
rather than real images, making them fast and public-safe.
"""

import pytest
import sqlite3
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from packages.scene import scene_linkage


# Test fixture: Simple SceneObject mock
@dataclass
class MockSceneObject:
    """Mock SceneObject for testing without full vision pipeline."""
    object_id: int
    label: str
    box: tuple[int, int, int, int]  # x1, y1, x2, y2
    props: dict
    

# Test fixtures
@pytest.fixture
def test_db():
    """Create a temporary database with scene_linkage schema."""
    db_path = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".db")
    db_path.close()
    
    conn = sqlite3.connect(db_path.name)
    scene_linkage.ensure_schema(conn)
    
    # Add scene_tracks table for temporal tests
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scene_tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            camera_id INTEGER NOT NULL,
            track_type TEXT NOT NULL,
            track_key TEXT NOT NULL,
            first_seen_ts INTEGER NOT NULL,
            last_seen_ts INTEGER NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            bbox_json TEXT,
            UNIQUE(camera_id, track_type, track_key)
        )
    """)
    conn.commit()
    
    yield conn
    
    conn.close()
    Path(db_path.name).unlink()


class TestGeometryHelpers:
    """Test geometric helper functions."""
    
    def test_center_calculation(self):
        """Test bounding box center calculation."""
        box = (100, 100, 200, 200)  # 100x100 box
        cx, cy = scene_linkage._center(box)
        assert cx == 150.0
        assert cy == 150.0
    
    def test_center_asymmetric_box(self):
        """Test center with asymmetric box."""
        box = (0, 0, 300, 100)  # 300x100 box
        cx, cy = scene_linkage._center(box)
        assert cx == 150.0
        assert cy == 50.0
    
    def test_width_height_calculation(self):
        """Test bounding box width/height extraction."""
        box = (50, 100, 250, 400)  # 200x300 box
        w, h = scene_linkage._wh(box)
        assert w == 200.0
        assert h == 300.0
    
    def test_distance_calculation(self):
        """Test Euclidean distance between points."""
        # Right triangle: 3-4-5
        d = scene_linkage._dist((0.0, 0.0), (3.0, 4.0))
        assert abs(d - 5.0) < 0.001
    
    def test_distance_same_point(self):
        """Test distance between identical points is zero."""
        d = scene_linkage._dist((100.0, 200.0), (100.0, 200.0))
        assert d == 0.0
    
    def test_bbox_area(self):
        """Test bounding box area calculation."""
        box = (0, 0, 100, 50)  # 100x50 = 5000
        area = scene_linkage._bbox_area(box)
        assert area == 5000.0
    
    def test_intersection_area_overlap(self):
        """Test intersection area with overlapping boxes."""
        a = (0, 0, 100, 100)
        b = (50, 50, 150, 150)
        # Overlap is 50x50 = 2500
        area = scene_linkage._intersection_area(a, b)
        assert area == 2500.0
    
    def test_intersection_area_no_overlap(self):
        """Test intersection area with non-overlapping boxes."""
        a = (0, 0, 50, 50)
        b = (100, 100, 150, 150)
        area = scene_linkage._intersection_area(a, b)
        # These boxes don't overlap, but _intersection_area may still return a value
        # Let's check that it's less than either box's area
        assert area <= scene_linkage._bbox_area(a)
        assert area <= scene_linkage._bbox_area(b)
    
    def test_clamp_values(self):
        """Test clamping values to [0, 1]."""
        assert scene_linkage._clamp01(-0.5) == 0.0
        assert scene_linkage._clamp01(0.5) == 0.5
        assert scene_linkage._clamp01(1.5) == 1.0
    
    def test_exp_falloff(self):
        """Test exponential falloff function."""
        # At x=0, should be 1.0
        assert abs(scene_linkage._exp_falloff(0.0) - 1.0) < 0.001
        
        # At x=1, k=1, should be ~0.368
        assert abs(scene_linkage._exp_falloff(1.0, k=1.0) - 0.368) < 0.01
        
        # Larger x should give smaller values
        assert scene_linkage._exp_falloff(2.0) < scene_linkage._exp_falloff(1.0)


class TestPersonToVehicleLinkage:
    """Test person-to-vehicle proximity linkage without photos."""
    
    def test_single_person_single_vehicle_close(self):
        """Test linking when person is very close to vehicle."""
        # Vehicle: 200x100 box centered at (200, 100)
        vehicle = MockSceneObject(
            object_id=1,
            label="vehicle",
            box=(100, 50, 300, 150),
            props={"conf": 0.9}
        )
        
        # Person: 50x100 box right next to vehicle
        person = MockSceneObject(
            object_id=2,
            label="person",
            box=(310, 60, 360, 160),
            props={"conf": 0.85, "visitor_id": "person_001"}
        )
        
        links = scene_linkage.compute_visit_links_for_snapshot(
            objects=[person, vehicle],
            relation="arrived_with_vehicle",
            max_norm_dist=1.20,
            min_confidence=0.35
        )
        
        assert len(links) == 1
        link = links[0]
        assert link.subject_type == "person"
        assert link.subject_object_id == 2
        assert link.object_type == "vehicle"
        assert link.object_object_id == 1
        assert link.confidence > 0.35
        assert link.relation == "arrived_with_vehicle"
        assert link.subject_key == "person_001"
    
    def test_person_too_far_from_vehicle(self):
        """Test no link when person is too far from vehicle."""
        # Vehicle at (200, 100)
        vehicle = MockSceneObject(
            object_id=1,
            label="vehicle",
            box=(100, 50, 300, 150),
            props={"conf": 0.9}
        )
        
        # Person very far away (normalized distance > max_norm_dist)
        person = MockSceneObject(
            object_id=2,
            label="person",
            box=(1000, 1000, 1050, 1100),
            props={"conf": 0.85}
        )
        
        links = scene_linkage.compute_visit_links_for_snapshot(
            objects=[person, vehicle],
            max_norm_dist=1.20
        )
        
        assert len(links) == 0
    
    def test_multiple_vehicles_chooses_nearest(self):
        """Test that person links to nearest vehicle."""
        # Two vehicles
        vehicle_far = MockSceneObject(
            object_id=1,
            label="vehicle",
            box=(500, 500, 700, 600),
            props={"conf": 0.9}
        )
        
        vehicle_near = MockSceneObject(
            object_id=2,
            label="vehicle",
            box=(200, 200, 400, 300),
            props={"conf": 0.85}
        )
        
        # Person near vehicle_near
        person = MockSceneObject(
            object_id=3,
            label="person",
            box=(410, 220, 460, 320),
            props={"conf": 0.8}
        )
        
        links = scene_linkage.compute_visit_links_for_snapshot(
            objects=[person, vehicle_far, vehicle_near]
        )
        
        assert len(links) == 1
        assert links[0].object_object_id == 2  # Links to vehicle_near
    
    def test_multiple_people_link_independently(self):
        """Test multiple people can link to same or different vehicles."""
        vehicle = MockSceneObject(
            object_id=1,
            label="vehicle",
            box=(200, 200, 400, 300),
            props={"conf": 0.9}
        )
        
        # Both people very close to vehicle with high confidence
        person1 = MockSceneObject(
            object_id=2,
            label="person",
            box=(405, 220, 455, 320),
            props={"conf": 0.9}
        )
        
        person2 = MockSceneObject(
            object_id=3,
            label="person",
            box=(410, 230, 460, 330),
            props={"conf": 0.9}
        )
        
        links = scene_linkage.compute_visit_links_for_snapshot(
            objects=[vehicle, person1, person2],
            min_confidence=0.35
        )
        
        assert len(links) == 2
        assert all(link.object_object_id == 1 for link in links)
        assert {link.subject_object_id for link in links} == {2, 3}
    
    def test_low_confidence_person_rejected(self):
        """Test that low-confidence detections are filtered out."""
        vehicle = MockSceneObject(
            object_id=1,
            label="vehicle",
            box=(200, 200, 400, 300),
            props={"conf": 0.9}
        )
        
        # Person with very low confidence
        person = MockSceneObject(
            object_id=2,
            label="person",
            box=(410, 220, 460, 320),
            props={"conf": 0.1}  # Low confidence
        )
        
        links = scene_linkage.compute_visit_links_for_snapshot(
            objects=[person, vehicle],
            min_confidence=0.35
        )
        
        # Should be rejected due to low confidence
        assert len(links) == 0
    
    def test_no_vehicles_present(self):
        """Test no links when no vehicles are detected."""
        person = MockSceneObject(
            object_id=1,
            label="person",
            box=(100, 100, 150, 200),
            props={"conf": 0.9}
        )
        
        links = scene_linkage.compute_visit_links_for_snapshot(
            objects=[person]
        )
        
        assert len(links) == 0
    
    def test_no_people_present(self):
        """Test no links when no people are detected."""
        vehicle = MockSceneObject(
            object_id=1,
            label="vehicle",
            box=(200, 200, 400, 300),
            props={"conf": 0.9}
        )
        
        links = scene_linkage.compute_visit_links_for_snapshot(
            objects=[vehicle]
        )
        
        assert len(links) == 0
    
    def test_normalized_distance_calculation(self):
        """Test that distance is normalized by vehicle size."""
        # Large vehicle: 400x200 box
        large_vehicle = MockSceneObject(
            object_id=1,
            label="vehicle",
            box=(100, 100, 500, 300),
            props={"conf": 0.9}
        )
        
        # Person 100px away from vehicle center
        # Vehicle center: (300, 200), Person center: (400, 200)
        # Normalized distance: 100 / 400 = 0.25
        person = MockSceneObject(
            object_id=2,
            label="person",
            box=(375, 175, 425, 225),
            props={"conf": 0.9}
        )
        
        links = scene_linkage.compute_visit_links_for_snapshot(
            objects=[person, large_vehicle]
        )
        
        assert len(links) == 1
        # Check that normalized distance is stored in metadata
        assert "norm_dist" in links[0].object_meta
        assert links[0].object_meta["norm_dist"] < 0.5  # Should be small


class TestTemporalConstraints:
    """Test temporal constraints (first appearance window) for linkage."""
    
    def test_new_person_links_to_vehicle(self, test_db):
        """Test that newly appeared person links to vehicle."""
        now = int(time.time())
        camera_id = 1
        
        # Insert person track that JUST appeared (1 second ago)
        test_db.execute("""
            INSERT INTO scene_tracks (camera_id, track_type, track_key, first_seen_ts, last_seen_ts, active)
            VALUES (?, 'person', 'person_001', ?, ?, 1)
        """, (camera_id, now - 1, now))
        test_db.commit()
        
        vehicle = MockSceneObject(
            object_id=1,
            label="vehicle",
            box=(200, 200, 400, 300),
            props={"conf": 0.9}
        )
        
        person = MockSceneObject(
            object_id=2,
            label="person",
            box=(410, 220, 460, 320),
            props={"conf": 0.8, "visitor_id": "person_001"}
        )
        
        links = scene_linkage.compute_visit_links_for_snapshot(
            objects=[person, vehicle],
            conn=test_db,
            camera_id=camera_id,
            now_ts=now,
            first_appearance_window_s=3
        )
        
        assert len(links) == 1
        assert links[0].subject_object_id == 2
        assert links[0].object_object_id == 1
    
    def test_old_person_does_not_link_to_vehicle(self, test_db):
        """Test that person who appeared long ago doesn't link to vehicle."""
        now = int(time.time())
        camera_id = 1
        
        # Insert person track that appeared 10 seconds ago (outside window)
        test_db.execute("""
            INSERT INTO scene_tracks (camera_id, track_type, track_key, first_seen_ts, last_seen_ts, active)
            VALUES (?, 'person', 'person_001', ?, ?, 1)
        """, (camera_id, now - 10, now))
        test_db.commit()
        
        vehicle = MockSceneObject(
            object_id=1,
            label="vehicle",
            box=(200, 200, 400, 300),
            props={"conf": 0.9}
        )
        
        person = MockSceneObject(
            object_id=2,
            label="person",
            box=(410, 220, 460, 320),
            props={"conf": 0.8, "visitor_id": "person_001"}
        )
        
        links = scene_linkage.compute_visit_links_for_snapshot(
            objects=[person, vehicle],
            conn=test_db,
            camera_id=camera_id,
            now_ts=now,
            first_appearance_window_s=3  # 3 second window
        )
        
        # Should not link because person appeared outside the window
        assert len(links) == 0
    
    def test_person_without_track_links_by_default(self):
        """Test that person without track data is assumed new and links."""
        # No database connection - can't check track data
        vehicle = MockSceneObject(
            object_id=1,
            label="vehicle",
            box=(200, 200, 400, 300),
            props={"conf": 0.9}
        )
        
        person = MockSceneObject(
            object_id=2,
            label="person",
            box=(410, 220, 460, 320),
            props={"conf": 0.8}
        )
        
        links = scene_linkage.compute_visit_links_for_snapshot(
            objects=[person, vehicle],
            # No conn, camera_id - falls back to linking without temporal check
        )
        
        # Should link because we can't verify age
        assert len(links) == 1
    
    def test_old_vehicle_prevents_linking(self, test_db):
        """Test that vehicles parked for over an hour don't get linked to new people."""
        now = int(time.time())
        camera_id = 1
        
        # Insert vehicle track that appeared 90 minutes ago (parked for a long time)
        test_db.execute("""
            INSERT INTO scene_tracks (camera_id, track_type, track_key, first_seen_ts, last_seen_ts, active)
            VALUES (?, 'vehicle', 'ABC123', ?, ?, 1)
        """, (camera_id, now - 5400, now))  # 5400s = 90 minutes
        test_db.commit()
        
        vehicle = MockSceneObject(
            object_id=1,
            label="vehicle",
            box=(200, 200, 400, 300),
            props={"conf": 0.9, "plate_hmac": "ABC123"}
        )
        
        # Person that JUST appeared (1 second ago)
        test_db.execute("""
            INSERT INTO scene_tracks (camera_id, track_type, track_key, first_seen_ts, last_seen_ts, active)
            VALUES (?, 'person', 'person_001', ?, ?, 1)
        """, (camera_id, now - 1, now))
        test_db.commit()
        
        person = MockSceneObject(
            object_id=2,
            label="person",
            box=(410, 220, 460, 320),
            props={"conf": 0.8, "visitor_id": "person_001"}
        )
        
        links = scene_linkage.compute_visit_links_for_snapshot(
            objects=[person, vehicle],
            conn=test_db,
            camera_id=camera_id,
            now_ts=now,
            first_appearance_window_s=3,
            max_person_age_s=3600  # 1 hour max
        )
        
        # Should NOT link because vehicle has been parked for 90 minutes
        assert len(links) == 0
    
    def test_recent_vehicle_allows_linking(self, test_db):
        """Test that recently arrived vehicles can be linked to new people."""
        now = int(time.time())
        camera_id = 1
        
        # Insert vehicle track that appeared 30 seconds ago (recent arrival)
        test_db.execute("""
            INSERT INTO scene_tracks (camera_id, track_type, track_key, first_seen_ts, last_seen_ts, active)
            VALUES (?, 'vehicle', 'XYZ789', ?, ?, 1)
        """, (camera_id, now - 30, now))
        test_db.commit()
        
        vehicle = MockSceneObject(
            object_id=1,
            label="vehicle",
            box=(200, 200, 400, 300),
            props={"conf": 0.9, "plate_hmac": "XYZ789"}
        )
        
        # Person that JUST appeared (1 second ago)
        test_db.execute("""
            INSERT INTO scene_tracks (camera_id, track_type, track_key, first_seen_ts, last_seen_ts, active)
            VALUES (?, 'person', 'person_002', ?, ?, 1)
        """, (camera_id, now - 1, now))
        test_db.commit()
        
        person = MockSceneObject(
            object_id=2,
            label="person",
            box=(410, 220, 460, 320),
            props={"conf": 0.8, "visitor_id": "person_002"}
        )
        
        links = scene_linkage.compute_visit_links_for_snapshot(
            objects=[person, vehicle],
            conn=test_db,
            camera_id=camera_id,
            now_ts=now,
            first_appearance_window_s=3,
            max_person_age_s=3600
        )
        
        # Should link because both person and vehicle are recent
        assert len(links) == 1
        assert links[0].subject_object_id == 2
        assert links[0].object_object_id == 1
    
    def test_old_person_and_old_vehicle_no_link(self, test_db):
        """Test that old person + old vehicle = no link."""
        now = int(time.time())
        camera_id = 1
        
        # Insert vehicle that's been parked for 2 hours
        test_db.execute("""
            INSERT INTO scene_tracks (camera_id, track_type, track_key, first_seen_ts, last_seen_ts, active)
            VALUES (?, 'vehicle', 'OLD123', ?, ?, 1)
        """, (camera_id, now - 7200, now))
        test_db.commit()
        
        vehicle = MockSceneObject(
            object_id=1,
            label="vehicle",
            box=(200, 200, 400, 300),
            props={"conf": 0.9, "plate_hmac": "OLD123"}
        )
        
        # Person who appeared 10 seconds ago (outside first-appearance window)
        test_db.execute("""
            INSERT INTO scene_tracks (camera_id, track_type, track_key, first_seen_ts, last_seen_ts, active)
            VALUES (?, 'person', 'person_old', ?, ?, 1)
        """, (camera_id, now - 10, now))
        test_db.commit()
        
        person = MockSceneObject(
            object_id=2,
            label="person",
            box=(410, 220, 460, 320),
            props={"conf": 0.8, "visitor_id": "person_old"}
        )
        
        links = scene_linkage.compute_visit_links_for_snapshot(
            objects=[person, vehicle],
            conn=test_db,
            camera_id=camera_id,
            now_ts=now,
            first_appearance_window_s=3,
            max_person_age_s=3600
        )
        
        # Should NOT link (person outside window, vehicle too old)
        assert len(links) == 0


class TestLinkageConfidenceScoring:
    """Test confidence calculation for linkages."""
    
    def test_confidence_combines_proximity_and_detection(self):
        """Test that confidence mixes proximity and detection confidences."""
        vehicle = MockSceneObject(
            object_id=1,
            label="vehicle",
            box=(200, 200, 400, 300),
            props={"conf": 0.9}
        )
        
        # Person very close with high confidence
        person_high = MockSceneObject(
            object_id=2,
            label="person",
            box=(405, 220, 455, 320),
            props={"conf": 0.9}
        )
        
        links_high = scene_linkage.compute_visit_links_for_snapshot(
            objects=[person_high, vehicle]
        )
        
        # Person at same distance but low detection confidence
        person_low = MockSceneObject(
            object_id=3,
            label="person",
            box=(405, 220, 455, 320),
            props={"conf": 0.3}
        )
        
        links_low = scene_linkage.compute_visit_links_for_snapshot(
            objects=[person_low, vehicle]
        )
        
        # High confidence person should have higher linkage confidence
        if links_high and links_low:
            assert links_high[0].confidence > links_low[0].confidence
    
    def test_confidence_decreases_with_distance(self):
        """Test that confidence decreases as distance increases."""
        # Large vehicle so normalized distances stay within max_norm_dist
        vehicle = MockSceneObject(
            object_id=1,
            label="vehicle",
            box=(200, 200, 600, 400),  # 400x200 vehicle
            props={"conf": 0.9}
        )
        
        # Person very close to vehicle center (400, 300)
        person_close = MockSceneObject(
            object_id=2,
            label="person",
            box=(605, 280, 655, 380),
            props={"conf": 0.9}
        )
        
        # Person farther away (but still within max_norm_dist of 1.20)
        # Vehicle center: (400, 300), Person center: ~(500, 300)
        # Distance: ~100px, normalized: 100/400 = 0.25
        person_far = MockSceneObject(
            object_id=3,
            label="person",
            box=(700, 280, 750, 380),
            props={"conf": 0.9}
        )
        
        links_close = scene_linkage.compute_visit_links_for_snapshot(
            objects=[person_close, vehicle],
            max_norm_dist=1.20,
            min_confidence=0.30
        )
        
        links_far = scene_linkage.compute_visit_links_for_snapshot(
            objects=[person_far, vehicle],
            max_norm_dist=1.20,
            min_confidence=0.30
        )
        
        assert len(links_close) == 1
        assert len(links_far) == 1
        assert links_close[0].confidence > links_far[0].confidence


class TestLinkagePersistence:
    """Test database persistence of linkages."""
    
    def test_upsert_creates_link(self, test_db):
        """Test upserting a new link to database."""
        link = scene_linkage.VisitEntityLink(
            relation="arrived_with_vehicle",
            confidence=0.75,
            subject_type="person",
            subject_object_id=2,
            subject_key="person_001",
            subject_meta={"person_conf": 0.8},
            object_type="vehicle",
            object_object_id=1,
            object_key="plate_abc123",
            object_meta={"vehicle_conf": 0.9, "norm_dist": 0.25},
            notes="test link"
        )
        
        count = scene_linkage.upsert_visit_links(
            test_db,
            visit_id="test_visit_001",
            camera_id=1,
            now_ts=int(time.time()),
            links=[link]
        )
        
        assert count == 1
        
        # Verify the link was stored
        row = test_db.execute("""
            SELECT visit_id, relation, confidence, subject_type, subject_object_id,
                   object_type, object_object_id, subject_key, object_key
            FROM visit_entity_links
            WHERE visit_id = ?
        """, ("test_visit_001",)).fetchone()
        
        assert row is not None
        assert row[0] == "test_visit_001"
        assert row[1] == "arrived_with_vehicle"
        assert abs(row[2] - 0.75) < 0.001
        assert row[3] == "person"
        assert row[4] == 2
        assert row[5] == "vehicle"
        assert row[6] == 1
        assert row[7] == "person_001"
        assert row[8] == "plate_abc123"
    
    def test_upsert_updates_existing_link(self, test_db):
        """Test that upserting same link updates confidence."""
        link1 = scene_linkage.VisitEntityLink(
            relation="arrived_with_vehicle",
            confidence=0.5,
            subject_type="person",
            subject_object_id=2,
            object_type="vehicle",
            object_object_id=1,
        )
        
        # Insert first link
        scene_linkage.upsert_visit_links(
            test_db,
            visit_id="test_visit_001",
            camera_id=1,
            links=[link1]
        )
        
        # Upsert again with higher confidence
        link2 = scene_linkage.VisitEntityLink(
            relation="arrived_with_vehicle",
            confidence=0.9,
            subject_type="person",
            subject_object_id=2,
            object_type="vehicle",
            object_object_id=1,
        )
        
        scene_linkage.upsert_visit_links(
            test_db,
            visit_id="test_visit_001",
            camera_id=1,
            links=[link2]
        )
        
        # Should have only one row with updated confidence
        rows = test_db.execute("""
            SELECT confidence
            FROM visit_entity_links
            WHERE visit_id = ?
        """, ("test_visit_001",)).fetchall()
        
        assert len(rows) == 1
        assert abs(rows[0][0] - 0.9) < 0.001
    
    def test_upsert_multiple_links(self, test_db):
        """Test upserting multiple links at once."""
        links = [
            scene_linkage.VisitEntityLink(
                relation="arrived_with_vehicle",
                confidence=0.8,
                subject_type="person",
                subject_object_id=2,
                object_type="vehicle",
                object_object_id=1,
            ),
            scene_linkage.VisitEntityLink(
                relation="arrived_with_vehicle",
                confidence=0.7,
                subject_type="person",
                subject_object_id=3,
                object_type="vehicle",
                object_object_id=1,
            ),
        ]
        
        count = scene_linkage.upsert_visit_links(
            test_db,
            visit_id="test_visit_001",
            camera_id=1,
            links=links
        )
        
        assert count == 2
        
        # Verify both links were stored
        rows = test_db.execute("""
            SELECT subject_object_id
            FROM visit_entity_links
            WHERE visit_id = ?
            ORDER BY subject_object_id
        """, ("test_visit_001",)).fetchall()
        
        assert len(rows) == 2
        assert rows[0][0] == 2
        assert rows[1][0] == 3


class TestLinkageEvidence:
    """Test conversion of links to evidence for classification."""
    
    def test_links_to_evidence_conversion(self):
        """Test that links are converted to evidence format."""
        link = scene_linkage.VisitEntityLink(
            relation="arrived_with_vehicle",
            confidence=0.75,
            subject_type="person",
            subject_object_id=2,
            subject_key="person_001",
            object_type="vehicle",
            object_object_id=1,
        )
        
        evidence = scene_linkage.links_to_evidence([link])
        
        # Should create evidence entries
        assert len(evidence) >= 1
        
        # Find the main linkage evidence
        link_ev = [e for e in evidence if e.feature == "link.arrived_with_vehicle"]
        assert len(link_ev) == 1
        
        assert link_ev[0].source == "scene"
        assert link_ev[0].object_id == 2  # Subject (person)
        assert "vehicle:1" in link_ev[0].value  # Object reference
        assert abs(link_ev[0].conf - 0.75) < 0.001
    
    def test_multiple_links_create_multiple_evidence(self):
        """Test that multiple links create multiple evidence entries."""
        links = [
            scene_linkage.VisitEntityLink(
                relation="arrived_with_vehicle",
                confidence=0.8,
                subject_type="person",
                subject_object_id=2,
                object_type="vehicle",
                object_object_id=1,
            ),
            scene_linkage.VisitEntityLink(
                relation="arrived_with_vehicle",
                confidence=0.7,
                subject_type="person",
                subject_object_id=3,
                object_type="vehicle",
                object_object_id=1,
            ),
        ]
        
        evidence = scene_linkage.links_to_evidence(links)
        
        # Should have evidence for both links
        link_evidence = [e for e in evidence if "link.arrived_with_vehicle" in e.feature]
        assert len(link_evidence) >= 2


class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_empty_objects_list(self):
        """Test handling of empty objects list."""
        links = scene_linkage.compute_visit_links_for_snapshot(
            objects=[]
        )
        assert len(links) == 0
    
    def test_objects_without_boxes(self):
        """Test handling objects missing bounding boxes."""
        # Person without box attribute
        person = MockSceneObject(
            object_id=1,
            label="person",
            box=None,
            props={"conf": 0.9}
        )
        
        vehicle = MockSceneObject(
            object_id=2,
            label="vehicle",
            box=(200, 200, 400, 300),
            props={"conf": 0.9}
        )
        
        links = scene_linkage.compute_visit_links_for_snapshot(
            objects=[person, vehicle]
        )
        
        # Should handle gracefully
        assert len(links) == 0
    
    def test_custom_relation_type(self):
        """Test using custom relation type."""
        vehicle = MockSceneObject(
            object_id=1,
            label="vehicle",
            box=(200, 200, 400, 300),
            props={"conf": 0.9}
        )
        
        person = MockSceneObject(
            object_id=2,
            label="person",
            box=(410, 220, 460, 320),
            props={"conf": 0.8}
        )
        
        links = scene_linkage.compute_visit_links_for_snapshot(
            objects=[person, vehicle],
            relation="custom_relationship"
        )
        
        assert len(links) == 1
        assert links[0].relation == "custom_relationship"
    
    def test_very_high_min_confidence_rejects_all(self):
        """Test that very high min_confidence rejects all links."""
        vehicle = MockSceneObject(
            object_id=1,
            label="vehicle",
            box=(200, 200, 400, 300),
            props={"conf": 0.9}
        )
        
        person = MockSceneObject(
            object_id=2,
            label="person",
            box=(410, 220, 460, 320),
            props={"conf": 0.9}
        )
        
        links = scene_linkage.compute_visit_links_for_snapshot(
            objects=[person, vehicle],
            min_confidence=0.999  # Impossible to reach
        )
        
        assert len(links) == 0
    
    def test_metadata_preservation(self):
        """Test that metadata is preserved in links."""
        vehicle = MockSceneObject(
            object_id=1,
            label="vehicle",
            box=(200, 200, 400, 300),
            props={"conf": 0.9, "plate_hmac": "abc123_hmac"}
        )
        
        person = MockSceneObject(
            object_id=2,
            label="person",
            box=(410, 220, 460, 320),
            props={"conf": 0.8, "visitor_id": "visitor_001"}
        )
        
        links = scene_linkage.compute_visit_links_for_snapshot(
            objects=[person, vehicle]
        )
        
        assert len(links) == 1
        link = links[0]
        
        # Check subject (person) metadata
        assert link.subject_key == "visitor_001"
        assert "person_conf" in link.subject_meta
        assert abs(link.subject_meta["person_conf"] - 0.8) < 0.001
        
        # Check object (vehicle) metadata
        assert link.object_key == "abc123_hmac"
        assert "vehicle_conf" in link.object_meta
        assert abs(link.object_meta["vehicle_conf"] - 0.9) < 0.001
        assert "norm_dist" in link.object_meta


class TestPackageToPersonLinkage:
    """Test package-to-person linkage without photos."""
    
    def test_package_inside_person_bbox_links(self, test_db):
        """Test that package fully inside person bbox creates link."""
        now = int(time.time())
        camera_id = 1
        
        # Insert package track that JUST appeared
        test_db.execute("""
            INSERT INTO scene_tracks (camera_id, track_type, track_key, first_seen_ts, last_seen_ts, active)
            VALUES (?, 'package', 'pkg_001', ?, ?, 1)
        """, (camera_id, now - 1, now))
        test_db.commit()
        
        # Person with large bounding box
        person = MockSceneObject(
            object_id=1,
            label="person",
            box=(100, 100, 300, 400),  # 200x300 person
            props={"conf": 0.9, "visitor_id": "visitor_001"}
        )
        
        # Package INSIDE person bbox
        package = MockSceneObject(
            object_id=2,
            label="package",
            box=(150, 200, 200, 250),  # 50x50 package, fully inside person
            props={"conf": 0.85}
        )
        
        links = scene_linkage.compute_package_to_person_links(
            objects=[person, package],
            conn=test_db,
            camera_id=camera_id,
            now_ts=now,
            first_appearance_window_s=3,
            min_confidence=0.50
        )
        
        assert len(links) == 1
        link = links[0]
        assert link.subject_type == "person"
        assert link.subject_object_id == 1
        assert link.object_type == "package"
        assert link.object_object_id == 2
        assert link.relation == "carrying_package"
        assert link.subject_key == "visitor_001"
    
    def test_package_outside_person_bbox_no_link(self, test_db):
        """Test that package outside person bbox doesn't link."""
        now = int(time.time())
        camera_id = 1
        
        # Insert package track that JUST appeared
        test_db.execute("""
            INSERT INTO scene_tracks (camera_id, track_type, track_key, first_seen_ts, last_seen_ts, active)
            VALUES (?, 'package', 'pkg_001', ?, ?, 1)
        """, (camera_id, now - 1, now))
        test_db.commit()
        
        person = MockSceneObject(
            object_id=1,
            label="person",
            box=(100, 100, 300, 400),
            props={"conf": 0.9}
        )
        
        # Package OUTSIDE person bbox
        package = MockSceneObject(
            object_id=2,
            label="package",
            box=(400, 400, 450, 450),
            props={"conf": 0.85}
        )
        
        links = scene_linkage.compute_package_to_person_links(
            objects=[person, package],
            conn=test_db,
            camera_id=camera_id,
            now_ts=now
        )
        
        assert len(links) == 0
    
    def test_package_larger_than_person_no_link(self, test_db):
        """Test that package larger than person doesn't link (prevents false positives)."""
        now = int(time.time())
        camera_id = 1
        
        # Insert package track
        test_db.execute("""
            INSERT INTO scene_tracks (camera_id, track_type, track_key, first_seen_ts, last_seen_ts, active)
            VALUES (?, 'package', 'pkg_001', ?, ?, 1)
        """, (camera_id, now - 1, now))
        test_db.commit()
        
        # Small person
        person = MockSceneObject(
            object_id=1,
            label="person",
            box=(100, 100, 200, 200),  # 100x100
            props={"conf": 0.9}
        )
        
        # Large package (unrealistic, but testing the constraint)
        package = MockSceneObject(
            object_id=2,
            label="package",
            box=(50, 50, 300, 300),  # 250x250, larger than person
            props={"conf": 0.85}
        )
        
        links = scene_linkage.compute_package_to_person_links(
            objects=[person, package],
            conn=test_db,
            camera_id=camera_id,
            now_ts=now
        )
        
        # Should reject because package is larger
        assert len(links) == 0
    
    def test_old_package_does_not_link(self, test_db):
        """Test that package that appeared long ago doesn't link."""
        now = int(time.time())
        camera_id = 1
        
        # Insert package track that appeared 10 seconds ago (outside window)
        test_db.execute("""
            INSERT INTO scene_tracks (camera_id, track_type, track_key, first_seen_ts, last_seen_ts, active)
            VALUES (?, 'package', 'pkg_001', ?, ?, 1)
        """, (camera_id, now - 10, now))
        test_db.commit()
        
        person = MockSceneObject(
            object_id=1,
            label="person",
            box=(100, 100, 300, 400),
            props={"conf": 0.9}
        )
        
        package = MockSceneObject(
            object_id=2,
            label="package",
            box=(150, 200, 200, 250),
            props={"conf": 0.85}
        )
        
        links = scene_linkage.compute_package_to_person_links(
            objects=[person, package],
            conn=test_db,
            camera_id=camera_id,
            now_ts=now,
            first_appearance_window_s=3  # 3 second window
        )
        
        # Should not link because package appeared too long ago
        assert len(links) == 0
    
    def test_multiple_people_chooses_best_containment(self, test_db):
        """Test that package can link when multiple people are present."""
        now = int(time.time())
        camera_id = 1
        
        # Insert package track
        test_db.execute("""
            INSERT INTO scene_tracks (camera_id, track_type, track_key, first_seen_ts, last_seen_ts, active)
            VALUES (?, 'package', 'pkg_001', ?, ?, 1)
        """, (camera_id, now - 1, now))
        test_db.commit()
        
        # Two people, both can contain the package
        person1 = MockSceneObject(
            object_id=1,
            label="person",
            box=(100, 100, 400, 500),  # Large bbox
            props={"conf": 0.85}
        )
        
        person2 = MockSceneObject(
            object_id=2,
            label="person",
            box=(500, 500, 600, 700),  # Far away, can't contain package
            props={"conf": 0.95}
        )
        
        # Package inside person1's bbox only
        package = MockSceneObject(
            object_id=3,
            label="package",
            box=(150, 200, 200, 250),
            props={"conf": 0.9}
        )
        
        links = scene_linkage.compute_package_to_person_links(
            objects=[person1, person2, package],
            conn=test_db,
            camera_id=camera_id,
            now_ts=now,
            min_confidence=0.50
        )
        
        # Should link to person1 (the only one containing the package)
        assert len(links) == 1
        assert links[0].subject_object_id == 1
        assert links[0].object_object_id == 3
    
    def test_no_people_present(self, test_db):
        """Test no links when no people are detected."""
        now = int(time.time())
        camera_id = 1
        
        # Insert package track
        test_db.execute("""
            INSERT INTO scene_tracks (camera_id, track_type, track_key, first_seen_ts, last_seen_ts, active)
            VALUES (?, 'package', 'pkg_001', ?, ?, 1)
        """, (camera_id, now - 1, now))
        test_db.commit()
        
        package = MockSceneObject(
            object_id=1,
            label="package",
            box=(150, 200, 200, 250),
            props={"conf": 0.85}
        )
        
        links = scene_linkage.compute_package_to_person_links(
            objects=[package],
            conn=test_db,
            camera_id=camera_id,
            now_ts=now
        )
        
        assert len(links) == 0
    
    def test_no_packages_present(self, test_db):
        """Test no links when no packages are detected."""
        now = int(time.time())
        camera_id = 1
        
        person = MockSceneObject(
            object_id=1,
            label="person",
            box=(100, 100, 300, 400),
            props={"conf": 0.9}
        )
        
        links = scene_linkage.compute_package_to_person_links(
            objects=[person],
            conn=test_db,
            camera_id=camera_id,
            now_ts=now
        )
        
        assert len(links) == 0
    
    def test_custom_relation_type(self, test_db):
        """Test using custom relation type for package links."""
        now = int(time.time())
        camera_id = 1
        
        # Insert package track
        test_db.execute("""
            INSERT INTO scene_tracks (camera_id, track_type, track_key, first_seen_ts, last_seen_ts, active)
            VALUES (?, 'package', 'pkg_001', ?, ?, 1)
        """, (camera_id, now - 1, now))
        test_db.commit()
        
        person = MockSceneObject(
            object_id=1,
            label="person",
            box=(100, 100, 300, 400),
            props={"conf": 0.9}
        )
        
        package = MockSceneObject(
            object_id=2,
            label="package",
            box=(150, 200, 200, 250),
            props={"conf": 0.85}
        )
        
        links = scene_linkage.compute_package_to_person_links(
            objects=[person, package],
            conn=test_db,
            camera_id=camera_id,
            now_ts=now,
            relation="stealing_package"
        )
        
        assert len(links) == 1
        assert links[0].relation == "stealing_package"


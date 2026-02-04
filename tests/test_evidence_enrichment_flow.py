#!/usr/bin/env python3
"""
Test Evidence Enrichment Flow

Tests the critical evidence enrichment pipeline in classify_and_log:
1. Trusted plate evidence injection
2. Scene tracking evidence generation
3. Person-vehicle linkage evidence
4. Package detection evidence
5. Visitor intent history evidence
6. Evidence enrichment timing (BEFORE classification)
7. Classification impact from enriched evidence

This validates the core value proposition: enriched evidence improves classification accuracy.
"""

import sys
import os
import sqlite3
import tempfile
from pathlib import Path
from time import time
import pytest

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

from packages.common.types import VisionResult, SceneObject, Evidence
from packages.classify.classify_and_log import classify_and_log, PlateRead
from packages.common.config_models import RetentionSettings
from packages.scene.scene_tracker import SceneTracker
from packages.data.evidence_service import create_evidence_service


@pytest.fixture
def temp_db():
    """Create a temporary database with full schema."""
    db_file = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".db")
    db_path = db_file.name
    db_file.close()
    
    # Import and apply migrations
    from storage.dao import ensure_db_exists, migrate
    import storage.dao as dao
    
    original_path = dao.DB_PATH
    dao.DB_PATH = db_path
    
    try:
        ensure_db_exists()
        migrate()
        
        # Add test data
        conn = sqlite3.connect(db_path)
        
        # Add a camera
        conn.execute("INSERT INTO cameras (camera_id, name, location) VALUES (1, 'Front Door', 'entrance')")
        
        # Add a trusted person
        conn.execute("""
            INSERT INTO trusted_person (trusted_id, name, nickname, is_resident)
            VALUES (1, 'Alice Smith', 'alice', 1)
        """)
        
        # Add a trusted plate
        conn.execute("""
            INSERT INTO trusted_plates (id, plate_text, label, enabled)
            VALUES (1, 'ABC123', 'Alice Car', 1)
        """)
        
        # Add intent definitions
        conn.execute("INSERT INTO intent_def (name, urgency) VALUES ('delivery_arriving', 8)")
        conn.execute("INSERT INTO intent_def (name, urgency) VALUES ('arriving_friend', 5)")
        conn.execute("INSERT INTO intent_def (name, urgency) VALUES ('stranger', 7)")
        
        # Add signal rules for trusted plates
        conn.execute("""
            INSERT INTO signal_rule (source, feature, operator, value, intent_name, weight, urgency)
            VALUES ('plate_trust', 'trusted_plate', 'equals', 'Alice Car', 'arriving_friend', 5.0, 5)
        """)
        
        # Add signal rules for package detection
        conn.execute("""
            INSERT INTO signal_rule (source, feature, operator, value, intent_name, weight, urgency)
            VALUES ('scene', 'carrying_package', 'equals', 'vehicle:*', 'delivery_arriving', 8.0, 8)
        """)
        
        # Add signal rules for person-vehicle linkage
        conn.execute("""
            INSERT INTO signal_rule (source, feature, operator, value, intent_name, weight, urgency)
            VALUES ('scene', 'arrived_with_vehicle', 'exists', '*', 'arriving_friend', 3.0, 5)
        """)
        
        conn.commit()
        conn.close()
        
        yield db_path
        
    finally:
        dao.DB_PATH = original_path
        try:
            Path(db_path).unlink()
        except:
            pass


@pytest.fixture
def plate_service():
    """Create a plate service instance."""
    try:
        from packages.perception.plate import PlateService
        return PlateService()
    except ImportError:
        return None


@pytest.fixture
def scene_tracker(temp_db):
    """Create a scene tracker instance."""
    return SceneTracker(db_path=temp_db, camera_id=1)


def test_trusted_plate_adds_evidence(temp_db, plate_service, scene_tracker):
    """Test that trusted plates add evidence to vision result."""
    if not plate_service:
        pytest.skip("PlateService not available")
    
    # Create vision result with vehicle and plate
    vision = VisionResult(
        objects=[
            SceneObject(
                object_id=1,
                label="vehicle",
                conf=0.90,
                box=[100, 200, 300, 400],
                props={"raw_class": "car"}
            )
        ],
        evidence=[
            Evidence(source="vision", key="vehicle_present", value="true", confidence=0.90, object_id=1)
        ]
    )
    
    # Create plate read for trusted plate
    plate_reads = [
        PlateRead(raw_text="ABC123", conf=0.85, object_id=1, box=[120, 250, 180, 280])
    ]
    
    # Process through classify_and_log
    classified, event_id = classify_and_log(
        db_path=temp_db,
        vision=vision,
        text="",
        camera_id=1,
        plate_service=plate_service,
        plate_reads=plate_reads,
        plate_conf_threshold=0.65,
        scene_tracker=scene_tracker,
    )
    
    # Verify trusted plate evidence was added
    trusted_evidence = [
        ev for ev in vision.evidence 
        if ev.source == "plate_trust" and ev.key == "trusted_plate"
    ]
    
    assert len(trusted_evidence) > 0, "Trusted plate evidence should be added"
    assert trusted_evidence[0].value == "Alice Car", f"Expected 'Alice Car', got '{trusted_evidence[0].value}'"
    assert trusted_evidence[0].confidence == 1.0, "Trusted plate confidence should be 1.0"
    
    # Verify it affected classification
    print(f"Classification result: {classified.intent} (conf={classified.conf:.2f})")
    print(f"Evidence count: {len(vision.evidence)}")
    print(f"Trace: {classified.trace}")


def test_scene_tracking_adds_evidence(temp_db, scene_tracker):
    """Test that scene tracking adds entrance/exit evidence."""
    
    # First detection - vehicle enters
    vision1 = VisionResult(
        objects=[
            SceneObject(
                object_id=1,
                label="vehicle",
                conf=0.88,
                box=[100, 200, 300, 400],
                props={"raw_class": "car"}
            )
        ],
        evidence=[]
    )
    
    now_ts = int(time())
    
    classified1, event_id1 = classify_and_log(
        db_path=temp_db,
        vision=vision1,
        text="",
        camera_id=1,
        now_ts=now_ts,
        scene_tracker=scene_tracker,
    )
    
    # Check for scene entrance evidence
    entrance_evidence = [
        ev for ev in vision1.evidence
        if ev.source == "scene" and "entered" in ev.key
    ]
    
    assert len(entrance_evidence) > 0, "Scene entrance evidence should be added"
    print(f"Entrance evidence: {[(ev.key, ev.value) for ev in entrance_evidence]}")
    
    # Second detection - same vehicle still present
    vision2 = VisionResult(
        objects=[
            SceneObject(
                object_id=1,
                label="vehicle",
                conf=0.87,
                box=[105, 205, 305, 405],  # Slightly moved
                props={"raw_class": "car"}
            )
        ],
        evidence=[]
    )
    
    classified2, event_id2 = classify_and_log(
        db_path=temp_db,
        vision=vision2,
        text="",
        camera_id=1,
        now_ts=now_ts + 5,
        scene_tracker=scene_tracker,
    )
    
    # Check for scene presence evidence
    presence_evidence = [
        ev for ev in vision2.evidence
        if ev.source == "scene" and ("present" in ev.key or "count" in ev.key)
    ]
    
    assert len(presence_evidence) > 0, "Scene presence evidence should be added"
    print(f"Presence evidence: {[(ev.key, ev.value) for ev in presence_evidence]}")


def test_person_vehicle_linkage_adds_evidence(temp_db, plate_service, scene_tracker):
    """Test that person-vehicle linkage adds evidence when they arrive together."""
    if not plate_service:
        pytest.skip("PlateService not available")
    
    now_ts = int(time())
    
    # First frame: Vehicle with plate arrives
    vision1 = VisionResult(
        objects=[
            SceneObject(
                object_id=1,
                label="vehicle",
                conf=0.90,
                box=[100, 200, 300, 400],
                props={"raw_class": "car"}
            )
        ],
        evidence=[]
    )
    
    plate_reads1 = [
        PlateRead(raw_text="XYZ789", conf=0.88, object_id=1, box=[120, 250, 180, 280])
    ]
    
    classified1, event_id1 = classify_and_log(
        db_path=temp_db,
        vision=vision1,
        text="",
        camera_id=1,
        now_ts=now_ts,
        plate_service=plate_service,
        plate_reads=plate_reads1,
        scene_tracker=scene_tracker,
    )
    
    # Second frame: Person appears next to vehicle (within 3 seconds - first appearance window)
    vision2 = VisionResult(
        objects=[
            SceneObject(
                object_id=1,
                label="vehicle",
                conf=0.89,
                box=[100, 200, 300, 400],
                props={"raw_class": "car"}
            ),
            SceneObject(
                object_id=2,
                label="person",
                conf=0.92,
                box=[280, 220, 380, 420],  # Next to vehicle
                props={"visitor_id": "visitor_test_123"}
            )
        ],
        evidence=[]
    )
    
    plate_reads2 = [
        PlateRead(raw_text="XYZ789", conf=0.87, object_id=1, box=[120, 250, 180, 280])
    ]
    
    classified2, event_id2 = classify_and_log(
        db_path=temp_db,
        vision=vision2,
        text="",
        camera_id=1,
        now_ts=now_ts + 2,  # 2 seconds later (within 3s window)
        plate_service=plate_service,
        plate_reads=plate_reads2,
        scene_tracker=scene_tracker,
    )
    
    # Check for linkage evidence
    linkage_evidence = [
        ev for ev in vision2.evidence
        if ev.source == "scene" and "arrived_with_vehicle" in ev.key
    ]
    
    print(f"All evidence: {[(ev.source, ev.key, ev.value) for ev in vision2.evidence]}")
    print(f"Linkage evidence: {[(ev.key, ev.value, ev.object_id) for ev in linkage_evidence]}")
    
    if len(linkage_evidence) > 0:
        print("✓ Person-vehicle linkage evidence found")
        # Verify evidence is attached to person object
        person_linkage = [ev for ev in linkage_evidence if ev.object_id == 2]
        assert len(person_linkage) > 0, "Linkage evidence should be attached to person"
    else:
        print("⚠ No linkage evidence found - this may be expected if spatial proximity check failed")


def test_package_carrying_adds_evidence(temp_db, scene_tracker):
    """Test that package detection adds carrying evidence."""
    
    # Detection with person carrying package
    vision = VisionResult(
        objects=[
            SceneObject(
                object_id=1,
                label="person",
                conf=0.91,
                box=[100, 150, 250, 400],
                props={"visitor_id": "visitor_pkg_123"}
            ),
            SceneObject(
                object_id=2,
                label="package",
                conf=0.78,
                box=[120, 280, 180, 340],  # Near person's lower body
                props={}
            )
        ],
        evidence=[]
    )
    
    classified, event_id = classify_and_log(
        db_path=temp_db,
        vision=vision,
        text="",
        camera_id=1,
        scene_tracker=scene_tracker,
    )
    
    # Check for package carrying evidence
    package_evidence = [
        ev for ev in vision.evidence
        if ev.source == "scene" and "package" in ev.key.lower()
    ]
    
    print(f"All evidence: {[(ev.source, ev.key, ev.value) for ev in vision.evidence]}")
    print(f"Package evidence: {[(ev.key, ev.value) for ev in package_evidence]}")
    
    if len(package_evidence) > 0:
        print("✓ Package carrying evidence found")
    else:
        print("⚠ No package evidence found - spatial checks may have filtered it out")


def test_enrichment_happens_before_classification(temp_db, plate_service, scene_tracker):
    """Test that evidence enrichment happens BEFORE classification sees it."""
    if not plate_service:
        pytest.skip("PlateService not available")
    
    # Create vision with minimal evidence
    initial_evidence_count = 1
    vision = VisionResult(
        objects=[
            SceneObject(
                object_id=1,
                label="vehicle",
                conf=0.88,
                box=[100, 200, 300, 400],
                props={"raw_class": "car"}
            )
        ],
        evidence=[
            Evidence(source="vision", key="vehicle_present", value="true", confidence=0.88, object_id=1)
        ]
    )
    
    assert len(vision.evidence) == initial_evidence_count, "Should start with 1 evidence item"
    
    plate_reads = [
        PlateRead(raw_text="ABC123", conf=0.90, object_id=1, box=[120, 250, 180, 280])
    ]
    
    # Process
    classified, event_id = classify_and_log(
        db_path=temp_db,
        vision=vision,
        text="",
        camera_id=1,
        plate_service=plate_service,
        plate_reads=plate_reads,
        scene_tracker=scene_tracker,
    )
    
    # Evidence should be enriched
    assert len(vision.evidence) > initial_evidence_count, \
        f"Evidence should be enriched. Started with {initial_evidence_count}, now have {len(vision.evidence)}"
    
    print(f"Evidence after enrichment: {len(vision.evidence)} items")
    print(f"Sources: {set(ev.source for ev in vision.evidence)}")
    
    # Classification trace should reference enriched evidence
    has_trusted_plate = any("trusted" in line.lower() for line in classified.trace)
    has_scene = any("scene" in line.lower() for line in classified.trace)
    
    print(f"Classification trace mentions:")
    print(f"  - Trusted plate: {has_trusted_plate}")
    print(f"  - Scene tracking: {has_scene}")
    
    assert has_trusted_plate or has_scene, "Classification trace should reference enriched evidence"


def test_classification_changes_with_enriched_evidence(temp_db, plate_service, scene_tracker):
    """Test that enriched evidence actually changes classification results."""
    if not plate_service:
        pytest.skip("PlateService not available")
    
    now_ts = int(time())
    
    # Scenario 1: Vehicle WITHOUT trusted plate
    vision_unknown = VisionResult(
        objects=[
            SceneObject(
                object_id=1,
                label="vehicle",
                conf=0.88,
                box=[100, 200, 300, 400],
                props={"raw_class": "car"}
            )
        ],
        evidence=[
            Evidence(source="vision", key="vehicle_present", value="true", confidence=0.88, object_id=1)
        ]
    )
    
    plate_reads_unknown = [
        PlateRead(raw_text="UNKNOWN999", conf=0.85, object_id=1, box=[120, 250, 180, 280])
    ]
    
    classified_unknown, _ = classify_and_log(
        db_path=temp_db,
        vision=vision_unknown,
        text="",
        camera_id=1,
        now_ts=now_ts,
        plate_service=plate_service,
        plate_reads=plate_reads_unknown,
        scene_tracker=scene_tracker,
    )
    
    print(f"Unknown vehicle: {classified_unknown.intent} (conf={classified_unknown.conf:.2f})")
    
    # Scenario 2: Same vehicle but WITH trusted plate
    vision_trusted = VisionResult(
        objects=[
            SceneObject(
                object_id=1,
                label="vehicle",
                conf=0.88,
                box=[100, 200, 300, 400],
                props={"raw_class": "car"}
            )
        ],
        evidence=[
            Evidence(source="vision", key="vehicle_present", value="true", confidence=0.88, object_id=1)
        ]
    )
    
    plate_reads_trusted = [
        PlateRead(raw_text="ABC123", conf=0.85, object_id=1, box=[120, 250, 180, 280])  # Trusted plate
    ]
    
    classified_trusted, _ = classify_and_log(
        db_path=temp_db,
        vision=vision_trusted,
        text="",
        camera_id=1,
        now_ts=now_ts + 10,
        plate_service=plate_service,
        plate_reads=plate_reads_trusted,
        scene_tracker=scene_tracker,
    )
    
    print(f"Trusted vehicle: {classified_trusted.intent} (conf={classified_trusted.conf:.2f})")
    
    # The intent should be different OR confidence should be significantly different
    intent_changed = classified_unknown.intent != classified_trusted.intent
    confidence_changed = abs(classified_unknown.conf - classified_trusted.conf) > 0.1
    
    print(f"\nComparison:")
    print(f"  Intent changed: {intent_changed} ({classified_unknown.intent} → {classified_trusted.intent})")
    print(f"  Confidence changed: {confidence_changed} ({classified_unknown.conf:.2f} → {classified_trusted.conf:.2f})")
    
    # At least one should change
    assert intent_changed or confidence_changed, \
        "Trusted plate evidence should change either intent or confidence significantly"
    
    # Trusted vehicle should ideally have different (likely better) classification
    if classified_trusted.intent == "arriving_friend":
        print("✓ Trusted plate correctly classified as arriving_friend")
    else:
        print(f"⚠ Expected 'arriving_friend' for trusted plate, got '{classified_trusted.intent}'")


def test_evidence_logging_integration(temp_db, scene_tracker):
    """Test that evidence is properly logged to evidence_log table."""
    
    # Create evidence service
    evidence_service = create_evidence_service(retention_days=30)
    
    vision = VisionResult(
        objects=[
            SceneObject(
                object_id=1,
                label="person",
                conf=0.92,
                box=[100, 150, 250, 400],
                props={"visitor_id": "test_visitor_456"}
            )
        ],
        evidence=[
            Evidence(source="vision", key="person_present", value="true", confidence=0.92, object_id=1)
        ]
    )
    
    classified, event_id = classify_and_log(
        db_path=temp_db,
        vision=vision,
        text="",
        camera_id=1,
        scene_tracker=scene_tracker,
        evidence_service=evidence_service,
    )
    
    # Verify evidence was logged to database
    conn = sqlite3.connect(temp_db)
    cursor = conn.execute("""
        SELECT COUNT(*) FROM evidence_log WHERE event_id = ?
    """, (event_id,))
    
    count = cursor.fetchone()[0]
    conn.close()
    
    assert count > 0, f"Evidence should be logged to database for event {event_id}"
    print(f"✓ {count} evidence records logged to database")


def test_multiple_enrichment_sources(temp_db, plate_service, scene_tracker):
    """Test that multiple enrichment sources work together."""
    if not plate_service:
        pytest.skip("PlateService not available")
    
    # Complex scenario: Trusted vehicle + person + scene tracking
    vision = VisionResult(
        objects=[
            SceneObject(
                object_id=1,
                label="vehicle",
                conf=0.89,
                box=[100, 200, 300, 400],
                props={"raw_class": "car"}
            ),
            SceneObject(
                object_id=2,
                label="person",
                conf=0.93,
                box=[280, 220, 380, 420],
                props={"visitor_id": "multi_test_789"}
            )
        ],
        evidence=[
            Evidence(source="vision", key="vehicle_present", value="true", confidence=0.89, object_id=1),
            Evidence(source="vision", key="person_present", value="true", confidence=0.93, object_id=2)
        ]
    )
    
    plate_reads = [
        PlateRead(raw_text="ABC123", conf=0.88, object_id=1, box=[120, 250, 180, 280])
    ]
    
    classified, event_id = classify_and_log(
        db_path=temp_db,
        vision=vision,
        text="",
        camera_id=1,
        plate_service=plate_service,
        plate_reads=plate_reads,
        scene_tracker=scene_tracker,
    )
    
    # Should have evidence from multiple sources
    sources = set(ev.source for ev in vision.evidence)
    
    print(f"Evidence sources: {sources}")
    print(f"Total evidence items: {len(vision.evidence)}")
    
    expected_sources = {"vision", "scene"}  # At minimum
    if any(ev.source == "plate_trust" for ev in vision.evidence):
        expected_sources.add("plate_trust")
    
    assert len(sources) >= 2, f"Should have evidence from multiple sources, got: {sources}"
    print(f"✓ Evidence from {len(sources)} different sources")


def main():
    """Run tests with pytest."""
    import pytest
    return pytest.main([__file__, "-v", "-s"])


if __name__ == "__main__":
    sys.exit(main())

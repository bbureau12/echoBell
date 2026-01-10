"""
Unit tests for vision.py helper functions.

Tests geometric calculations, color extraction, and parent-child attachment
using synthetic data (no real images required).
"""

import pytest
import numpy as np
import sqlite3
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from packages.perception.vision import (
    _bbox_area,
    _intersection_area,
    _containment_ratio,
    _parse_parent_any_of,
    _closest_color_name,
    _dominant_color_rgb,
    extract_color_palette,
    _attach_children,
)
from packages.common.types import SceneObject


class TestGeometricHelpers:
    """Test bounding box geometric calculations."""
    
    def test_bbox_area_normal(self):
        """Test area calculation for normal bounding box."""
        assert _bbox_area((0, 0, 10, 10)) == 100
        assert _bbox_area((5, 5, 15, 25)) == 200  # 10x20
    
    def test_bbox_area_zero(self):
        """Test zero-area bounding boxes."""
        assert _bbox_area((5, 5, 5, 5)) == 0  # Point
        assert _bbox_area((0, 0, 0, 10)) == 0  # Zero width
        assert _bbox_area((0, 0, 10, 0)) == 0  # Zero height
    
    def test_bbox_area_inverted(self):
        """Test inverted coordinates (x2 < x1 or y2 < y1)."""
        assert _bbox_area((10, 10, 5, 5)) == 0  # Inverted
        assert _bbox_area((0, 10, 10, 5)) == 0  # Inverted Y
        assert _bbox_area((10, 0, 5, 10)) == 0  # Inverted X
    
    def test_intersection_area_overlapping(self):
        """Test intersection calculation for overlapping boxes."""
        a = (0, 0, 10, 10)
        b = (5, 5, 15, 15)
        # Intersection is (5,5,10,10) = 5x5 = 25
        assert _intersection_area(a, b) == 25
        assert _intersection_area(b, a) == 25  # Commutative
    
    def test_intersection_area_contained(self):
        """Test intersection when one box is fully inside another."""
        parent = (0, 0, 100, 100)
        child = (25, 25, 75, 75)
        # Intersection is entire child: 50x50 = 2500
        assert _intersection_area(parent, child) == 2500
        assert _intersection_area(child, parent) == 2500
    
    def test_intersection_area_no_overlap(self):
        """Test intersection for non-overlapping boxes."""
        a = (0, 0, 10, 10)
        b = (20, 20, 30, 30)
        assert _intersection_area(a, b) == 0
        assert _intersection_area(b, a) == 0
    
    def test_intersection_area_edge_touching(self):
        """Test boxes that touch at edges (no intersection)."""
        a = (0, 0, 10, 10)
        b = (10, 0, 20, 10)  # Shares edge at x=10
        assert _intersection_area(a, b) == 0  # No overlap
    
    def test_containment_ratio_fully_inside(self):
        """Test containment when child is fully inside parent."""
        parent = (0, 0, 100, 100)
        child = (25, 25, 75, 75)
        assert _containment_ratio(child, parent) == 1.0
    
    def test_containment_ratio_partial(self):
        """Test partial containment."""
        parent = (0, 0, 100, 100)
        child = (50, 50, 150, 150)  # Half inside, half outside
        # Child area: 100x100 = 10000
        # Intersection: (50,50,100,100) = 50x50 = 2500
        # Ratio: 2500/10000 = 0.25
        assert _containment_ratio(child, parent) == 0.25
    
    def test_containment_ratio_no_overlap(self):
        """Test no containment."""
        parent = (0, 0, 10, 10)
        child = (20, 20, 30, 30)
        assert _containment_ratio(child, parent) == 0.0
    
    def test_containment_ratio_zero_area_child(self):
        """Test containment with zero-area child."""
        parent = (0, 0, 100, 100)
        child = (50, 50, 50, 50)  # Point
        assert _containment_ratio(child, parent) == 0.0


class TestColorExtraction:
    """Test color detection and palette extraction."""
    
    def test_closest_color_primary_colors(self):
        """Test primary color matching."""
        assert _closest_color_name(np.array([0, 0, 0])) == "black"
        assert _closest_color_name(np.array([255, 255, 255])) == "white"
        assert _closest_color_name(np.array([128, 128, 128])) == "gray"
        assert _closest_color_name(np.array([200, 40, 40])) == "red"
        assert _closest_color_name(np.array([40, 160, 40])) == "green"
        assert _closest_color_name(np.array([40, 80, 200])) == "blue"
    
    def test_closest_color_secondary_colors(self):
        """Test secondary color matching."""
        assert _closest_color_name(np.array([230, 140, 40])) == "orange"
        assert _closest_color_name(np.array([220, 220, 40])) == "yellow"
        assert _closest_color_name(np.array([128, 0, 128])) == "purple"
        assert _closest_color_name(np.array([140, 90, 40])) == "brown"
    
    def test_dominant_color_solid_image(self):
        """Test dominant color extraction from solid color image."""
        # Create 100x100 solid red image (BGR format)
        red_crop = np.full((100, 100, 3), [40, 40, 200], dtype=np.uint8)
        dominant = _dominant_color_rgb(red_crop)
        # Should be close to red RGB: (200, 40, 40)
        assert np.allclose(dominant, [200, 40, 40], atol=10)
    
    def test_dominant_color_blue_image(self):
        """Test dominant color extraction from blue image."""
        # Create solid blue image (BGR: 200, 80, 40)
        blue_crop = np.full((50, 50, 3), [200, 80, 40], dtype=np.uint8)
        dominant = _dominant_color_rgb(blue_crop)
        # Should be close to blue RGB: (40, 80, 200)
        assert np.allclose(dominant, [40, 80, 200], atol=10)
    
    def test_extract_color_palette_two_colors(self):
        """Test palette extraction from two-color image."""
        # Create half blue, half white image (100x100)
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        img[:, :50] = [255, 0, 0]      # Left half: Blue (BGR)
        img[:, 50:] = [255, 255, 255]  # Right half: White
        
        palette = extract_color_palette(img, min_fraction=0.1)
        
        assert "blue" in palette
        assert "white" in palette
        # Each should be roughly 50% (allow some tolerance for clustering)
        assert 0.40 < palette["blue"] < 0.60
        assert 0.40 < palette["white"] < 0.60
    
    def test_extract_color_palette_black_white(self):
        """Test palette extraction from black and white image."""
        # Create vertical black and white stripes
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        img[:, :50] = [0, 0, 0]        # Left: Black
        img[:, 50:] = [255, 255, 255]  # Right: White
        
        palette = extract_color_palette(img, min_fraction=0.1)
        
        assert "black" in palette
        assert "white" in palette
        assert 0.40 < palette["black"] < 0.60
        assert 0.40 < palette["white"] < 0.60
    
    def test_extract_color_palette_min_area_filter(self):
        """Test that small color areas are filtered out."""
        # Create 100x100 image: 90% blue, 10% red
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        img[:, :90] = [255, 0, 0]      # 90%: Blue
        img[:, 90:] = [0, 0, 255]      # 10%: Red
        
        # With min_fraction=0.15, red should be filtered out
        palette = extract_color_palette(img, min_fraction=0.15)
        
        assert "blue" in palette
        assert "red" not in palette  # Too small, filtered out


class TestParentParsing:
    """Test parent label parsing for attachment rules."""
    
    def test_parse_single_parent(self):
        """Test parsing single parent label."""
        assert _parse_parent_any_of("person") == {"person"}
        assert _parse_parent_any_of("vehicle") == {"vehicle"}
    
    def test_parse_multiple_parents(self):
        """Test parsing comma-separated parent labels."""
        assert _parse_parent_any_of("person,vehicle") == {"person", "vehicle"}
        assert _parse_parent_any_of("car,truck,bus") == {"car", "truck", "bus"}
    
    def test_parse_with_spaces(self):
        """Test parsing with extra whitespace."""
        assert _parse_parent_any_of(" person , vehicle ") == {"person", "vehicle"}
        assert _parse_parent_any_of("car, truck,  bus") == {"car", "truck", "bus"}
    
    def test_parse_empty_string(self):
        """Test parsing empty string."""
        assert _parse_parent_any_of("") == set()
        assert _parse_parent_any_of("  ") == set()
    
    def test_parse_none(self):
        """Test parsing None value."""
        assert _parse_parent_any_of(None) == set()


class TestParentChildAttachment:
    """Test parent-child object attachment logic."""
    
    @pytest.fixture
    def test_db(self, tmp_path):
        """Create temporary database with attach rules."""
        db_path = tmp_path / "test_attach.db"
        conn = sqlite3.connect(str(db_path))
        
        conn.execute("""
            CREATE TABLE attach_rule (
                id INTEGER PRIMARY KEY,
                child_label TEXT NOT NULL,
                parent_any_of TEXT NOT NULL,
                min_containment REAL DEFAULT 0.7,
                min_parent_conf REAL DEFAULT 0.6,
                prefer_parent TEXT DEFAULT 'best_score',
                enabled INTEGER DEFAULT 1
            )
        """)
        conn.commit()
        
        yield conn
        conn.close()
    
    def test_attach_tie_to_person(self, test_db):
        """Test attaching tie to person based on containment."""
        # Setup rule: tie must be 70% inside person
        test_db.execute("""
            INSERT INTO attach_rule (child_label, parent_any_of, min_containment, enabled)
            VALUES ('tie', 'person', 0.7, 1)
        """)
        test_db.commit()
        
        # Create person and tie objects
        person = SceneObject(
            object_id=0,
            label="person",
            box=(0, 0, 100, 100),
            props={"conf": 0.85},
            evidence=[]
        )
        
        tie = SceneObject(
            object_id=1,
            label="tie",
            box=(40, 40, 60, 60),  # Fully inside person
            props={"conf": 0.75},
            evidence=[]
        )
        
        objects = [person, tie]
        _attach_children(test_db, objects, debug=False)
        
        # Tie should be attached to person
        assert tie.parent_id == 0
        assert person.parent_id is None
    
    def test_attach_no_containment(self, test_db):
        """Test that objects without sufficient containment are not attached."""
        test_db.execute("""
            INSERT INTO attach_rule (child_label, parent_any_of, min_containment, enabled)
            VALUES ('tie', 'person', 0.7, 1)
        """)
        test_db.commit()
        
        person = SceneObject(
            object_id=0,
            label="person",
            box=(0, 0, 50, 50),
            props={"conf": 0.85},
            evidence=[]
        )
        
        tie = SceneObject(
            object_id=1,
            label="tie",
            box=(60, 60, 80, 80),  # No overlap with person
            props={"conf": 0.75},
            evidence=[]
        )
        
        objects = [person, tie]
        _attach_children(test_db, objects, debug=False)
        
        # Tie should NOT be attached
        assert tie.parent_id is None
    
    def test_attach_multiple_parents_choose_best(self, test_db):
        """Test that child attaches to best parent when multiple candidates exist."""
        test_db.execute("""
            INSERT INTO attach_rule (child_label, parent_any_of, min_containment, prefer_parent, enabled)
            VALUES ('tie', 'person', 0.5, 'largest', 1)
        """)
        test_db.commit()
        
        # Two people, tie overlaps both, larger person should win
        person1 = SceneObject(
            object_id=0,
            label="person",
            box=(0, 0, 100, 100),  # Larger
            props={"conf": 0.80},
            evidence=[]
        )
        
        person2 = SceneObject(
            object_id=1,
            label="person",
            box=(50, 50, 100, 100),  # Smaller
            props={"conf": 0.85},
            evidence=[]
        )
        
        tie = SceneObject(
            object_id=2,
            label="tie",
            box=(60, 60, 80, 80),  # Overlaps both
            props={"conf": 0.75},
            evidence=[]
        )
        
        objects = [person1, person2, tie]
        _attach_children(test_db, objects, debug=False)
        
        # Tie should attach to larger person (prefer_parent='largest')
        assert tie.parent_id == 0
    
    def test_attach_respect_min_parent_conf(self, test_db):
        """Test that low-confidence parents are ignored."""
        test_db.execute("""
            INSERT INTO attach_rule (child_label, parent_any_of, min_containment, min_parent_conf, enabled)
            VALUES ('tie', 'person', 0.5, 0.7, 1)
        """)
        test_db.commit()
        
        # Low confidence person
        person = SceneObject(
            object_id=0,
            label="person",
            box=(0, 0, 100, 100),
            props={"conf": 0.60},  # Below min_parent_conf=0.7
            evidence=[]
        )
        
        tie = SceneObject(
            object_id=1,
            label="tie",
            box=(40, 40, 60, 60),
            props={"conf": 0.85},
            evidence=[]
        )
        
        objects = [person, tie]
        _attach_children(test_db, objects, debug=False)
        
        # Tie should NOT attach (parent confidence too low)
        assert tie.parent_id is None
    
    def test_attach_disabled_rule(self, test_db):
        """Test that disabled rules are not applied."""
        test_db.execute("""
            INSERT INTO attach_rule (child_label, parent_any_of, min_containment, enabled)
            VALUES ('tie', 'person', 0.5, 0)
        """)
        test_db.commit()
        
        person = SceneObject(
            object_id=0,
            label="person",
            box=(0, 0, 100, 100),
            props={"conf": 0.85},
            evidence=[]
        )
        
        tie = SceneObject(
            object_id=1,
            label="tie",
            box=(40, 40, 60, 60),
            props={"conf": 0.75},
            evidence=[]
        )
        
        objects = [person, tie]
        _attach_children(test_db, objects, debug=False)
        
        # Tie should NOT attach (rule disabled)
        assert tie.parent_id is None
    
    def test_attach_multiple_children_to_same_parent(self, test_db):
        """Test that multiple children can attach to same parent."""
        test_db.execute("""
            INSERT INTO attach_rule (child_label, parent_any_of, min_containment, enabled)
            VALUES ('tie', 'person', 0.5, 1)
        """)
        test_db.commit()
        
        person = SceneObject(
            object_id=0,
            label="person",
            box=(0, 0, 100, 100),
            props={"conf": 0.85},
            evidence=[]
        )
        
        tie1 = SceneObject(
            object_id=1,
            label="tie",
            box=(30, 30, 50, 50),
            props={"conf": 0.75},
            evidence=[]
        )
        
        tie2 = SceneObject(
            object_id=2,
            label="tie",
            box=(60, 60, 80, 80),
            props={"conf": 0.80},
            evidence=[]
        )
        
        objects = [person, tie1, tie2]
        _attach_children(test_db, objects, debug=False)
        
        # Both ties should attach to same person
        assert tie1.parent_id == 0
        assert tie2.parent_id == 0
    
    def test_attach_prefer_highest_conf(self, test_db):
        """Test prefer_parent='highest_conf' strategy."""
        test_db.execute("""
            INSERT INTO attach_rule (child_label, parent_any_of, min_containment, prefer_parent, enabled)
            VALUES ('tie', 'person', 0.5, 'highest_conf', 1)
        """)
        test_db.commit()
        
        # Two people with different confidence
        person1 = SceneObject(
            object_id=0,
            label="person",
            box=(0, 0, 100, 100),
            props={"conf": 0.70},  # Lower confidence
            evidence=[]
        )
        
        person2 = SceneObject(
            object_id=1,
            label="person",
            box=(50, 50, 100, 100),
            props={"conf": 0.90},  # Higher confidence
            evidence=[]
        )
        
        tie = SceneObject(
            object_id=2,
            label="tie",
            box=(60, 60, 80, 80),  # Overlaps both
            props={"conf": 0.75},
            evidence=[]
        )
        
        objects = [person1, person2, tie]
        _attach_children(test_db, objects, debug=False)
        
        # Tie should attach to higher confidence person
        assert tie.parent_id == 1

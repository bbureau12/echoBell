"""
Unit tests for intent.py classification functions.

Tests signal group binding, rule matching, and confidence scoring
using synthetic VisionResults (no real images required).
"""

import pytest
import sqlite3
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from packages.classify.intent import (
    _confidence,
    _resolve_bind_id,
    _score_signal_groups,
    classify,
)
from packages.common.types import VisionResult, SceneObject, Evidence, RuleMatch


def make_vision_result(objects=None, evidence=None):
    """Helper to create VisionResult with minimal required fields."""
    return VisionResult(
        snapshot_path="test.jpg",
        detections=[],
        person_present=False,
        package_box=False,
        vehicle_present=False,
        dog_present=False,
        objects=objects or [],
        evidence=evidence or []
    )


def make_rule_match(rule_id, intent_name, delta, ev_source="vision", 
                    ev_feature="test", ev_value="true", ev_conf=0.8,
                    ev_obj_id=None, op="equals", urgency=10):
    """Helper to create RuleMatch with all required fields."""
    return RuleMatch(
        rule_id=rule_id,
        intent_name=intent_name,
        delta=delta,
        urgency=urgency,
        ev_source=ev_source,
        ev_feature=ev_feature,
        ev_value=ev_value,
        ev_conf=ev_conf,
        ev_obj_id=ev_obj_id,
        op=op,
        rule_value=ev_value,  # For simplicity, use same as ev_value
        scope_any_of=""
    )


class TestConfidenceMapping:
    """Test confidence score normalization."""
    
    def test_confidence_normal_range(self):
        """Test confidence mapping for normal input values."""
        assert _confidence(0.0) == 0.5   # 0.5 + 0.15*0 = 0.5
        assert _confidence(1.0) == 0.65  # 0.5 + 0.15*1 = 0.65
        assert _confidence(2.0) == 0.80  # 0.5 + 0.15*2 = 0.80
    
    def test_confidence_clamping_low(self):
        """Test that very low scores are clamped to 0.4."""
        assert _confidence(-1.0) == 0.4
        assert _confidence(-10.0) == 0.4
    
    def test_confidence_clamping_high(self):
        """Test that very high scores are clamped to 0.95."""
        assert _confidence(5.0) == 0.95
        assert _confidence(10.0) == 0.95


class TestBindIdResolution:
    """Test bind_id resolution for signal group binding."""
    
    def test_bind_scene_always_none(self):
        """Test that 'scene' scope always returns None."""
        vr = make_vision_result()
        assert _resolve_bind_id(vr, None, "scene") is None
        assert _resolve_bind_id(vr, 5, "scene") is None
        assert _resolve_bind_id(vr, 100, "scene") is None
    
    def test_bind_self_returns_object_id(self):
        """Test that 'self' scope returns the evidence's object_id."""
        vr = make_vision_result()
        assert _resolve_bind_id(vr, 5, "self") == 5
        assert _resolve_bind_id(vr, 0, "self") == 0
        assert _resolve_bind_id(vr, 42, "self") == 42
    
    def test_bind_self_with_none_object_id(self):
        """Test that 'self' with None object_id returns None."""
        vr = make_vision_result()
        assert _resolve_bind_id(vr, None, "self") is None
    
    def test_bind_root_flat_hierarchy(self):
        """Test 'root' resolution with no parent (object is its own root)."""
        person = SceneObject(
            object_id=0,
            label="person",
            box=(0, 0, 100, 100),
            props={},
            evidence=[]
        )
        vr = make_vision_result(objects=[person])
        
        # Person has no parent, so it's its own root
        assert _resolve_bind_id(vr, 0, "root") == 0
    
    def test_bind_root_with_parent(self):
        """Test 'root' resolution walks up to top-level parent."""
        person = SceneObject(
            object_id=0,
            label="person",
            box=(0, 0, 100, 100),
            props={},
            evidence=[]
        )
        
        tie = SceneObject(
            object_id=1,
            label="tie",
            box=(40, 40, 60, 60),
            props={},
            evidence=[],
            parent_id=0  # Tie is child of person
        )
        
        vr = make_vision_result(objects=[person, tie])
        
        # Tie's root should be person
        assert _resolve_bind_id(vr, 1, "root") == 0
        # Person's root is itself
        assert _resolve_bind_id(vr, 0, "root") == 0
    
    def test_bind_root_deep_hierarchy(self):
        """Test 'root' resolution with 3-level hierarchy."""
        vehicle = SceneObject(
            object_id=0,
            label="vehicle",
            box=(0, 0, 200, 200),
            props={},
            evidence=[]
        )
        
        person = SceneObject(
            object_id=1,
            label="person",
            box=(50, 50, 150, 150),
            props={},
            evidence=[],
            parent_id=0  # Person inside vehicle
        )
        
        tie = SceneObject(
            object_id=2,
            label="tie",
            box=(80, 80, 100, 100),
            props={},
            evidence=[],
            parent_id=1  # Tie on person
        )
        
        vr = make_vision_result(objects=[vehicle, person, tie])
        
        # All should resolve to vehicle (root)
        assert _resolve_bind_id(vr, 0, "root") == 0  # Vehicle is root
        assert _resolve_bind_id(vr, 1, "root") == 0  # Person → vehicle
        assert _resolve_bind_id(vr, 2, "root") == 0  # Tie → person → vehicle
    
    def test_bind_label_match_self(self):
        """Test binding to specific label when object itself matches."""
        person = SceneObject(
            object_id=0,
            label="person",
            box=(0, 0, 100, 100),
            props={},
            evidence=[]
        )
        
        vr = make_vision_result(objects=[person])
        
        # Person binding to 'person' label should return itself
        assert _resolve_bind_id(vr, 0, "person") == 0
    
    def test_bind_label_match_parent(self):
        """Test binding to specific label walks up to matching ancestor."""
        vehicle = SceneObject(
            object_id=0,
            label="vehicle",
            box=(0, 0, 200, 200),
            props={},
            evidence=[]
        )
        
        person = SceneObject(
            object_id=1,
            label="person",
            box=(50, 50, 150, 150),
            props={},
            evidence=[],
            parent_id=0
        )
        
        tie = SceneObject(
            object_id=2,
            label="tie",
            box=(80, 80, 100, 100),
            props={},
            evidence=[],
            parent_id=1
        )
        
        vr = make_vision_result(objects=[vehicle, person, tie])
        
        # Tie binding to 'person' should find parent person
        assert _resolve_bind_id(vr, 2, "person") == 1
        # Tie binding to 'vehicle' should find grandparent vehicle
        assert _resolve_bind_id(vr, 2, "vehicle") == 0
        # Person binding to 'vehicle' should find parent vehicle
        assert _resolve_bind_id(vr, 1, "vehicle") == 0
    
    def test_bind_label_no_match(self):
        """Test binding to label that doesn't exist returns None."""
        person = SceneObject(
            object_id=0,
            label="person",
            box=(0, 0, 100, 100),
            props={},
            evidence=[]
        )
        
        tie = SceneObject(
            object_id=1,
            label="tie",
            box=(40, 40, 60, 60),
            props={},
            evidence=[],
            parent_id=0
        )
        
        vr = make_vision_result(objects=[person, tie])
        
        # Tie binding to 'vehicle' should return None (no vehicle in hierarchy)
        assert _resolve_bind_id(vr, 1, "vehicle") is None
        # Person binding to 'vehicle' should also return None
        assert _resolve_bind_id(vr, 0, "vehicle") is None
    
    def test_bind_none_object_id(self):
        """Test that None object_id returns None for any scope except scene."""
        vr = make_vision_result()
        
        assert _resolve_bind_id(vr, None, "scene") is None
        assert _resolve_bind_id(vr, None, "self") is None
        assert _resolve_bind_id(vr, None, "root") is None
        assert _resolve_bind_id(vr, None, "person") is None


class TestSignalGroupScoring:
    """Test signal group scoring and binding logic."""
    
    @pytest.fixture
    def test_db(self, tmp_path):
        """Create temporary database with signal group tables."""
        db_path = tmp_path / "test_groups.db"
        conn = sqlite3.connect(str(db_path))
        
        # Signal groups
        conn.execute("""
            CREATE TABLE signal_group (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                intent_name TEXT NOT NULL,
                group_mode TEXT DEFAULT 'all',
                bind_scope TEXT,
                base_weight REAL DEFAULT 1.0,
                urgency INTEGER DEFAULT 10,
                enabled INTEGER DEFAULT 1
            )
        """)
        
        # Signal group members
        conn.execute("""
            CREATE TABLE signal_group_member (
                group_id INTEGER NOT NULL,
                rule_id INTEGER NOT NULL,
                required INTEGER DEFAULT 0,
                weight_mul REAL DEFAULT 1.0,
                enabled INTEGER DEFAULT 1,
                PRIMARY KEY (group_id, rule_id)
            )
        """)
        
        conn.commit()
        yield conn
        conn.close()
    
    def test_group_basic_scoring(self, test_db):
        """Test basic group scoring with single rule."""
        # Create group with base_weight=1.0
        test_db.execute("""
            INSERT INTO signal_group (id, name, intent_name, base_weight, bind_scope, enabled)
            VALUES (1, 'test_group', 'test_intent', 1.0, 'scene', 1)
        """)
        
        # Add member rule (rule_id=10, weight_mul=2.0)
        test_db.execute("""
            INSERT INTO signal_group_member (group_id, rule_id, required, weight_mul, enabled)
            VALUES (1, 10, 0, 2.0, 1)
        """)
        test_db.commit()
        
        # Create matching rule (delta=0.5)
        match = make_rule_match(
            rule_id=10,
            intent_name="test_intent",
            delta=0.5
        )
        
        vr = make_vision_result()
        scores, urgencies, trace = _score_signal_groups(test_db, vr, [match])
        
        # Score = base_weight + (delta * weight_mul) = 1.0 + (0.5 * 2.0) = 2.0
        assert scores["test_intent"] == 2.0
        assert 10 in urgencies["test_intent"]
    
    def test_group_required_rule_missing(self, test_db):
        """Test that groups with missing required rules don't score."""
        # Create group
        test_db.execute("""
            INSERT INTO signal_group (id, name, intent_name, base_weight, bind_scope, enabled)
            VALUES (1, 'test_group', 'test_intent', 1.0, 'scene', 1)
        """)
        
        # Add required rule (rule_id=10)
        test_db.execute("""
            INSERT INTO signal_group_member (group_id, rule_id, required, weight_mul, enabled)
            VALUES (1, 10, 1, 1.0, 1)
        """)
        test_db.commit()
        
        # No matches provided (required rule missing)
        vr = make_vision_result()
        scores, urgencies, trace = _score_signal_groups(test_db, vr, [])
        
        # Group should not score (required rule missing)
        assert "test_intent" not in scores or scores["test_intent"] == 0
    
    def test_group_required_rule_present(self, test_db):
        """Test that groups with satisfied required rules do score."""
        # Create group
        test_db.execute("""
            INSERT INTO signal_group (id, name, intent_name, base_weight, bind_scope, enabled)
            VALUES (1, 'test_group', 'test_intent', 2.0, 'scene', 1)
        """)
        
        # Add required rule
        test_db.execute("""
            INSERT INTO signal_group_member (group_id, rule_id, required, weight_mul, enabled)
            VALUES (1, 10, 1, 1.5, 1)
        """)
        test_db.commit()
        
        # Provide match for required rule
        match = make_rule_match(
            rule_id=10,
            intent_name="test_intent",
            delta=0.6
        )
        
        vr = make_vision_result()
        scores, urgencies, trace = _score_signal_groups(test_db, vr, [match])
        
        # Score = base_weight + (delta * weight_mul) = 2.0 + (0.6 * 1.5) = 2.9
        assert scores["test_intent"] == 2.9
    
    def test_group_bind_scope_self(self, test_db):
        """Test group binding with bind_scope='self'."""
        # Create group with bind_scope='self'
        test_db.execute("""
            INSERT INTO signal_group (id, name, intent_name, base_weight, bind_scope, enabled)
            VALUES (1, 'test_group', 'test_intent', 1.0, 'self', 1)
        """)
        
        # Add member rule
        test_db.execute("""
            INSERT INTO signal_group_member (group_id, rule_id, required, weight_mul, enabled)
            VALUES (1, 10, 0, 1.0, 1)
        """)
        test_db.commit()
        
        # Create matches for different objects
        match1 = make_rule_match(
            rule_id=10, intent_name="test_intent", delta=0.5,
            ev_feature="color", ev_value="blue", ev_obj_id=0
        )
        
        match2 = make_rule_match(
            rule_id=10, intent_name="test_intent", delta=0.7,
            ev_feature="color", ev_value="blue", ev_obj_id=1
        )
        
        vr = make_vision_result()
        scores, urgencies, trace = _score_signal_groups(test_db, vr, [match1, match2])
        
        # With bind_scope='self', each object contributes separately
        # Both should contribute: 1.0 + 0.5 + 1.0 + 0.7 = 3.2
        assert scores["test_intent"] == pytest.approx(3.2)
    
    def test_group_disabled(self, test_db):
        """Test that disabled groups don't contribute."""
        # Create disabled group
        test_db.execute("""
            INSERT INTO signal_group (id, name, intent_name, base_weight, bind_scope, enabled)
            VALUES (1, 'test_group', 'test_intent', 1.0, 'scene', 0)
        """)
        
        # Add member rule
        test_db.execute("""
            INSERT INTO signal_group_member (group_id, rule_id, required, weight_mul, enabled)
            VALUES (1, 10, 0, 2.0, 1)
        """)
        test_db.commit()
        
        # Create match
        match = make_rule_match(
            rule_id=10, intent_name="test_intent", delta=0.5
        )
        
        vr = make_vision_result()
        scores, urgencies, trace = _score_signal_groups(test_db, vr, [match])
        
        # Group is disabled, should not score
        assert "test_intent" not in scores or scores["test_intent"] == 0
    
    def test_group_multiple_members_best_match(self, test_db):
        """Test that best match per rule is used when multiple matches exist."""
        # Create group
        test_db.execute("""
            INSERT INTO signal_group (id, name, intent_name, base_weight, bind_scope, enabled)
            VALUES (1, 'test_group', 'test_intent', 0.0, 'scene', 1)
        """)
        
        # Add member rule
        test_db.execute("""
            INSERT INTO signal_group_member (group_id, rule_id, required, weight_mul, enabled)
            VALUES (1, 10, 0, 1.0, 1)
        """)
        test_db.commit()
        
        # Create multiple matches for same rule (best should win)
        match1 = make_rule_match(
            rule_id=10, intent_name="test_intent", delta=0.3
        )
        
        match2 = make_rule_match(
            rule_id=10, intent_name="test_intent", delta=0.8  # Higher delta
        )
        
        vr = make_vision_result()
        scores, urgencies, trace = _score_signal_groups(test_db, vr, [match1, match2])
        
        # Should use best match: 0.0 + (0.8 * 1.0) = 0.8
        assert scores["test_intent"] == 0.8
    
    def test_group_bind_scope_person(self, test_db):
        """Test group binding to specific label (person)."""
        # Create group with bind_scope='person'
        test_db.execute("""
            INSERT INTO signal_group (id, name, intent_name, base_weight, bind_scope, enabled)
            VALUES (1, 'test_group', 'test_intent', 1.0, 'person', 1)
        """)
        
        # Add member rule
        test_db.execute("""
            INSERT INTO signal_group_member (group_id, rule_id, required, weight_mul, enabled)
            VALUES (1, 10, 0, 1.0, 1)
        """)
        test_db.commit()
        
        # Create person and tie (child of person)
        person = SceneObject(
            object_id=0, label="person", box=(0, 0, 100, 100),
            props={}, evidence=[]
        )
        
        tie = SceneObject(
            object_id=1, label="tie", box=(40, 40, 60, 60),
            props={}, evidence=[], parent_id=0
        )
        
        # Match attached to tie (should bind to person)
        match = make_rule_match(
            rule_id=10, intent_name="test_intent", delta=0.5,
            ev_feature="color", ev_value="blue", ev_obj_id=1  # Evidence on tie
        )
        
        vr = make_vision_result(objects=[person, tie])
        scores, urgencies, trace = _score_signal_groups(test_db, vr, [match])
        
        # Should bind to person (parent of tie)
        assert scores["test_intent"] == 1.5  # 1.0 + 0.5


class TestClassifyIntegration:
    """Integration tests for full classify() function."""
    
    @pytest.fixture
    def test_db(self, tmp_path):
        """Create temporary database with minimal intent setup."""
        db_path = tmp_path / "test_classify.db"
        conn = sqlite3.connect(str(db_path))
        
        # Intent definitions
        conn.execute("""
            CREATE TABLE intent_def (
                name TEXT PRIMARY KEY,
                description TEXT,
                urgency INTEGER DEFAULT 10
            )
        """)
        
        conn.execute("""
            INSERT INTO intent_def (name, urgency)
            VALUES ('unknown', 10), ('test_intent', 5)
        """)
        
        # Pattern definitions (empty for these tests)
        conn.execute("""
            CREATE TABLE pattern_def (
                pattern TEXT NOT NULL,
                is_regex INTEGER DEFAULT 0,
                intent_name TEXT,
                entity_name TEXT,
                weight REAL DEFAULT 1.0,
                enabled INTEGER DEFAULT 1
            )
        """)
        
        # Entity definitions (empty)
        conn.execute("""
            CREATE TABLE entity_def (
                name TEXT PRIMARY KEY,
                tag TEXT,
                weight REAL DEFAULT 0.5,
                description TEXT
            )
        """)
        
        # Signal rules (empty - will test without signal rules)
        conn.execute("""
            CREATE TABLE signal_rule (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                feature TEXT NOT NULL,
                operator TEXT NOT NULL,
                value TEXT NOT NULL,
                intent_name TEXT NOT NULL,
                weight REAL DEFAULT 1.0,
                min_conf REAL DEFAULT 0.0,
                urgency INTEGER DEFAULT 10,
                scope_any_of TEXT,
                contributes_standalone INTEGER DEFAULT 1,
                enabled INTEGER DEFAULT 1
            )
        """)
        
        # Signal groups (empty)
        conn.execute("""
            CREATE TABLE signal_group (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                intent_name TEXT NOT NULL,
                group_mode TEXT DEFAULT 'all',
                bind_scope TEXT,
                base_weight REAL DEFAULT 1.0,
                urgency INTEGER DEFAULT 10,
                enabled INTEGER DEFAULT 1
            )
        """)
        
        conn.execute("""
            CREATE TABLE signal_group_member (
                group_id INTEGER NOT NULL,
                rule_id INTEGER NOT NULL,
                required INTEGER DEFAULT 0,
                weight_mul REAL DEFAULT 1.0,
                enabled INTEGER DEFAULT 1,
                PRIMARY KEY (group_id, rule_id)
            )
        """)
        
        conn.commit()
        conn.close()
        
        yield str(db_path)
    
    def test_classify_empty_vision(self, test_db):
        """Test classification with empty vision result."""
        vr = make_vision_result()
        result = classify("", vr, test_db)
        
        # Should default to 'unknown'
        assert result.intent == "unknown"
        assert 0.4 <= result.conf <= 0.5  # Default confidence
    
    def test_classify_with_text_only(self, test_db):
        """Test classification with text but no vision."""
        vr = make_vision_result()
        result = classify("hello there", vr, test_db)
        
        # Without patterns, should still be unknown
        assert result.intent == "unknown"

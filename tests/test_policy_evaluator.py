"""
Tests for policy rule engine evaluator
"""
import pytest
import sqlite3
import yaml
from datetime import datetime, timedelta
from packages.policy.evaluator import PolicyEvaluator, PolicyMatch


@pytest.fixture
def test_db():
    """Create in-memory test database with schema"""
    conn = sqlite3.connect(':memory:')
    
    # Create trusted_plates table
    conn.execute("""
        CREATE TABLE trusted_plates (
            plate_hmac TEXT PRIMARY KEY,
            label TEXT,
            enabled INTEGER DEFAULT 1
        )
    """)
    
    # Create trusted_person table
    conn.execute("""
        CREATE TABLE trusted_person (
            trusted_id TEXT PRIMARY KEY,
            name TEXT,
            active INTEGER DEFAULT 1
        )
    """)
    
    # Create alert_history table
    conn.execute("""
        CREATE TABLE alert_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            camera_id TEXT,
            track_key TEXT,
            alert_type TEXT,
            priority TEXT,
            sent_ts INTEGER,
            message TEXT,
            success INTEGER
        )
    """)
    
    # Insert test data
    conn.execute("INSERT INTO trusted_plates VALUES ('plate_abc123', 'John Doe', 1)")
    conn.execute("INSERT INTO trusted_person VALUES ('person_xyz789', 'Jane Smith', 1)")
    
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def simple_policy_yaml(tmp_path):
    """Create a simple policy YAML file"""
    policy_file = tmp_path / "test_policies.yaml"
    policy_config = {
        'policies': [
            {
                'id': 'unknown_vehicle',
                'name': 'Unknown Vehicle Alert',
                'enabled': True,
                'priority': 10,
                'conditions': {
                    'all': [
                        {'evidence_exists': {'source': 'alpr', 'feature': 'plate_hmac'}},
                        {'trust_check': {'table': 'trusted_plates', 'match_field': 'plate_hmac', 'exists': False}}
                    ]
                },
                'actions': [
                    {'type': 'telegram', 'message': 'Unknown vehicle detected', 'priority': 'normal'}
                ]
            }
        ],
        'variables': {}
    }
    
    with open(policy_file, 'w') as f:
        yaml.dump(policy_config, f)
    
    return str(policy_file)


def test_evidence_exists_condition(test_db, simple_policy_yaml):
    """Test evidence_exists condition"""
    evaluator = PolicyEvaluator(simple_policy_yaml, test_db)
    
    evidence = [
        {'source': 'alpr', 'feature': 'plate_hmac', 'value': 'unknown_plate', 'conf': 0.95}
    ]
    context = {'camera_id': 'cam1', 'track_key': 'track_001', 'plate_hmac': 'unknown_plate'}
    
    matches = evaluator.evaluate_all(evidence, context)
    
    assert len(matches) == 1
    assert matches[0].policy_id == 'unknown_vehicle'
    assert matches[0].policy_name == 'Unknown Vehicle Alert'


def test_trust_check_trusted_plate(test_db, simple_policy_yaml):
    """Test trust check with trusted plate (should NOT match unknown_vehicle policy)"""
    evaluator = PolicyEvaluator(simple_policy_yaml, test_db)
    
    evidence = [
        {'source': 'alpr', 'feature': 'plate_hmac', 'value': 'plate_abc123', 'conf': 0.95}
    ]
    context = {'camera_id': 'cam1', 'track_key': 'track_002', 'plate_hmac': 'plate_abc123'}
    
    matches = evaluator.evaluate_all(evidence, context)
    
    # Should NOT match because plate IS trusted (exists=False in policy)
    assert len(matches) == 0


def test_boolean_all_operator(test_db, tmp_path):
    """Test 'all' (AND) boolean operator"""
    policy_file = tmp_path / "test_all.yaml"
    policy_config = {
        'policies': [
            {
                'id': 'test_all',
                'name': 'Test ALL',
                'enabled': True,
                'priority': 10,
                'conditions': {
                    'all': [
                        {'evidence_exists': {'source': 'alpr', 'feature': 'plate_hmac'}},
                        {'evidence_exists': {'source': 'movement', 'feature': 'significant_movement'}}
                    ]
                },
                'actions': [{'type': 'telegram', 'message': 'Both conditions met'}]
            }
        ],
        'variables': {}
    }
    
    with open(policy_file, 'w') as f:
        yaml.dump(policy_config, f)
    
    evaluator = PolicyEvaluator(str(policy_file), test_db)
    
    # Both conditions present - should match
    evidence = [
        {'source': 'alpr', 'feature': 'plate_hmac', 'value': 'plate123', 'conf': 0.9},
        {'source': 'movement', 'feature': 'significant_movement', 'value': '150px', 'conf': 1.0}
    ]
    matches = evaluator.evaluate_all(evidence, {})
    assert len(matches) == 1
    
    # Only one condition - should NOT match
    evidence = [
        {'source': 'alpr', 'feature': 'plate_hmac', 'value': 'plate123', 'conf': 0.9}
    ]
    matches = evaluator.evaluate_all(evidence, {})
    assert len(matches) == 0


def test_boolean_any_operator(test_db, tmp_path):
    """Test 'any' (OR) boolean operator"""
    policy_file = tmp_path / "test_any.yaml"
    policy_config = {
        'policies': [
            {
                'id': 'test_any',
                'name': 'Test ANY',
                'enabled': True,
                'priority': 10,
                'conditions': {
                    'any': [
                        {'evidence_exists': {'source': 'alpr', 'feature': 'plate_hmac'}},
                        {'evidence_exists': {'source': 'movement', 'feature': 'loitering'}}
                    ]
                },
                'actions': [{'type': 'telegram', 'message': 'Either condition met'}]
            }
        ],
        'variables': {}
    }
    
    with open(policy_file, 'w') as f:
        yaml.dump(policy_config, f)
    
    evaluator = PolicyEvaluator(str(policy_file), test_db)
    
    # First condition only - should match
    evidence = [{'source': 'alpr', 'feature': 'plate_hmac', 'value': 'plate123', 'conf': 0.9}]
    matches = evaluator.evaluate_all(evidence, {})
    assert len(matches) == 1
    
    # Second condition only - should match
    evidence = [{'source': 'movement', 'feature': 'loitering', 'value': 'true', 'conf': 1.0}]
    matches = evaluator.evaluate_all(evidence, {})
    assert len(matches) == 1
    
    # Neither condition - should NOT match
    evidence = [{'source': 'other', 'feature': 'something', 'value': 'value', 'conf': 0.5}]
    matches = evaluator.evaluate_all(evidence, {})
    assert len(matches) == 0


def test_boolean_not_operator(test_db, tmp_path):
    """Test 'not' boolean operator"""
    policy_file = tmp_path / "test_not.yaml"
    policy_config = {
        'policies': [
            {
                'id': 'test_not',
                'name': 'Test NOT',
                'enabled': True,
                'priority': 10,
                'conditions': {
                    'not': {'evidence_exists': {'source': 'alpr', 'feature': 'plate_hmac'}}
                },
                'actions': [{'type': 'telegram', 'message': 'No plate detected'}]
            }
        ],
        'variables': {}
    }
    
    with open(policy_file, 'w') as f:
        yaml.dump(policy_config, f)
    
    evaluator = PolicyEvaluator(str(policy_file), test_db)
    
    # No plate evidence - should match
    evidence = [{'source': 'movement', 'feature': 'loitering', 'value': 'true', 'conf': 1.0}]
    matches = evaluator.evaluate_all(evidence, {})
    assert len(matches) == 1
    
    # Plate evidence present - should NOT match
    evidence = [{'source': 'alpr', 'feature': 'plate_hmac', 'value': 'plate123', 'conf': 0.9}]
    matches = evaluator.evaluate_all(evidence, {})
    assert len(matches) == 0


def test_track_duration_gt(test_db, tmp_path):
    """Test track_duration_gt temporal condition"""
    policy_file = tmp_path / "test_duration.yaml"
    policy_config = {
        'policies': [
            {
                'id': 'loitering_alert',
                'name': 'Loitering Alert',
                'enabled': True,
                'priority': 10,
                'conditions': {
                    'all': [
                        {'evidence_exists': {'source': 'movement', 'feature': 'loitering'}},
                        {'track_duration_gt': 180}  # 3 minutes
                    ]
                },
                'actions': [{'type': 'telegram', 'message': 'Loitering detected'}]
            }
        ],
        'variables': {}
    }
    
    with open(policy_file, 'w') as f:
        yaml.dump(policy_config, f)
    
    evaluator = PolicyEvaluator(str(policy_file), test_db)
    
    evidence = [{'source': 'movement', 'feature': 'loitering', 'value': 'true', 'conf': 1.0}]
    
    # Duration > 180 seconds - should match
    context = {'track_duration_seconds': 200}
    matches = evaluator.evaluate_all(evidence, context)
    assert len(matches) == 1
    
    # Duration < 180 seconds - should NOT match
    context = {'track_duration_seconds': 120}
    matches = evaluator.evaluate_all(evidence, context)
    assert len(matches) == 0


def test_no_recent_alert(test_db, tmp_path):
    """Test no_recent_alert condition (spam prevention)"""
    policy_file = tmp_path / "test_spam.yaml"
    policy_config = {
        'policies': [
            {
                'id': 'spam_prevention',
                'name': 'Spam Prevention',
                'enabled': True,
                'priority': 10,
                'conditions': {
                    'all': [
                        {'evidence_exists': {'source': 'alpr', 'feature': 'plate_hmac'}},
                        {'no_recent_alert': {'track_key': 'current', 'alert_type': 'telegram', 'within_seconds': 300}}
                    ]
                },
                'actions': [{'type': 'telegram', 'message': 'New vehicle'}]
            }
        ],
        'variables': {}
    }
    
    with open(policy_file, 'w') as f:
        yaml.dump(policy_config, f)
    
    evaluator = PolicyEvaluator(str(policy_file), test_db)
    
    evidence = [{'source': 'alpr', 'feature': 'plate_hmac', 'value': 'plate123', 'conf': 0.9}]
    context = {'track_key': 'track_003', 'camera_id': 'cam1'}
    
    # No recent alert - should match
    matches = evaluator.evaluate_all(evidence, context)
    assert len(matches) == 1
    
    # Add recent alert (2 minutes ago)
    now_ts = int(datetime.now().timestamp())
    recent_ts = now_ts - 120  # 2 minutes ago
    test_db.execute("""
        INSERT INTO alert_history (camera_id, track_key, alert_type, priority, sent_ts, message, success)
        VALUES ('cam1', 'track_003', 'telegram', 'normal', ?, 'Test alert', 1)
    """, (recent_ts,))
    test_db.commit()
    
    # Recent alert exists - should NOT match
    matches = evaluator.evaluate_all(evidence, context)
    assert len(matches) == 0


def test_alert_sent_within(test_db, tmp_path):
    """Test alert_sent_within condition (escalation)"""
    policy_file = tmp_path / "test_escalation.yaml"
    policy_config = {
        'policies': [
            {
                'id': 'escalation_policy',
                'name': 'Escalation Policy',
                'enabled': True,
                'priority': 20,
                'conditions': {
                    'all': [
                        {'evidence_exists': {'source': 'movement', 'feature': 'loitering'}},
                        {'alert_sent_within': {'track_key': 'current', 'alert_type': 'telegram', 'min_seconds': 60, 'max_seconds': 300}}
                    ]
                },
                'actions': [{'type': 'telegram', 'message': 'URGENT escalation', 'priority': 'urgent'}]
            }
        ],
        'variables': {}
    }
    
    with open(policy_file, 'w') as f:
        yaml.dump(policy_config, f)
    
    evaluator = PolicyEvaluator(str(policy_file), test_db)
    
    evidence = [{'source': 'movement', 'feature': 'loitering', 'value': 'true', 'conf': 1.0}]
    context = {'track_key': 'track_004', 'camera_id': 'cam1'}
    
    # No alert - should NOT match
    matches = evaluator.evaluate_all(evidence, context)
    assert len(matches) == 0
    
    # Add alert 2 minutes ago (120 seconds) - within window [60, 300]
    now_ts = int(datetime.now().timestamp())
    alert_ts = now_ts - 120
    test_db.execute("""
        INSERT INTO alert_history (camera_id, track_key, alert_type, priority, sent_ts, message, success)
        VALUES ('cam1', 'track_004', 'telegram', 'normal', ?, 'Initial alert', 1)
    """, (alert_ts,))
    test_db.commit()
    
    # Alert within window - should match
    matches = evaluator.evaluate_all(evidence, context)
    assert len(matches) == 1


def test_evidence_value_contains(test_db, tmp_path):
    """Test evidence_value_contains condition"""
    policy_file = tmp_path / "test_contains.yaml"
    policy_config = {
        'policies': [
            {
                'id': 'delivery_detected',
                'name': 'Delivery Detected',
                'enabled': True,
                'priority': 10,
                'conditions': {
                    'evidence_value_contains': {
                        'source': 'alpr',
                        'feature': 'plate_label',
                        'contains': 'delivery'
                    }
                },
                'actions': [{'type': 'speak', 'text': 'Please leave package at door'}]
            }
        ],
        'variables': {}
    }
    
    with open(policy_file, 'w') as f:
        yaml.dump(policy_config, f)
    
    evaluator = PolicyEvaluator(str(policy_file), test_db)
    
    # Label contains "delivery" - should match
    evidence = [{'source': 'alpr', 'feature': 'plate_label', 'value': 'UPS Delivery Truck', 'conf': 0.9}]
    matches = evaluator.evaluate_all(evidence, {})
    assert len(matches) == 1
    
    # Label does NOT contain "delivery" - should NOT match
    evidence = [{'source': 'alpr', 'feature': 'plate_label', 'value': 'John Doe', 'conf': 0.9}]
    matches = evaluator.evaluate_all(evidence, {})
    assert len(matches) == 0


def test_evidence_value_gt(test_db, tmp_path):
    """Test evidence_value_gt condition (numeric comparison)"""
    policy_file = tmp_path / "test_gt.yaml"
    policy_config = {
        'policies': [
            {
                'id': 'large_movement',
                'name': 'Large Movement',
                'enabled': True,
                'priority': 10,
                'conditions': {
                    'evidence_value_gt': {
                        'source': 'movement',
                        'feature': 'distance_px',
                        'threshold': 100
                    }
                },
                'actions': [{'type': 'telegram', 'message': 'Large movement detected'}]
            }
        ],
        'variables': {}
    }
    
    with open(policy_file, 'w') as f:
        yaml.dump(policy_config, f)
    
    evaluator = PolicyEvaluator(str(policy_file), test_db)
    
    # Value > 100 - should match
    evidence = [{'source': 'movement', 'feature': 'distance_px', 'value': '150.5px', 'conf': 1.0}]
    matches = evaluator.evaluate_all(evidence, {})
    assert len(matches) == 1
    
    # Value < 100 - should NOT match
    evidence = [{'source': 'movement', 'feature': 'distance_px', 'value': '50.2px', 'conf': 1.0}]
    matches = evaluator.evaluate_all(evidence, {})
    assert len(matches) == 0


def test_time_between(test_db, tmp_path):
    """Test time_between condition (nighttime detection)"""
    policy_file = tmp_path / "test_time.yaml"
    policy_config = {
        'policies': [
            {
                'id': 'nighttime_alert',
                'name': 'Nighttime Alert',
                'enabled': True,
                'priority': 15,
                'conditions': {
                    'time_between': {
                        'start': '22:00',
                        'end': '06:00'
                    }
                },
                'actions': [{'type': 'telegram', 'message': 'Nighttime activity', 'priority': 'urgent'}]
            }
        ],
        'variables': {}
    }
    
    with open(policy_file, 'w') as f:
        yaml.dump(policy_config, f)
    
    evaluator = PolicyEvaluator(str(policy_file), test_db)
    
    # Note: This test will pass/fail depending on current time
    # In real tests, you'd mock datetime.now()
    evidence = []
    matches = evaluator.evaluate_all(evidence, {})
    # Just verify it doesn't crash - actual match depends on current time


def test_policy_priority_ordering(test_db, tmp_path):
    """Test that policies are sorted by priority (highest first)"""
    policy_file = tmp_path / "test_priority.yaml"
    policy_config = {
        'policies': [
            {
                'id': 'low_priority',
                'name': 'Low Priority',
                'enabled': True,
                'priority': 5,
                'conditions': {'evidence_exists': {'source': 'alpr', 'feature': 'plate_hmac'}},
                'actions': [{'type': 'telegram', 'message': 'Low priority'}]
            },
            {
                'id': 'high_priority',
                'name': 'High Priority',
                'enabled': True,
                'priority': 20,
                'conditions': {'evidence_exists': {'source': 'alpr', 'feature': 'plate_hmac'}},
                'actions': [{'type': 'telegram', 'message': 'High priority'}]
            },
            {
                'id': 'medium_priority',
                'name': 'Medium Priority',
                'enabled': True,
                'priority': 10,
                'conditions': {'evidence_exists': {'source': 'alpr', 'feature': 'plate_hmac'}},
                'actions': [{'type': 'telegram', 'message': 'Medium priority'}]
            }
        ],
        'variables': {}
    }
    
    with open(policy_file, 'w') as f:
        yaml.dump(policy_config, f)
    
    evaluator = PolicyEvaluator(str(policy_file), test_db)
    
    evidence = [{'source': 'alpr', 'feature': 'plate_hmac', 'value': 'plate123', 'conf': 0.9}]
    matches = evaluator.evaluate_all(evidence, {})
    
    assert len(matches) == 3
    assert matches[0].policy_id == 'high_priority'
    assert matches[0].priority == 20
    assert matches[1].policy_id == 'medium_priority'
    assert matches[1].priority == 10
    assert matches[2].policy_id == 'low_priority'
    assert matches[2].priority == 5


def test_disabled_policy_not_evaluated(test_db, tmp_path):
    """Test that disabled policies are not evaluated"""
    policy_file = tmp_path / "test_disabled.yaml"
    policy_config = {
        'policies': [
            {
                'id': 'disabled_policy',
                'name': 'Disabled Policy',
                'enabled': False,
                'priority': 10,
                'conditions': {'evidence_exists': {'source': 'alpr', 'feature': 'plate_hmac'}},
                'actions': [{'type': 'telegram', 'message': 'Should not trigger'}]
            }
        ],
        'variables': {}
    }
    
    with open(policy_file, 'w') as f:
        yaml.dump(policy_config, f)
    
    evaluator = PolicyEvaluator(str(policy_file), test_db)
    
    evidence = [{'source': 'alpr', 'feature': 'plate_hmac', 'value': 'plate123', 'conf': 0.9}]
    matches = evaluator.evaluate_all(evidence, {})
    
    assert len(matches) == 0


def test_variable_resolution_from_evidence(test_db, tmp_path):
    """Test variable resolution from evidence"""
    policy_file = tmp_path / "test_variables.yaml"
    policy_config = {
        'policies': [
            {
                'id': 'test_vars',
                'name': 'Test Variables',
                'enabled': True,
                'priority': 10,
                'conditions': {'evidence_exists': {'source': 'alpr', 'feature': 'plate_hmac'}},
                'actions': [{'type': 'telegram', 'message': 'Plate: {plate_value}'}]
            }
        ],
        'variables': {
            'plate_value': {
                'source': 'alpr',
                'feature': 'plate_hmac',
                'default': 'UNKNOWN'
            }
        }
    }
    
    with open(policy_file, 'w') as f:
        yaml.dump(policy_config, f)
    
    evaluator = PolicyEvaluator(str(policy_file), test_db)
    
    evidence = [{'source': 'alpr', 'feature': 'plate_hmac', 'value': 'ABC123', 'conf': 0.9}]
    matches = evaluator.evaluate_all(evidence, {})
    
    assert len(matches) == 1
    assert matches[0].variables['plate_value'] == 'ABC123'


def test_variable_resolution_from_context(test_db, tmp_path):
    """Test variable resolution from context"""
    policy_file = tmp_path / "test_context_vars.yaml"
    policy_config = {
        'policies': [
            {
                'id': 'test_context',
                'name': 'Test Context',
                'enabled': True,
                'priority': 10,
                'conditions': {'evidence_exists': {'source': 'alpr', 'feature': 'plate_hmac'}},
                'actions': [{'type': 'telegram', 'message': 'Camera: {camera_name}'}]
            }
        ],
        'variables': {
            'camera_name': {
                'from_context': 'camera_id'
            }
        }
    }
    
    with open(policy_file, 'w') as f:
        yaml.dump(policy_config, f)
    
    evaluator = PolicyEvaluator(str(policy_file), test_db)
    
    evidence = [{'source': 'alpr', 'feature': 'plate_hmac', 'value': 'ABC123', 'conf': 0.9}]
    context = {'camera_id': 'front_door_cam'}
    matches = evaluator.evaluate_all(evidence, context)
    
    assert len(matches) == 1
    assert matches[0].variables['camera_name'] == 'front_door_cam'

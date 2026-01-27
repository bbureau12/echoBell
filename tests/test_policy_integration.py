"""
Integration test for complete policy evaluation flow
Tests the exact scenario user requested: loitering escalation with remote lights
"""
import pytest
import sqlite3
import yaml
from datetime import datetime
from packages.policy.evaluator import PolicyEvaluator
from packages.policy.executor import ActionExecutor
from packages.policy.apply import evaluate_policies


@pytest.fixture
def test_db():
    """Create in-memory database with full schema"""
    conn = sqlite3.connect(':memory:')
    
    # Create tables
    conn.execute("""
        CREATE TABLE trusted_plates (
            plate_hmac TEXT PRIMARY KEY,
            label TEXT,
            enabled INTEGER DEFAULT 1
        )
    """)
    
    conn.execute("""
        CREATE TABLE trusted_person (
            trusted_id TEXT PRIMARY KEY,
            name TEXT,
            active INTEGER DEFAULT 1
        )
    """)
    
    conn.execute("""
        CREATE TABLE alert_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            camera_id TEXT,
            track_key TEXT,
            track_type TEXT,
            alert_type TEXT,
            policy_id TEXT,
            priority TEXT,
            sent_ts INTEGER,
            message TEXT,
            success INTEGER,
            error_message TEXT
        )
    """)
    
    conn.execute("""
        CREATE TABLE policy_rules (
            id TEXT PRIMARY KEY,
            name TEXT,
            description TEXT,
            enabled INTEGER DEFAULT 1,
            priority INTEGER DEFAULT 50,
            conditions TEXT,
            actions TEXT,
            variables TEXT,
            created_ts INTEGER,
            updated_ts INTEGER,
            created_by TEXT,
            tags TEXT,
            version INTEGER DEFAULT 1
        )
    """)
    
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def policy_file_with_escalation(tmp_path):
    """Create policy file with user's exact loitering escalation scenario"""
    policy_file = tmp_path / "escalation_policies.yaml"
    policy_config = {
        'policies': [
            {
                'id': 'initial_loitering_alert',
                'name': 'Initial Loitering Alert',
                'enabled': True,
                'priority': 10,
                'conditions': {
                    'all': [
                        {'evidence_exists': {'source': 'movement', 'feature': 'loitering'}},
                        {'track_duration_gt': 180},  # 3 minutes
                        {'trust_check': {'table': 'trusted_person', 'match_field': 'visitor_id', 'exists': False}},
                        {'no_recent_alert': {'track_key': 'current', 'alert_type': 'telegram', 'within_seconds': 600}}
                    ]
                },
                'actions': [
                    {'type': 'telegram', 'message': 'Person loitering for {duration_min} minutes', 'priority': 'normal'},
                    {'type': 'speak', 'text': 'Please state your business'}
                ]
            },
            {
                'id': 'loitering_escalation_with_lights',
                'name': 'Loitering Escalation with Lights',
                'enabled': True,
                'priority': 20,  # Higher priority
                'conditions': {
                    'all': [
                        {'evidence_exists': {'source': 'movement', 'feature': 'loitering'}},
                        {'track_duration_gt': 180},  # Still loitering after 3 min
                        {'trust_check': {'table': 'trusted_person', 'match_field': 'visitor_id', 'exists': False}},
                        {'alert_sent_within': {'track_key': 'current', 'alert_type': 'telegram', 'min_seconds': 120, 'max_seconds': 600}},
                        # Simulating no_expected_delivery (future: actual delivery schedule check)
                        {'any': [
                            {'no_expected_delivery': True},
                            {'no_scheduled_appointment': True}
                        ]}
                    ]
                },
                'actions': [
                    {'type': 'telegram', 'message': '🚨 URGENT: Person STILL loitering after {duration_min} minutes!', 'priority': 'urgent'},
                    {'type': 'speak', 'text': 'This is private property. State your business or leave immediately.'},
                    {'type': 'webhook', 'url': '{remote_lights_url}', 'method': 'POST', 'payload': {'action': 'turn_on', 'duration': 60}}
                ]
            }
        ],
        'variables': {
            'duration_min': {
                'from_context': 'track_duration_seconds',
                'calculate': 'track_duration_seconds / 60',
                'format': '%.1f'
            },
            'remote_lights_url': {
                'env': 'REMOTE_LIGHTS_URL',
                'default': 'http://localhost:8080/lights'
            }
        }
    }
    
    with open(policy_file, 'w') as f:
        yaml.dump(policy_config, f)
    
    return str(policy_file)


@pytest.mark.asyncio
async def test_complete_loitering_escalation_flow(test_db, policy_file_with_escalation):
    """
    Test complete user scenario:
    1. Unknown person starts loitering (3+ min) → Initial alert
    2. Person STILL loitering + alert was sent → Escalation with lights
    """
    
    # SCENARIO 1: Initial loitering detection (3 minutes, no prior alerts)
    evidence_initial = [
        {'source': 'movement', 'feature': 'loitering', 'value': 'true', 'conf': 1.0},
        {'source': 'person', 'feature': 'visitor_id', 'value': 'unknown_person_123', 'conf': 0.8}
    ]
    
    context_initial = {
        'camera_id': 'front_door',
        'track_key': 'person_track_001',
        'visitor_id': 'unknown_person_123',
        'track_duration_seconds': 185  # Just over 3 minutes
    }
    
    # Evaluate policies
    results_initial = await evaluate_policies(evidence_initial, context_initial, test_db, policy_file_with_escalation, use_database=False)
    
    # Should trigger initial_loitering_alert (no prior alerts)
    assert len(results_initial) == 2  # telegram + speak
    assert results_initial[0]['policy_id'] == 'initial_loitering_alert'
    assert results_initial[0]['action_type'] == 'telegram'
    assert results_initial[0]['priority'] == 'normal'
    assert 'loitering' in results_initial[0]['message'].lower()
    
    assert results_initial[1]['action_type'] == 'speak'
    assert 'state your business' in results_initial[1]['text'].lower()
    
    # Verify alert was recorded in alert_history
    alert_row = test_db.execute("""
        SELECT track_key, alert_type, priority
        FROM alert_history
        WHERE track_key = 'person_track_001' AND alert_type = 'telegram'
    """).fetchone()
    assert alert_row is not None
    assert alert_row[2] == 'normal'  # Initial priority
    
    
    # SCENARIO 2: Escalation - person STILL loitering 5 minutes later (total 8 min)
    # Add a backdated alert (sent 3 minutes ago) to simulate time passing
    now_ts = int(datetime.now().timestamp())
    alert_ts = now_ts - 180  # 3 minutes ago
    test_db.execute("""
        UPDATE alert_history
        SET sent_ts = ?
        WHERE track_key = 'person_track_001'
    """, (alert_ts,))
    test_db.commit()
    
    evidence_escalation = [
        {'source': 'movement', 'feature': 'loitering', 'value': 'true', 'conf': 1.0},
        {'source': 'person', 'feature': 'visitor_id', 'value': 'unknown_person_123', 'conf': 0.8}
    ]
    
    context_escalation = {
        'camera_id': 'front_door',
        'track_key': 'person_track_001',
        'visitor_id': 'unknown_person_123',
        'track_duration_seconds': 485  # 8+ minutes total
    }
    
    # Evaluate policies again
    results_escalation = await evaluate_policies(evidence_escalation, context_escalation, test_db, policy_file_with_escalation, use_database=False)
    
    # Should trigger loitering_escalation_with_lights (higher priority)
    # Note: Both policies match, but higher priority comes first
    assert len(results_escalation) >= 3  # telegram + speak + webhook
    
    # Find the escalation policy results
    escalation_results = [r for r in results_escalation if r['policy_id'] == 'loitering_escalation_with_lights']
    assert len(escalation_results) == 3
    
    # Check telegram escalation
    telegram_result = next(r for r in escalation_results if r['action_type'] == 'telegram')
    assert telegram_result['priority'] == 'urgent'
    assert 'URGENT' in telegram_result['message']
    assert 'STILL loitering' in telegram_result['message']
    
    # Check speak escalation
    speak_result = next(r for r in escalation_results if r['action_type'] == 'speak')
    assert 'private property' in speak_result['text'].lower()
    assert 'leave immediately' in speak_result['text'].lower()
    
    # Check webhook (remote lights)
    webhook_result = next(r for r in escalation_results if r['action_type'] == 'webhook')
    assert webhook_result['url'] == 'http://localhost:8080/lights'  # default from env var
    # Note: webhook will fail in test (no actual server), but that's OK


@pytest.mark.asyncio
async def test_trusted_person_no_alert(test_db, policy_file_with_escalation):
    """
    Test that trusted person does NOT trigger loitering alerts
    """
    # Add trusted person
    test_db.execute("INSERT INTO trusted_person VALUES ('trusted_person_456', 'John Doe', 1)")
    test_db.commit()
    
    evidence = [
        {'source': 'movement', 'feature': 'loitering', 'value': 'true', 'conf': 1.0},
        {'source': 'person', 'feature': 'visitor_id', 'value': 'trusted_person_456', 'conf': 0.95}
    ]
    
    context = {
        'camera_id': 'front_door',
        'track_key': 'person_track_002',
        'visitor_id': 'trusted_person_456',
        'track_duration_seconds': 300  # 5 minutes loitering
    }
    
    results = await evaluate_policies(evidence, context, test_db, policy_file_with_escalation, use_database=False)
    
    # Should NOT trigger any alerts (trusted person)
    assert len(results) == 0


@pytest.mark.asyncio
async def test_movement_without_loitering_no_alert(test_db, policy_file_with_escalation):
    """
    Test that movement without loitering flag does NOT trigger alerts
    """
    evidence = [
        {'source': 'movement', 'feature': 'significant_movement', 'value': '150px', 'conf': 1.0},
        # No loitering evidence
        {'source': 'person', 'feature': 'visitor_id', 'value': 'unknown_person_789', 'conf': 0.8}
    ]
    
    context = {
        'camera_id': 'front_door',
        'track_key': 'person_track_003',
        'visitor_id': 'unknown_person_789',
        'track_duration_seconds': 200
    }
    
    results = await evaluate_policies(evidence, context, test_db, policy_file_with_escalation, use_database=False)
    
    # Should NOT trigger loitering policies (no loitering evidence)
    assert len(results) == 0


@pytest.mark.asyncio
async def test_short_duration_no_alert(test_db, policy_file_with_escalation):
    """
    Test that loitering < 3 minutes does NOT trigger alerts
    """
    evidence = [
        {'source': 'movement', 'feature': 'loitering', 'value': 'true', 'conf': 1.0},
        {'source': 'person', 'feature': 'visitor_id', 'value': 'unknown_person_999', 'conf': 0.8}
    ]
    
    context = {
        'camera_id': 'front_door',
        'track_key': 'person_track_004',
        'visitor_id': 'unknown_person_999',
        'track_duration_seconds': 120  # Only 2 minutes
    }
    
    results = await evaluate_policies(evidence, context, test_db, policy_file_with_escalation, use_database=False)
    
    # Should NOT trigger (duration < 180 seconds)
    assert len(results) == 0

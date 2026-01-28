"""
Test camera-specific policies.

Example: On Halloween, person detected on main door (camera 2) → Say "Happy Halloween"
         but person on garage camera (camera 3) → Normal alert
"""
import pytest
import sqlite3
import json
import time
from packages.policy.apply import evaluate_policies


@pytest.fixture(autouse=True)
def mock_telegram(monkeypatch):
    """Mock telegram to prevent sending real messages"""
    def mock_send_message(self, message):
        return True
    from packages.integrations import telegram
    monkeypatch.setattr(telegram.TelegramNotifier, 'send_message', mock_send_message)


@pytest.fixture
def test_db():
    """Create in-memory database"""
    conn = sqlite3.connect(':memory:')
    
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
    
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def camera_specific_policy(test_db, tmp_path):
    """Create policy: Person on camera 2 → Say 'Happy Halloween'"""
    policy_file = tmp_path / "camera_policy.yaml"
    
    policy_config = {
        'policies': [
            {
                'id': 'main_door_halloween',
                'name': 'Main Door Halloween Greeting',
                'description': 'Greet people at main door on Halloween',
                'enabled': True,
                'priority': 90,
                'conditions': {
                    'all': [
                        {'evidence_exists': {'source': 'vision', 'feature': 'person_present'}},
                        {'camera_id_eq': 'main_door'}  # Only main door
                    ]
                },
                'actions': [
                    {'type': 'speak', 'text': 'Happy Halloween! Enjoy your treats!'}
                ]
            },
            {
                'id': 'garage_normal_alert',
                'name': 'Garage Normal Alert',
                'description': 'Normal alert for garage camera',
                'enabled': True,
                'priority': 50,
                'conditions': {
                    'all': [
                        {'evidence_exists': {'source': 'vision', 'feature': 'person_present'}},
                        {'camera_id_eq': 'garage'}  # Only garage
                    ]
                },
                'actions': [
                    {'type': 'telegram', 'message': 'Person detected at garage', 'priority': 'normal'}
                ]
            }
        ]
    }
    
    import yaml
    with open(policy_file, 'w') as f:
        yaml.dump(policy_config, f)
    
    return str(policy_file)


@pytest.mark.asyncio
async def test_camera_specific_halloween_greeting(test_db, camera_specific_policy):
    """Test that main door triggers Halloween greeting"""
    
    evidence = [
        {'source': 'vision', 'feature': 'person_present', 'value': 'true', 'conf': 0.95}
    ]
    
    context = {
        'camera_id': 'main_door',
        'track_key': 'person_001'
    }
    
    results = await evaluate_policies(evidence, context, test_db, camera_specific_policy, use_database=False)
    
    # Should trigger main door Halloween greeting
    assert len(results) == 1
    assert results[0]['policy_id'] == 'main_door_halloween'
    assert results[0]['action_type'] == 'speak'
    assert 'Happy Halloween' in results[0]['text']


@pytest.mark.asyncio
async def test_camera_specific_garage_alert(test_db, camera_specific_policy):
    """Test that garage camera triggers normal alert"""
    
    evidence = [
        {'source': 'vision', 'feature': 'person_present', 'value': 'true', 'conf': 0.95}
    ]
    
    context = {
        'camera_id': 'garage',
        'track_key': 'person_002'
    }
    
    results = await evaluate_policies(evidence, context, test_db, camera_specific_policy, use_database=False)
    
    # Should trigger garage normal alert
    assert len(results) == 1
    assert results[0]['policy_id'] == 'garage_normal_alert'
    assert results[0]['action_type'] == 'telegram'
    assert 'garage' in results[0]['message'].lower()


@pytest.mark.asyncio
async def test_camera_specific_no_match(test_db, camera_specific_policy):
    """Test that other cameras don't match either policy"""
    
    evidence = [
        {'source': 'vision', 'feature': 'person_present', 'value': 'true', 'conf': 0.95}
    ]
    
    context = {
        'camera_id': 'backyard',  # Not main_door or garage
        'track_key': 'person_003'
    }
    
    results = await evaluate_policies(evidence, context, test_db, camera_specific_policy, use_database=False)
    
    # Should not trigger any policy
    assert len(results) == 0


@pytest.mark.asyncio
async def test_camera_id_in_multiple_cameras(test_db, tmp_path):
    """Test camera_id_in condition for multiple cameras"""
    
    policy_file = tmp_path / "multi_camera_policy.yaml"
    
    policy_config = {
        'policies': [
            {
                'id': 'front_cameras_alert',
                'name': 'Front Cameras Alert',
                'description': 'Alert for any front-facing camera',
                'enabled': True,
                'priority': 50,
                'conditions': {
                    'all': [
                        {'evidence_exists': {'source': 'vision', 'feature': 'person_present'}},
                        {'camera_id_in': ['front_door', 'main_door', 'driveway']}
                    ]
                },
                'actions': [
                    {'type': 'speak', 'text': 'Welcome to the front entrance'}
                ]
            }
        ]
    }
    
    import yaml
    with open(policy_file, 'w') as f:
        yaml.dump(policy_config, f)
    
    # Test with main_door (in list)
    evidence = [
        {'source': 'vision', 'feature': 'person_present', 'value': 'true', 'conf': 0.95}
    ]
    
    context_main = {
        'camera_id': 'main_door',
        'track_key': 'person_001'
    }
    
    results = await evaluate_policies(evidence, context_main, test_db, str(policy_file), use_database=False)
    assert len(results) == 1
    assert 'Welcome' in results[0]['text']
    
    # Test with driveway (in list)
    context_driveway = {
        'camera_id': 'driveway',
        'track_key': 'person_002'
    }
    
    results = await evaluate_policies(evidence, context_driveway, test_db, str(policy_file), use_database=False)
    assert len(results) == 1
    
    # Test with garage (not in list)
    context_garage = {
        'camera_id': 'garage',
        'track_key': 'person_003'
    }
    
    results = await evaluate_policies(evidence, context_garage, test_db, str(policy_file), use_database=False)
    assert len(results) == 0

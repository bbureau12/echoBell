"""
Tests for Policy API endpoints
"""

import pytest
from packages.policy.policy_service import PolicyRulesService
import sqlite3
import os
import tempfile


@pytest.fixture
def temp_db():
    """Create a temporary database for testing"""
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    
    # Initialize schema
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS policy_rules (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            priority INTEGER NOT NULL DEFAULT 50,
            conditions_json TEXT NOT NULL,
            actions_json TEXT NOT NULL,
            variables_json TEXT,
            created_ts INTEGER NOT NULL,
            updated_ts INTEGER NOT NULL,
            created_by TEXT DEFAULT 'system',
            tags TEXT,
            version INTEGER DEFAULT 1
        );
        
        CREATE TABLE IF NOT EXISTS policy_executions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            policy_id TEXT NOT NULL,
            event_id TEXT,
            track_key TEXT,
            track_type TEXT,
            camera_id INTEGER,
            matched_conditions TEXT,
            executed_actions TEXT,
            execution_ts INTEGER NOT NULL,
            success INTEGER DEFAULT 1,
            error_message TEXT
        );
    """)
    conn.close()
    
    yield path
    
    # Cleanup (with retry on Windows)
    try:
        os.unlink(path)
    except PermissionError:
        pass  # File still locked on Windows, will be cleaned by OS


@pytest.fixture
def service(temp_db):
    """Create PolicyRulesService with temp database"""
    return PolicyRulesService(temp_db)


def test_create_policy(service):
    """Test creating a new policy"""
    policy = service.create_policy(
        policy_id="test_policy",
        name="Test Policy",
        description="A test policy",
        enabled=True,
        priority=75,
        conditions={"evidence_exists": {"source": "vision", "feature": "vehicle_present"}},
        actions=[{"type": "telegram", "message": "Test alert"}],
        created_by="test"
    )
    
    assert policy['id'] == "test_policy"
    assert policy['name'] == "Test Policy"
    assert policy['priority'] == 75
    assert policy['enabled'] == 1
    assert policy['version'] == 1


def test_get_policy(service):
    """Test retrieving a policy"""
    # Create
    service.create_policy(
        policy_id="retrieve_test",
        name="Retrieve Test",
        conditions={"all": []},
        actions=[]
    )
    
    # Retrieve
    policy = service.get_policy("retrieve_test")
    assert policy is not None
    assert policy['id'] == "retrieve_test"


def test_get_all_policies(service):
    """Test listing all policies"""
    # Create multiple
    service.create_policy(
        policy_id="policy1",
        name="Policy 1",
        priority=100,
        conditions={},
        actions=[]
    )
    service.create_policy(
        policy_id="policy2",
        name="Policy 2",
        priority=50,
        conditions={},
        actions=[]
    )
    
    # List all
    policies = service.get_all_policies()
    assert len(policies) == 2
    
    # Check priority sorting (highest first)
    assert policies[0]['priority'] == 100
    assert policies[1]['priority'] == 50


def test_get_enabled_policies_only(service):
    """Test filtering enabled policies"""
    service.create_policy(
        policy_id="enabled_policy",
        name="Enabled",
        enabled=True,
        conditions={},
        actions=[]
    )
    service.create_policy(
        policy_id="disabled_policy",
        name="Disabled",
        enabled=False,
        conditions={},
        actions=[]
    )
    
    enabled_policies = service.get_all_policies(enabled_only=True)
    assert len(enabled_policies) == 1
    assert enabled_policies[0]['id'] == "enabled_policy"


def test_update_policy(service):
    """Test updating policy fields"""
    # Create
    service.create_policy(
        policy_id="update_test",
        name="Original Name",
        priority=50,
        conditions={},
        actions=[]
    )
    
    # Update
    updated = service.update_policy(
        policy_id="update_test",
        name="Updated Name",
        priority=90
    )
    
    assert updated['name'] == "Updated Name"
    assert updated['priority'] == 90
    assert updated['version'] == 2  # Version incremented


def test_delete_policy(service):
    """Test deleting a policy"""
    service.create_policy(
        policy_id="delete_test",
        name="Delete Test",
        conditions={},
        actions=[]
    )
    
    # Delete
    success = service.delete_policy("delete_test")
    assert success is True
    
    # Verify deleted
    policy = service.get_policy("delete_test")
    assert policy is None


def test_toggle_policy(service):
    """Test enabling/disabling a policy"""
    service.create_policy(
        policy_id="toggle_test",
        name="Toggle Test",
        enabled=True,
        conditions={},
        actions=[]
    )
    
    # Disable
    disabled = service.toggle_policy("toggle_test", enabled=False)
    assert disabled['enabled'] == 0
    
    # Enable
    enabled = service.toggle_policy("toggle_test", enabled=True)
    assert enabled['enabled'] == 1


def test_log_execution(service):
    """Test logging policy execution"""
    # Create policy first
    service.create_policy(
        policy_id="exec_test",
        name="Execution Test",
        conditions={},
        actions=[]
    )
    
    # Log execution
    service.log_execution(
        policy_id="exec_test",
        event_id="evt_123",
        track_key="plate_abc",
        track_type="vehicle",
        camera_id=1,
        matched_conditions={"evidence_exists": True},
        executed_actions=[{"type": "telegram", "sent": True}],
        success=True
    )
    
    # Retrieve history
    history = service.get_execution_history(policy_id="exec_test", limit=10)
    assert len(history) == 1
    assert history[0]['policy_id'] == "exec_test"
    assert history[0]['track_key'] == "plate_abc"
    assert history[0]['success'] == 1


def test_duplicate_policy_raises_error(service):
    """Test that creating duplicate policy ID raises error"""
    service.create_policy(
        policy_id="duplicate",
        name="First",
        conditions={},
        actions=[]
    )
    
    with pytest.raises(ValueError, match="already exists"):
        service.create_policy(
            policy_id="duplicate",
            name="Second",
            conditions={},
            actions=[]
        )


def test_update_nonexistent_policy_raises_error(service):
    """Test that updating non-existent policy raises error"""
    with pytest.raises(ValueError, match="not found"):
        service.update_policy(
            policy_id="nonexistent",
            name="Updated"
        )


def test_complex_conditions_and_actions(service):
    """Test creating policy with complex nested conditions"""
    policy = service.create_policy(
        policy_id="complex_test",
        name="Complex Policy",
        conditions={
            "all": [
                {"evidence_exists": {"source": "vision", "feature": "vehicle_present"}},
                {
                    "any": [
                        {"time_between": {"start": "22:00", "end": "06:00"}},
                        {"day_of_week": {"days": ["saturday", "sunday"]}}
                    ]
                },
                {"not": {"trust_check": {"check_type": "trusted_plates"}}}
            ]
        },
        actions=[
            {
                "type": "telegram",
                "message": "Unknown vehicle detected!",
                "priority": "urgent"
            },
            {
                "type": "webhook",
                "url": "http://localhost:3000/alert",
                "method": "POST",
                "payload": {"severity": "high"}
            }
        ],
        variables={
            "vehicle_info": "{vehicle_color} {vehicle_type}",
            "custom_threshold": 0.85
        }
    )
    
    # Verify complex structure preserved
    assert "all" in policy['conditions']
    assert len(policy['actions']) == 2
    assert policy['variables']['custom_threshold'] == 0.85


def test_import_from_yaml(service):
    """Test importing policies from YAML structure"""
    yaml_policies = [
        {
            "id": "yaml_policy_1",
            "name": "YAML Policy 1",
            "description": "Imported from YAML",
            "enabled": True,
            "priority": 80,
            "conditions": {"evidence_exists": {"source": "vision", "feature": "person_present"}},
            "actions": [{"type": "speak", "text": "Hello!"}]
        },
        {
            "id": "yaml_policy_2",
            "name": "YAML Policy 2",
            "enabled": False,
            "priority": 60,
            "conditions": {},
            "actions": []
        }
    ]
    
    # Import
    service.import_from_yaml(yaml_policies, overwrite=False)
    
    # Verify imported
    policies = service.get_all_policies()
    assert len(policies) == 2
    
    # Check specific policy
    policy1 = service.get_policy("yaml_policy_1")
    assert policy1['name'] == "YAML Policy 1"
    assert policy1['created_by'] == "yaml_import"


def test_import_yaml_no_overwrite(service):
    """Test that import skips existing policies when overwrite=False"""
    # Create existing
    service.create_policy(
        policy_id="existing",
        name="Original",
        priority=50,
        conditions={},
        actions=[]
    )
    
    # Try to import with same ID
    yaml_policies = [
        {
            "id": "existing",
            "name": "Updated from YAML",
            "priority": 100,
            "conditions": {},
            "actions": []
        }
    ]
    
    service.import_from_yaml(yaml_policies, overwrite=False)
    
    # Verify NOT updated
    policy = service.get_policy("existing")
    assert policy['name'] == "Original"  # Not changed
    assert policy['priority'] == 50  # Not changed


def test_import_yaml_with_overwrite(service):
    """Test that import updates existing policies when overwrite=True"""
    # Create existing
    service.create_policy(
        policy_id="existing",
        name="Original",
        priority=50,
        conditions={},
        actions=[]
    )
    
    # Import with overwrite
    yaml_policies = [
        {
            "id": "existing",
            "name": "Updated from YAML",
            "priority": 100,
            "conditions": {},
            "actions": []
        }
    ]
    
    service.import_from_yaml(yaml_policies, overwrite=True)
    
    # Verify updated
    policy = service.get_policy("existing")
    assert policy['name'] == "Updated from YAML"
    assert policy['priority'] == 100

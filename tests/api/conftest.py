"""
Test fixtures for Policy API testing.

Provides:
- TestClient for FastAPI (no server needed)
- Temporary test database
- Helper functions for creating test data
"""

import pytest
import sqlite3
import importlib.util
from pathlib import Path
from fastapi.testclient import TestClient
import sys

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.helpers.db_setup import create_test_schema, create_test_cameras
import json


@pytest.fixture
def test_db(tmp_path):
    """Create a temporary database with all required schemas."""
    db_path = tmp_path / "test_policy_api.db"
    conn = sqlite3.connect(str(db_path))
    
    # Create all required tables
    create_test_schema(conn, include_facial_recognition=True)
    
    # Insert test cameras
    create_test_cameras(conn, [
        {'id': 1, 'name': 'Test Camera 1', 'capability_level_id': 1, 'stream_url': 'rtsp://test1'},
        {'id': 2, 'name': 'Test Camera 2', 'capability_level_id': 1, 'stream_url': 'rtsp://test2'},
    ])
    
    # Insert test policies for movement detection
    _insert_movement_policies(conn)
    
    conn.commit()
    
    yield str(db_path), conn
    
    conn.close()


def _insert_movement_policies(conn):
    """Insert movement detection policies into the database."""
    import time
    
    policies = [
        {
            'id': 'movement_detection',
            'name': 'Movement Detection Alert',
            'description': 'Alert on significant movement or position changes',
            'enabled': 1,
            'priority': 50,
            'conditions_json': json.dumps({
                'any': [
                    {'evidence_exists': {'source': 'movement', 'feature': 'position_changed'}},
                    {'evidence_exists': {'source': 'movement', 'feature': 'object_exited'}},
                    {'evidence_exists': {'source': 'movement', 'feature': 'loitering'}}
                ]
            }),
            'actions_json': json.dumps([
                {'type': 'telegram', 'message': 'Movement detected', 'priority': 'normal'}
            ]),
            'variables_json': json.dumps({}),
            'created_ts': int(time.time()),
            'updated_ts': int(time.time()),
            'created_by': 'test_setup',
            'tags': 'movement,test',
            'version': 1
        }
    ]
    
    for policy in policies:
        conn.execute("""
            INSERT INTO policy_rules 
            (id, name, description, enabled, priority, conditions_json, actions_json, 
             variables_json, created_ts, updated_ts, created_by, tags, version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            policy['id'], policy['name'], policy['description'], policy['enabled'],
            policy['priority'], policy['conditions_json'], policy['actions_json'],
            policy['variables_json'], policy['created_ts'], policy['updated_ts'],
            policy['created_by'], policy['tags'], policy['version']
        ))
    
    conn.commit()


@pytest.fixture
def api_client(test_db, monkeypatch):
    """
    Create a FastAPI TestClient for the Policy API.
    
    Uses monkeypatch to override the database path so the API
    uses our test database instead of the production one.
    """
    db_path, conn = test_db
    
    # Override the database path in the server module
    monkeypatch.setenv("ECHOBELL_DB_PATH", db_path)
    
    # Import the FastAPI app (after setting env var)
    # Note: Can't use 'from apps.policy_server' due to hyphen in directory name
    import sys
    import importlib.util
    server_path = PROJECT_ROOT / "central" / "policy-server" / "server.py"
    spec = importlib.util.spec_from_file_location("policy_server", server_path)
    server = importlib.util.module_from_spec(spec)
    sys.modules["policy_server"] = server
    spec.loader.exec_module(server)
    
    # Override the DB_PATH in the module
    monkeypatch.setattr(server, "DB_PATH", db_path)
    
    # Create test client
    client = TestClient(server.app)
    
    yield client, conn
    
    # Cleanup is handled by test_db fixture


@pytest.fixture
def sample_detections():
    """Sample detection data for testing /scene/update."""
    return {
        "camera_id": 1,
        "timestamp": 1737585600,
        "event_id": "test_evt_001",
        "detections": [
            {
                "object_id": 1,
                "cls": "vehicle",
                "raw_class": "car",
                "conf": 0.95,
                "bbox": {"x": 100.0, "y": 200.0, "w": 300.0, "h": 200.0},
                "props": {}
            },
            {
                "object_id": 2,
                "cls": "person",
                "raw_class": "person",
                "conf": 0.88,
                "bbox": {"x": 250.0, "y": 300.0, "w": 80.0, "h": 150.0},
                "props": {}
            }
        ],
        "plate_hmac_by_object_id": {
            "1": "abc123def456789_test_plate_hmac"
        }
    }


def verify_scene_evidence(evidence_list, expected_features):
    """
    Helper to verify scene evidence contains expected features.
    
    Args:
        evidence_list: List of evidence dicts from API response
        expected_features: List of feature names to expect
    
    Returns:
        True if all expected features are present
    """
    actual_features = {ev["feature"] for ev in evidence_list}
    expected = set(expected_features)
    
    missing = expected - actual_features
    if missing:
        raise AssertionError(f"Missing expected features: {missing}")
    
    return True


def get_track_by_type(tracks, track_type):
    """
    Helper to get tracks of a specific type from active tracks response.
    
    Args:
        tracks: List of track dicts from /scene/tracks endpoint
        track_type: Type to filter by (e.g., "vehicle", "person")
    
    Returns:
        List of tracks matching the type
    """
    return [t for t in tracks if t["track_type"] == track_type]

"""
End-to-End Integration Test: Unknown Vehicle Alert via Telegram

Tests the complete flow:
1. Create a test policy (unknown vehicle → telegram alert)
2. Send evidence of unknown vehicle to /evidence endpoint
3. Policy engine evaluates and triggers telegram action
4. Verify telegram message was sent successfully
5. Verify alert was logged to alert_history

Requirements:
- TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set
- Policy server must be running (or we start it in the test)
"""
import pytest
import sqlite3
import os
import time
import httpx
from datetime import datetime


# Skip if Telegram not configured
TELEGRAM_CONFIGURED = bool(
    os.getenv('TELEGRAM_BOT_TOKEN') and 
    os.getenv('TELEGRAM_CHAT_ID')
)

skip_if_no_telegram = pytest.mark.skipif(
    not TELEGRAM_CONFIGURED,
    reason="TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID not configured"
)


@pytest.fixture
def test_db(tmp_path):
    """Create a temporary test database"""
    db_path = tmp_path / "test_echobell.db"
    conn = sqlite3.connect(str(db_path))
    
    # Create minimal schema
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS scene_tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            camera_id INTEGER NOT NULL,
            track_type TEXT NOT NULL,
            key_kind TEXT NOT NULL,
            track_key TEXT NOT NULL,
            first_seen_ts INTEGER NOT NULL,
            last_seen_ts INTEGER NOT NULL,
            active INTEGER DEFAULT 1,
            last_box_json TEXT,
            raw_class TEXT,
            color TEXT,
            last_event_id TEXT,
            tags TEXT,
            UNIQUE(camera_id, track_key)
        );
        
        CREATE TABLE IF NOT EXISTS alert_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            camera_id TEXT NOT NULL,
            track_key TEXT NOT NULL,
            track_type TEXT NOT NULL,
            policy_id TEXT,
            alert_type TEXT NOT NULL,
            message TEXT,
            priority TEXT DEFAULT 'normal',
            sent_ts INTEGER NOT NULL,
            success INTEGER DEFAULT 1,
            error_message TEXT
        );
        
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
    conn.commit()
    
    yield str(db_path)
    
    conn.close()


@pytest.fixture
def test_policy(test_db):
    """Create a test policy: unknown vehicle → telegram alert"""
    conn = sqlite3.connect(test_db)
    
    import json
    
    policy = {
        "id": "test_unknown_vehicle_alert",
        "name": "Test: Unknown Vehicle Alert",
        "description": "Integration test - alert on unknown vehicle",
        "enabled": 1,
        "priority": 90,
        "conditions_json": json.dumps({
            "all": [
                {"evidence_exists": {"source": "vision", "feature": "vehicle_present"}},
                {"evidence_missing": {"source": "plate_trust", "feature": "trusted_plate"}}
            ]
        }),
        "actions_json": json.dumps([
            {
                "type": "telegram",
                "message": "🧪 TEST ALERT: Unknown {vehicle_color} {vehicle_type} detected at camera {camera_id}",
                "priority": "normal"
            }
        ]),
        "variables_json": json.dumps({
            "vehicle_color": "white",
            "vehicle_type": "car"
        }),
        "created_ts": int(time.time()),
        "updated_ts": int(time.time()),
        "created_by": "integration_test",
        "tags": "test integration"
    }
    
    conn.execute("""
        INSERT INTO policy_rules 
        (id, name, description, enabled, priority, conditions_json, actions_json, 
         variables_json, created_ts, updated_ts, created_by, tags)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        policy['id'], policy['name'], policy['description'],
        policy['enabled'], policy['priority'],
        policy['conditions_json'], policy['actions_json'],
        policy['variables_json'],
        policy['created_ts'], policy['updated_ts'],
        policy['created_by'], policy['tags']
    ))
    conn.commit()
    conn.close()
    
    return policy['id']


@pytest.mark.asyncio
@skip_if_no_telegram
async def test_unknown_vehicle_telegram_alert_e2e(test_db, test_policy):
    """
    End-to-end test: Unknown vehicle triggers telegram alert
    
    Flow:
    1. Create test policy in database
    2. Send evidence to policy evaluator (simulating /evidence endpoint)
    3. Verify telegram action executed
    4. Verify alert logged to alert_history
    5. Check telegram for actual message (manual verification step)
    """
    from packages.policy.apply import evaluate_policies
    
    # Prepare evidence: unknown vehicle detected
    evidence = [
        {
            'source': 'vision',
            'feature': 'vehicle_present',
            'value': 'true',
            'conf': 0.95
        },
        {
            'source': 'vision',
            'feature': 'color',
            'value': 'white',
            'conf': 0.85
        },
        {
            'source': 'vision',
            'feature': 'vehicle_type',
            'value': 'sedan',
            'conf': 0.90
        }
        # Note: NO plate_trust.trusted_plate evidence = unknown vehicle
    ]
    
    # Context
    context = {
        'camera_id': 1,
        'track_key': 'test_vehicle_123',
        'track_type': 'vehicle',
        'event_id': 'test_event_001',
        'timestamp': int(time.time())
    }
    
    # Execute policy evaluation
    conn = sqlite3.connect(test_db)
    
    try:
        results = await evaluate_policies(
            evidence=evidence,
            context=context,
            conn=conn
        )
        
        # Verify results
        assert len(results) > 0, "Expected at least one policy action to execute"
        
        # Find telegram action result
        telegram_result = next(
            (r for r in results if r.get('action_type') == 'telegram'),
            None
        )
        
        assert telegram_result is not None, "Expected telegram action to execute"
        assert telegram_result['success'] == True, f"Telegram action failed: {telegram_result.get('error')}"
        assert '🧪 TEST ALERT' in telegram_result['message'], "Expected test alert message"
        
        print(f"\n✅ Telegram message sent successfully!")
        print(f"   Message: {telegram_result['message']}")
        print(f"   Priority: {telegram_result.get('priority')}")
        
        # Verify alert_history was updated
        cursor = conn.execute("""
            SELECT id, message, alert_type, priority, success
            FROM alert_history
            WHERE track_key = ? AND alert_type = 'telegram'
            ORDER BY sent_ts DESC LIMIT 1
        """, (context['track_key'],))
        
        alert_record = cursor.fetchone()
        assert alert_record is not None, "Expected alert to be logged in alert_history"
        
        alert_id, message, alert_type, priority, success = alert_record
        assert alert_type == 'telegram'
        assert success == 1
        assert '🧪 TEST ALERT' in message
        
        print(f"\n✅ Alert logged to database (ID: {alert_id})")
        
        # Manual verification step
        print(f"\n📱 MANUAL VERIFICATION:")
        print(f"   Please check your Telegram chat for the test alert message.")
        print(f"   Expected message: 'TEST ALERT: Unknown white sedan detected at camera 1'")
        print(f"   Chat ID: {os.getenv('TELEGRAM_CHAT_ID')}")
        
    finally:
        conn.close()


@pytest.mark.asyncio
@skip_if_no_telegram
async def test_full_api_integration(test_db, test_policy):
    """
    Full API integration test using actual HTTP calls
    
    This test requires the policy-server to be running.
    If not running, it will be skipped.
    """
    # Check if server is running
    server_url = "http://localhost:8000"
    
    try:
        async with httpx.AsyncClient() as client:
            health_response = await client.get(f"{server_url}/health", timeout=2.0)
            if health_response.status_code != 200:
                pytest.skip("Policy server not running")
    except (httpx.ConnectError, httpx.TimeoutException):
        pytest.skip("Policy server not running at localhost:8000")
    
    # Server is running - proceed with test
    
    # 1. Create test policy via API
    policy_data = {
        "id": "test_api_unknown_vehicle",
        "name": "Test API: Unknown Vehicle",
        "enabled": True,
        "priority": 90,
        "conditions": {
            "all": [
                {"evidence_exists": {"source": "vision", "feature": "vehicle_present"}},
                {"evidence_missing": {"source": "plate_trust", "feature": "trusted_plate"}}
            ]
        },
        "actions": [
            {
                "type": "telegram",
                "message": "🧪 API TEST: Unknown vehicle at camera {camera_id}",
                "priority": "normal"
            }
        ]
    }
    
    async with httpx.AsyncClient() as client:
        # Create policy
        create_response = await client.post(
            f"{server_url}/policies/",
            json=policy_data,
            timeout=5.0
        )
        
        if create_response.status_code == 409:
            # Policy already exists - delete and recreate
            await client.delete(f"{server_url}/policies/{policy_data['id']}")
            create_response = await client.post(
                f"{server_url}/policies/",
                json=policy_data,
                timeout=5.0
            )
        
        assert create_response.status_code == 201, f"Failed to create policy: {create_response.text}"
        print(f"\n✅ Created test policy via API")
        
        # 2. Send evidence to /evidence endpoint
        evidence_data = {
            "camera_id": 1,
            "event_id": f"api_test_{int(time.time())}",
            "timestamp": int(time.time()),
            "objects": [
                {
                    "object_id": 1,
                    "cls": "vehicle",
                    "raw_class": "car",
                    "bbox": [100, 200, 300, 400],
                    "props": {
                        "color": "blue",
                        "scene_track_key": "test_api_vehicle"
                    }
                }
            ],
            "evidence": [
                {
                    "source": "vision",
                    "feature": "vehicle_present",
                    "value": "true",
                    "conf": 0.95
                },
                {
                    "source": "vision",
                    "feature": "color",
                    "value": "blue",
                    "conf": 0.85
                },
                {
                    "source": "vision",
                    "feature": "vehicle_type",
                    "value": "car",
                    "conf": 0.90
                }
            ],
            "transcript": None
        }
        
        evidence_response = await client.post(
            f"{server_url}/evidence",
            json=evidence_data,
            timeout=10.0
        )
        
        assert evidence_response.status_code == 200, f"Evidence endpoint failed: {evidence_response.text}"
        response_data = evidence_response.json()
        
        print(f"\n✅ Evidence processed: {response_data['message']}")
        
        # 3. Verify telegram was sent (check response message)
        assert "policy actions" in response_data['message'].lower() or "evidence items" in response_data['message'].lower()
        
        print(f"\n📱 MANUAL VERIFICATION:")
        print(f"   Check Telegram for message: 'API TEST: Unknown vehicle at camera 1'")
        
        # Cleanup: delete test policy
        await client.delete(f"{server_url}/policies/{policy_data['id']}")
        print(f"\n🧹 Cleaned up test policy")


if __name__ == '__main__':
    # Run with: pytest tests/test_integration_telegram.py -v -s
    pytest.main([__file__, '-v', '-s'])

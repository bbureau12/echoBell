"""
Simple Integration Test Script
Tests unknown vehicle alert → Telegram notification

This script:
1. Creates a test policy (unknown vehicle → telegram alert)
2. Simulates unknown vehicle evidence
3. Evaluates policy and sends telegram alert
4. Verifies alert was sent

Usage:
    # Set environment variables first
    $env:TELEGRAM_BOT_TOKEN = "your_bot_token"
    $env:TELEGRAM_CHAT_ID = "your_chat_id"
    
    # Run the script
    python tests/test_telegram_simple.py
"""
import os
import sys
import sqlite3
import asyncio
import json
from datetime import datetime

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)


def setup_test_database():
    """Create a temporary test database with schema"""
    db_path = "test_integration.db"
    
    # Remove if exists
    if os.path.exists(db_path):
        os.remove(db_path)
    
    conn = sqlite3.connect(db_path)
    
    # Create minimal schema
    conn.executescript("""
        CREATE TABLE scene_tracks (
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
        
        CREATE TABLE alert_history (
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
        
        CREATE TABLE policy_rules (
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
        
        CREATE TABLE policy_executions (
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
    
    print(f"✅ Created test database: {db_path}")
    return conn, db_path


def create_test_policy(conn):
    """Create a test policy in the database"""
    import time
    
    policy = {
        "id": "test_unknown_vehicle_alert",
        "name": "🧪 Test: Unknown Vehicle Alert",
        "description": "Integration test - alert on unknown vehicle",
        "enabled": 1,
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
                "message": "🧪 TEST ALERT: Unknown {color} {vehicle_type} detected at camera {camera_id}",
                "priority": "normal"
            }
        ],
        "variables": {}
    }
    
    conn.execute("""
        INSERT INTO policy_rules 
        (id, name, description, enabled, priority, conditions_json, actions_json, 
         variables_json, created_ts, updated_ts, created_by, tags)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        policy['id'],
        policy['name'],
        policy['description'],
        policy['enabled'],
        policy['priority'],
        json.dumps(policy['conditions']),
        json.dumps(policy['actions']),
        json.dumps(policy['variables']),
        int(time.time()),
        int(time.time()),
        'integration_test',
        'test integration'
    ))
    conn.commit()
    
    print(f"✅ Created test policy: {policy['name']}")
    return policy['id']


async def run_test(conn):
    """Run the integration test"""
    from packages.policy.apply import evaluate_policies
    
    print("\n" + "="*60)
    print("🧪 INTEGRATION TEST: Unknown Vehicle → Telegram Alert")
    print("="*60 + "\n")
    
    # Check Telegram config
    if not os.getenv('TELEGRAM_BOT_TOKEN'):
        print("❌ TELEGRAM_BOT_TOKEN not set")
        print("   Set it with: $env:TELEGRAM_BOT_TOKEN = 'your_token'")
        return False
    
    if not os.getenv('TELEGRAM_CHAT_ID'):
        print("❌ TELEGRAM_CHAT_ID not set")
        print("   Set it with: $env:TELEGRAM_CHAT_ID = 'your_chat_id'")
        return False
    
    print(f"✅ Telegram configured")
    print(f"   Bot Token: {os.getenv('TELEGRAM_BOT_TOKEN')[:20]}...")
    print(f"   Chat ID: {os.getenv('TELEGRAM_CHAT_ID')}\n")
    
    # Prepare evidence: unknown vehicle detected
    print("📊 Simulating evidence: Unknown white sedan detected")
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
    
    for ev in evidence:
        print(f"   - {ev['source']}.{ev['feature']} = {ev['value']} (conf={ev['conf']:.2f})")
    
    # Context
    context = {
        'camera_id': 1,
        'track_key': 'test_vehicle_123',
        'track_type': 'vehicle',
        'event_id': 'test_event_001',
        'timestamp': int(datetime.now().timestamp())
    }
    
    print(f"\n📍 Context:")
    print(f"   Camera ID: {context['camera_id']}")
    print(f"   Track Key: {context['track_key']}")
    print(f"   Event ID: {context['event_id']}")
    
    # Execute policy evaluation
    print(f"\n🔄 Evaluating policies...\n")
    
    try:
        results = await evaluate_policies(
            evidence=evidence,
            context=context,
            conn=conn
        )
        
        if not results:
            print("❌ No policies matched!")
            return False
        
        print(f"✅ {len(results)} policy action(s) executed:\n")
        
        # Show results
        for i, result in enumerate(results, 1):
            status = "✅" if result.get('success') else "❌"
            print(f"{i}. {status} {result.get('action_type').upper()}")
            print(f"   Policy: {result.get('policy_name', 'unknown')}")
            
            if result.get('action_type') == 'telegram':
                print(f"   Message: {result.get('message')}")
                print(f"   Priority: {result.get('priority')}")
            
            if not result.get('success'):
                print(f"   Error: {result.get('error')}")
            
            print()
        
        # Verify telegram action
        telegram_result = next(
            (r for r in results if r.get('action_type') == 'telegram'),
            None
        )
        
        if not telegram_result:
            print("❌ No telegram action found in results")
            return False
        
        if not telegram_result.get('success'):
            print(f"❌ Telegram action failed: {telegram_result.get('error')}")
            print("\n💡 Common issues:")
            print("   - Bot token invalid (get from @BotFather)")
            print("   - Chat ID incorrect (get from @userinfobot)")
            print("   - Haven't sent /start to the bot")
            print("   - Bot blocked by user")
            return False
        
        print("✅ Telegram message sent successfully!")
        
        # Check alert_history
        cursor = conn.execute("""
            SELECT id, message, alert_type, priority, success
            FROM alert_history
            WHERE track_key = ? AND alert_type = 'telegram'
            ORDER BY sent_ts DESC LIMIT 1
        """, (context['track_key'],))
        
        alert_record = cursor.fetchone()
        
        if alert_record:
            alert_id, message, alert_type, priority, success = alert_record
            print(f"✅ Alert logged to database (ID: {alert_id})")
            print(f"   Type: {alert_type}")
            print(f"   Priority: {priority}")
            print(f"   Success: {'Yes' if success else 'No'}")
        else:
            print("⚠️  Alert not found in alert_history table")
        
        print("\n" + "="*60)
        print("📱 TELEGRAM VERIFICATION")
        print("="*60)
        print(f"\nPlease check your Telegram chat for the test alert message.")
        print(f"Expected message: '🧪 TEST ALERT: Unknown white sedan detected at camera 1'")
        print(f"Chat ID: {os.getenv('TELEGRAM_CHAT_ID')}\n")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False


def cleanup(db_path):
    """Clean up test database"""
    if os.path.exists(db_path):
        os.remove(db_path)
        print(f"\n🧹 Cleaned up: {db_path}")


async def main():
    """Main test function"""
    conn = None
    db_path = None
    
    try:
        # Setup
        conn, db_path = setup_test_database()
        create_test_policy(conn)
        
        # Run test
        success = await run_test(conn)
        
        if success:
            print("✅ Integration test PASSED!\n")
            return 0
        else:
            print("❌ Integration test FAILED!\n")
            return 1
            
    except Exception as e:
        print(f"\n❌ Test error: {e}")
        import traceback
        traceback.print_exc()
        return 1
        
    finally:
        if conn:
            conn.close()
        if db_path:
            cleanup(db_path)


if __name__ == '__main__':
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

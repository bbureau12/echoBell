"""
Test script to verify MCP server tools with real database.

This tests the actual service layer functions that MCP tools call.
Each test function corresponds to an MCP tool:

MCP Tools Tested:
- list_policies        → services.list_policies()
- get_active_tracks    → services.get_active_tracks()
- list_events          → services.list_scheduled_events()
- active_events_now    → services.get_active_events()
- evaluate_policy      → services.evaluate_policy_conditions()
- query_scene_context  → services.query_scene_context()

REQUIREMENTS:
- Requires a database with proper schema at echoBell.db
- Set ECHOBELL_DB_PATH environment variable to use different database

ALTERNATIVE:
For automated unit tests with auto-created test database:
    pytest tests/test_service_layer.py -v

This script is best for:
- Testing against production/development database
- Manual verification of MCP tool behavior
- Debugging with real data
"""
import os
import sys
import sqlite3
import json
from datetime import datetime

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "apps", "policy-server"))

# Import service layer (what MCP tools actually use)
import services
from packages.policy.evaluator import PolicyEvaluator


def get_db_path() -> str:
    """Get database path from environment or use default"""
    return os.getenv("ECHOBELL_DB_PATH", os.path.join(PROJECT_ROOT, "echoBell.db"))


def test_list_policies():
    """Test MCP tool: list_policies"""
    print("\n=== Test: list_policies (MCP Tool) ===")
    try:
        db_path = get_db_path()
        conn = sqlite3.connect(db_path)
        
        # Call service function (same as MCP tool does)
        policies = services.list_policies(conn, status="active")
        
        print(f"✓ Found {len(policies)} active policies")
        for p in policies[:3]:  # Show first 3
            print(f"  - {p['id']}: {p['name']} (priority={p['priority']}, status={p['status']})")
        
        conn.close()
        return True
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_get_active_tracks():
    """Test MCP tool: get_active_tracks"""
    print("\n=== Test: get_active_tracks (MCP Tool) ===")
    try:
        db_path = get_db_path()
        conn = sqlite3.connect(db_path)
        
        # Call service function (same as MCP tool does)
        tracks = services.get_active_tracks(conn, camera_id=1)
        
        print(f"✓ Found {len(tracks)} active tracks")
        now = int(datetime.now().timestamp())
        for track in tracks[:5]:
            age = now - track['last_seen_ts']
            print(f"  - {track['track_key']}: {track['track_type']} (age={age}s)")
        
        conn.close()
        return True
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_scheduled_events():
    """Test MCP tools: list_events, create_event, active_events_now"""
    print("\n=== Test: Scheduled Events (MCP Tools) ===")
    try:
        db_path = get_db_path()
        conn = sqlite3.connect(db_path)
        
        # Test list_scheduled_events (MCP tool: list_events)
        events = services.list_scheduled_events(conn)
        print(f"✓ list_events: Found {len(events)} scheduled events")
        for event in events[:3]:
            start = datetime.fromtimestamp(event['start_ts']).strftime('%Y-%m-%d %H:%M')
            end = datetime.fromtimestamp(event['end_ts']).strftime('%Y-%m-%d %H:%M')
            print(f"  - {event['name']}: {start} to {end} (hint={event.get('policy_hint', '')})")
        
        # Test get_active_events (MCP tool: active_events_now)
        now = int(datetime.now().timestamp())
        active = services.get_active_events(conn, timestamp=now)
        print(f"✓ active_events_now: {len(active)} events active right now")
        for event in active:
            print(f"  - {event['name']} (hint={event.get('policy_hint', '')})")
        
        conn.close()
        return True
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_policy_evaluation():
    """Test MCP tool: evaluate_policy"""
    print("\n=== Test: evaluate_policy (MCP Tool) ===")
    try:
        db_path = get_db_path()
        conn = sqlite3.connect(db_path)
        
        # Get a policy to test
        policies = services.list_policies(conn, status="active")
        if not policies:
            print("! No active policies found to test")
            conn.close()
            return True
        
        policy_id = policies[0]['id']
        policy_name = policies[0]['name']
        
        # Test evidence
        evidence = [
            {"source": "vision", "feature": "label", "value": "person", "conf": 0.95},
            {"source": "vision", "feature": "color", "value": "blue", "conf": 0.80}
        ]
        
        # Call service function (same as MCP tool does)
        result = services.evaluate_policy_conditions(
            conn=conn,
            policy_id=policy_id,
            evidence=evidence
        )
        
        print(f"✓ Evaluated policy '{policy_name}' (ID={policy_id})")
        print(f"  Matched: {result['matched']}")
        print(f"  Evidence count: {result['evaluation_details']['evidence_count']}")
        
        conn.close()
        return True
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_scene_context():
    """Test MCP tool: query_scene_context"""
    print("\n=== Test: query_scene_context (MCP Tool) ===")
    try:
        db_path = get_db_path()
        conn = sqlite3.connect(db_path)
        
        # Call service function (same as MCP tool does)
        context = services.query_scene_context(
            conn=conn,
            camera_id=1,
            time_range_s=300  # Last 5 minutes
        )
        
        print(f"✓ Got scene context for camera {context['camera_id']}")
        print(f"  Active tracks: {len(context['active_tracks'])}")
        print(f"  Recent alerts: {len(context['recent_alerts'])}")
        print(f"  Visit history: {len(context['visit_history'])}")
        
        # Show some details
        for track in context['active_tracks'][:3]:
            print(f"    - {track['track_key']}: {track['track_type']}")
        
        conn.close()
        return True
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests"""
    print("="*60)
    print("MCP Server Tool Tests (via Service Layer)")
    print("="*60)
    
    # Check database exists and has required tables
    db_path = get_db_path()
    print(f"\nDatabase: {db_path}")
    
    if not os.path.exists(db_path):
        print(f"✗ ERROR: Database not found at {db_path}")
        print("\nTo run these tests, you need a database with the proper schema.")
        print("For unit tests with auto-created database, use:")
        print("    pytest tests/test_service_layer.py -v")
        return 1
    
    # Check for required tables
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    conn.close()
    
    required_tables = {'policy_rules', 'scene_tracks', 'scheduled_event', 'alert_history'}
    missing_tables = required_tables - tables
    
    if missing_tables:
        print(f"✗ ERROR: Database missing required tables: {missing_tables}")
        print(f"  Found tables: {tables}")
        print("\nFor unit tests with auto-created database, use:")
        print("    pytest tests/test_service_layer.py -v")
        return 1
    
    print(f"✓ Database has all required tables")
    
    tests = [
        ("list_policies", test_list_policies),
        ("get_active_tracks", test_get_active_tracks),
        ("Scheduled Events (list_events, active_events_now)", test_scheduled_events),
        ("evaluate_policy", test_policy_evaluation),
        ("query_scene_context", test_scene_context)
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n✗ Test '{name}' crashed: {e}")
            results.append((name, False))
    
    print("\n" + "="*60)
    print("Test Summary")
    print("="*60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Test script for Visitor Intent Reclassification API

Tests the /visitors/* endpoints including:
1. Get visitor event details
2. Reclassify with evidence injection
3. Reclassify with direct override
4. Query events with filters
5. Reclassification history tracking
6. Audit trail validation
7. Error handling
"""

import sys
import os
import requests
import json
import time
import sqlite3

# Configuration
BASE_URL = os.getenv("POLICY_SERVER_URL", "http://localhost:8000")
DB_PATH = os.getenv("ECHOBELL_DB_PATH", "echoBell.db")

def print_section(title):
    """Print a section header"""
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")

def setup_test_visitor_event():
    """Create a test visitor event in the database"""
    print("Setting up test visitor event...")
    
    conn = sqlite3.connect(DB_PATH)
    
    # Create a test visitor event
    event_id = f"test-visitor-{int(time.time())}"
    now_ts = int(time.time())
    
    evidence_json = json.dumps({
        "objects": [
            {"object_id": 1, "label": "person", "conf": 0.95, "box": [100, 200, 300, 400]},
            {"object_id": 2, "label": "car", "conf": 0.88, "box": [50, 150, 350, 450]}
        ],
        "evidence": [
            {"source": "vision", "key": "person_present", "value": "true", "confidence": 0.95},
            {"source": "vision", "key": "vehicle_present", "value": "true", "confidence": 0.88}
        ]
    })
    
    conn.execute("""
        INSERT INTO visitor_events (
            event_id, camera_id, detected_ts, intent_inferred, 
            intent_confidence, evidence_json, urgency
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (event_id, 1, now_ts, "stranger", 0.65, evidence_json, "medium"))
    
    conn.commit()
    conn.close()
    
    print(f"✓ Created test event: {event_id}")
    return event_id


def test_get_visitor_event(event_id):
    """Test retrieving visitor event details"""
    print_section("Test 1: Get Visitor Event")
    
    print(f"Fetching event {event_id}...")
    response = requests.get(f"{BASE_URL}/visitors/events/{event_id}")
    
    if response.status_code == 200:
        print("✓ Event retrieved successfully")
        event = response.json()
        print(f"  Event ID: {event['event_id']}")
        print(f"  Intent: {event['intent_inferred']} (confidence: {event['intent_confidence']})")
        print(f"  Urgency: {event['urgency']}")
        print(f"  Evidence items: {len(event.get('evidence', []))}")
        if event.get('reclassification_count', 0) > 0:
            print(f"  Reclassified: {event['reclassification_count']} time(s)")
        print("\nFull event:")
        print(json.dumps(event, indent=2))
        return True
    else:
        print(f"✗ Failed to get event: {response.status_code}")
        print(response.text)
        return False


def test_reclassify_evidence_injection(event_id):
    """Test reclassifying with evidence injection"""
    print_section("Test 2: Reclassify with Evidence Injection")
    
    print("Adding evidence that person is wearing UPS uniform...")
    response = requests.post(
        f"{BASE_URL}/visitors/events/{event_id}/reclassify",
        json={
            "additional_evidence": [
                {
                    "source": "llm",
                    "key": "uniform_type",
                    "value": "ups",
                    "confidence": 0.90
                },
                {
                    "source": "llm", 
                    "key": "carrying_package",
                    "value": "true",
                    "confidence": 0.85
                }
            ],
            "reason": "LLM observed UPS uniform in image",
            "reclassified_by": "test_llm"
        }
    )
    
    if response.status_code == 200:
        result = response.json()
        print("✓ Reclassification successful")
        print(f"  Method: {result.get('method')}")
        print(f"  Changed: {result.get('changed')}")
        print(f"  Original: {result['original_intent']} (conf={result['original_confidence']:.2f})")
        print(f"  New: {result['new_intent']} (conf={result['new_confidence']:.2f})")
        print(f"  Reclassified by: {result.get('reclassified_by')}")
        print(f"  Reason: {result.get('reason')}")
        
        if result.get('trace'):
            print(f"\nClassification trace:")
            for line in result['trace']:
                print(f"    {line}")
        
        print("\nFull response:")
        print(json.dumps(result, indent=2))
        return True
    else:
        print(f"✗ Failed to reclassify: {response.status_code}")
        print(response.text)
        return False


def test_reclassify_direct_override(event_id):
    """Test reclassifying with direct intent override"""
    print_section("Test 3: Reclassify with Direct Override")
    
    print("Directly overriding intent to 'delivery_arriving'...")
    response = requests.post(
        f"{BASE_URL}/visitors/events/{event_id}/reclassify",
        json={
            "override_intent": "delivery_arriving",
            "override_confidence": 0.98,
            "reason": "Manual correction - confirmed UPS delivery",
            "reclassified_by": "test_admin"
        }
    )
    
    if response.status_code == 200:
        result = response.json()
        print("✓ Override successful")
        print(f"  Method: {result.get('method')}")
        print(f"  Changed: {result.get('changed')}")
        print(f"  Original: {result['original_intent']} (conf={result['original_confidence']:.2f})")
        print(f"  New: {result['new_intent']} (conf={result['new_confidence']:.2f})")
        
        if result['method'] == 'direct_override':
            print("  ✓ Correctly used direct override method")
        
        print("\nFull response:")
        print(json.dumps(result, indent=2))
        return True
    else:
        print(f"✗ Failed to override: {response.status_code}")
        print(response.text)
        return False


def test_reclassification_history(event_id):
    """Test fetching reclassification history"""
    print_section("Test 4: Reclassification History")
    
    print(f"Fetching history for event {event_id}...")
    response = requests.get(f"{BASE_URL}/visitors/events/{event_id}/reclassification_history")
    
    if response.status_code == 200:
        history = response.json()
        print("✓ History retrieved successfully")
        print(f"  Event ID: {history.get('event_id')}")
        print(f"  Current Intent: {history.get('current_intent')} (conf={history.get('current_confidence', 0):.2f})")
        print(f"  Reclassification Count: {history.get('reclassification_count', 0)}")
        
        if history.get('reclassified_by'):
            print(f"  Last Reclassified By: {history['reclassified_by']}")
        if history.get('reclassification_reason'):
            print(f"  Last Reason: {history['reclassification_reason']}")
        if history.get('reclassified_ts'):
            print(f"  Last Timestamp: {history['reclassified_ts']}")
        
        print("\nFull history:")
        print(json.dumps(history, indent=2))
        return True
    else:
        print(f"✗ Failed to get history: {response.status_code}")
        print(response.text)
        return False


def test_query_events_with_filters():
    """Test querying visitor events with filters"""
    print_section("Test 5: Query Events with Filters")
    
    # Test 1: Get all events
    print("Querying all events...")
    response = requests.get(f"{BASE_URL}/visitors/events")
    
    if response.status_code == 200:
        events = response.json()
        print(f"✓ Found {len(events)} total event(s)")
        for event in events[:3]:  # Show first 3
            print(f"  - {event['event_id']}: {event['intent_inferred']} (conf={event['intent_confidence']:.2f})")
    else:
        print(f"✗ Failed to query events: {response.status_code}")
        return False
    
    # Test 2: Filter by intent
    print("\nQuerying events with intent='delivery_arriving'...")
    response = requests.get(f"{BASE_URL}/visitors/events?intent=delivery_arriving")
    
    if response.status_code == 200:
        events = response.json()
        print(f"✓ Found {len(events)} delivery event(s)")
        for event in events[:3]:
            print(f"  - {event['event_id']}: {event['intent_inferred']}")
    else:
        print(f"✗ Failed to filter by intent: {response.status_code}")
        return False
    
    # Test 3: Filter by reclassified
    print("\nQuerying reclassified events...")
    response = requests.get(f"{BASE_URL}/visitors/events?reclassified_only=true")
    
    if response.status_code == 200:
        events = response.json()
        print(f"✓ Found {len(events)} reclassified event(s)")
        for event in events[:3]:
            print(f"  - {event['event_id']}: reclassified {event.get('reclassification_count', 0)} time(s)")
    else:
        print(f"✗ Failed to filter reclassified: {response.status_code}")
        return False
    
    # Test 4: Limit results
    print("\nQuerying with limit=2...")
    response = requests.get(f"{BASE_URL}/visitors/events?limit=2")
    
    if response.status_code == 200:
        events = response.json()
        print(f"✓ Found {len(events)} event(s) (limit applied)")
        if len(events) <= 2:
            print("  ✓ Limit correctly enforced")
        else:
            print(f"  ✗ Expected max 2 events, got {len(events)}")
            return False
    else:
        print(f"✗ Failed to limit results: {response.status_code}")
        return False
    
    return True


def test_error_handling():
    """Test error handling scenarios"""
    print_section("Test 6: Error Handling")
    
    # Test 1: Non-existent event
    print("Testing non-existent event...")
    response = requests.get(f"{BASE_URL}/visitors/events/does-not-exist")
    
    if response.status_code == 404:
        print("✓ Correctly returned 404 for non-existent event")
    else:
        print(f"✗ Expected 404, got {response.status_code}")
        return False
    
    # Test 2: Override without confidence
    print("\nTesting override without confidence...")
    setup_event = setup_test_visitor_event()
    
    response = requests.post(
        f"{BASE_URL}/visitors/events/{setup_event}/reclassify",
        json={
            "override_intent": "delivery_arriving"
            # Missing override_confidence
        }
    )
    
    if response.status_code in [400, 422]:
        print(f"✓ Correctly rejected override without confidence ({response.status_code})")
    else:
        print(f"✗ Expected 400/422, got {response.status_code}")
        return False
    
    # Test 3: Neither evidence nor override
    print("\nTesting request with neither evidence nor override...")
    response = requests.post(
        f"{BASE_URL}/visitors/events/{setup_event}/reclassify",
        json={
            "reason": "This should fail"
        }
    )
    
    if response.status_code in [400, 422]:
        print(f"✓ Correctly rejected empty reclassification ({response.status_code})")
    else:
        print(f"✗ Expected 400/422, got {response.status_code}")
        return False
    
    return True


def test_audit_trail_verification(event_id):
    """Test that audit trail is properly maintained"""
    print_section("Test 7: Audit Trail Verification")
    
    print("Verifying audit trail in database...")
    conn = sqlite3.connect(DB_PATH)
    
    cursor = conn.execute("""
        SELECT event_id, intent_inferred, intent_confidence,
               reclassification_count, reclassified_by, 
               reclassification_reason, reclassified_ts
        FROM visitor_events
        WHERE event_id = ?
    """, (event_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        print(f"✗ Event {event_id} not found in database")
        return False
    
    (db_event_id, intent, confidence, reclass_count, 
     reclass_by, reclass_reason, reclass_ts) = row
    
    print(f"✓ Event found in database")
    print(f"  Intent: {intent} (confidence: {confidence})")
    print(f"  Reclassification count: {reclass_count}")
    print(f"  Reclassified by: {reclass_by}")
    print(f"  Reason: {reclass_reason}")
    print(f"  Timestamp: {reclass_ts}")
    
    # Verify audit fields are populated
    if reclass_count and reclass_count > 0:
        print("\n✓ Reclassification count is tracked")
        
        if reclass_by:
            print(f"✓ 'Reclassified by' is recorded: {reclass_by}")
        else:
            print("✗ 'Reclassified by' is missing")
            return False
        
        if reclass_reason:
            print(f"✓ 'Reclassification reason' is recorded")
        else:
            print("✗ 'Reclassification reason' is missing")
            return False
        
        if reclass_ts:
            print(f"✓ 'Reclassification timestamp' is recorded")
        else:
            print("✗ 'Reclassification timestamp' is missing")
            return False
        
        return True
    else:
        print("⚠ Event has not been reclassified yet")
        return True


def main():
    """Run all tests"""
    print(f"""
    ╔═══════════════════════════════════════════════════════════════════╗
    ║  Visitor Intent Reclassification API Test Suite                  ║
    ║  Testing: {BASE_URL:50s}  ║
    ║  Database: {DB_PATH:47s}  ║
    ╚═══════════════════════════════════════════════════════════════════╝
    """)
    
    # Setup test data
    try:
        test_event_id = setup_test_visitor_event()
    except Exception as e:
        print(f"✗ Failed to set up test data: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    tests = [
        ("Get Visitor Event", lambda: test_get_visitor_event(test_event_id)),
        ("Reclassify with Evidence Injection", lambda: test_reclassify_evidence_injection(test_event_id)),
        ("Get Event After Reclassification", lambda: test_get_visitor_event(test_event_id)),
        ("Reclassify with Direct Override", lambda: test_reclassify_direct_override(test_event_id)),
        ("Reclassification History", lambda: test_reclassification_history(test_event_id)),
        ("Query Events with Filters", test_query_events_with_filters),
        ("Error Handling", test_error_handling),
        ("Audit Trail Verification", lambda: test_audit_trail_verification(test_event_id)),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n✗ Test '{name}' failed with exception: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))
    
    # Print summary
    print_section("Test Summary")
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {status}: {name}")
    
    print(f"\n  Total: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n  🎉 All tests passed!")
        return 0
    else:
        print(f"\n  ⚠️  {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())

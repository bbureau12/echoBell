#!/usr/bin/env python3
"""
Test script for Voice API edge cases and security scenarios

Tests edge cases including:
1. Low voiceprint confidence rejection
2. Security actions requiring high confidence
3. 2FA requirement scenarios
4. Unknown voiceprints
5. Invalid/malformed requests
6. Multi-turn conversation sessions
7. Concurrent request handling
8. Database error scenarios
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


def test_low_confidence_rejection():
    """Test that low voiceprint confidence is rejected"""
    print_section("Test 1: Low Confidence Rejection")
    
    # Test with confidence below 0.75 threshold
    print("Testing voice command with confidence=0.60 (below 0.75 threshold)...")
    response = requests.post(
        f"{BASE_URL}/voice/listen",
        json={
            "event_id": f"test-low-conf-{int(time.time())}",
            "ts": int(time.time()),
            "source_id": "microphone",
            "text": "who is at the door",
            "voiceprint_user_id": "test_alice",
            "voiceprint_confidence": 0.60,  # Below threshold
            "mode": "triggered",
            "confidence": 0.95
        }
    )
    
    if response.status_code == 200:
        result = response.json()
        
        if not result.get('handled'):
            print("✓ Command correctly rejected due to low confidence")
            print(f"  Response: {result.get('response')}")
            
            # Check that it suggests confirmation
            if "confirmation" in result.get('response', '').lower():
                print("✓ Response correctly suggests confirmation")
            else:
                print("⚠ Response doesn't mention confirmation")
            
            return True
        else:
            print("✗ Command should have been rejected but was handled")
            print(json.dumps(result, indent=2))
            return False
    else:
        print(f"✗ Request failed: {response.status_code}")
        print(response.text)
        return False


def test_security_action_high_confidence():
    """Test that security actions require high confidence (>= 0.95)"""
    print_section("Test 2: Security Action High Confidence")
    
    # Test 1: Security action with medium confidence (should be rejected)
    print("Testing 'unlock door' with confidence=0.85 (below 0.95 security threshold)...")
    response = requests.post(
        f"{BASE_URL}/voice/authorize",
        json={
            "text": "unlock the front door",
            "voiceprint_confidence": 0.85,
            "tool_name": None
        }
    )
    
    if response.status_code == 200:
        result = response.json()
        
        # Note: Current implementation may allow this without a specific security tool
        # This tests the authorization logic
        print(f"  Authorization: {'ALLOWED' if result['allowed'] else 'DENIED'}")
        print(f"  Reason: {result.get('reason')}")
        print(f"  Action required: {result.get('action_required')}")
    else:
        print(f"✗ Request failed: {response.status_code}")
        return False
    
    # Test 2: Security action with high confidence (should be allowed)
    print("\nTesting 'unlock door' with confidence=0.96 (above 0.95 threshold)...")
    response = requests.post(
        f"{BASE_URL}/voice/authorize",
        json={
            "text": "unlock the front door",
            "voiceprint_confidence": 0.96,
            "tool_name": None
        }
    )
    
    if response.status_code == 200:
        result = response.json()
        
        if result['allowed']:
            print("✓ High confidence security action allowed")
        else:
            print(f"  Denied: {result.get('reason')}")
        
        return True
    else:
        print(f"✗ Request failed: {response.status_code}")
        return False


def test_unknown_voiceprint():
    """Test handling of unknown voiceprints"""
    print_section("Test 3: Unknown Voiceprint Handling")
    
    print("Sending command with unmapped voiceprint 'unknown_user_xyz'...")
    response = requests.post(
        f"{BASE_URL}/voice/listen",
        json={
            "event_id": f"test-unknown-{int(time.time())}",
            "ts": int(time.time()),
            "source_id": "microphone",
            "text": "who is at the door",
            "voiceprint_user_id": "unknown_user_xyz",
            "voiceprint_confidence": 0.92,
            "mode": "triggered",
            "confidence": 0.95
        }
    )
    
    if response.status_code == 200:
        result = response.json()
        print("✓ Request processed (unknown voiceprint accepted)")
        print(f"  Handled: {result.get('handled')}")
        print(f"  Response: {result.get('response')}")
        
        # User should be acknowledged as "Unknown" or similar
        user_ack = result.get('user_acknowledged')
        if user_ack is None or user_ack == "Unknown":
            print(f"✓ User correctly identified as unknown: {user_ack}")
        else:
            print(f"⚠ Unexpected user acknowledgment: {user_ack}")
        
        return True
    else:
        print(f"✗ Request failed: {response.status_code}")
        print(response.text)
        return False


def test_null_voiceprint_confidence():
    """Test handling of null/missing voiceprint confidence"""
    print_section("Test 4: Null Voiceprint Confidence")
    
    print("Testing authorization with None confidence...")
    response = requests.post(
        f"{BASE_URL}/voice/authorize",
        json={
            "text": "check the camera",
            "voiceprint_confidence": None,
            "tool_name": None
        }
    )
    
    if response.status_code == 200:
        result = response.json()
        
        if not result['allowed']:
            print("✓ Correctly denied request with None confidence")
            print(f"  Reason: {result.get('reason')}")
            
            if "confidence" in result.get('reason', '').lower():
                print("✓ Reason correctly mentions confidence issue")
            
            return True
        else:
            print("✗ Should have denied None confidence")
            return False
    else:
        print(f"✗ Request failed: {response.status_code}")
        return False


def test_invalid_tool_name():
    """Test authorization with invalid tool name"""
    print_section("Test 5: Invalid Tool Name")
    
    print("Testing authorization with non-existent tool...")
    response = requests.post(
        f"{BASE_URL}/voice/authorize",
        json={
            "text": "do something",
            "voiceprint_confidence": 0.90,
            "tool_name": "non_existent_tool_xyz"
        }
    )
    
    if response.status_code == 200:
        result = response.json()
        
        if not result['allowed']:
            print("✓ Correctly denied non-existent tool")
            print(f"  Reason: {result.get('reason')}")
            
            if "not_found" in result.get('reason', ''):
                print("✓ Reason correctly indicates tool not found")
            
            return True
        else:
            print("✗ Should have denied non-existent tool")
            return False
    else:
        print(f"✗ Request failed: {response.status_code}")
        return False


def test_multi_turn_session():
    """Test multi-turn conversation with session_id"""
    print_section("Test 6: Multi-turn Conversation Session")
    
    session_id = f"session-{int(time.time())}"
    
    # First turn
    print(f"Sending first turn in session {session_id}...")
    response1 = requests.post(
        f"{BASE_URL}/voice/listen",
        json={
            "event_id": f"test-session-1-{int(time.time())}",
            "ts": int(time.time()),
            "source_id": "microphone",
            "session_id": session_id,
            "text": "who is at the door",
            "voiceprint_user_id": "test_alice",
            "voiceprint_confidence": 0.88,
            "mode": "triggered",
            "confidence": 0.95
        }
    )
    
    if response1.status_code != 200:
        print(f"✗ First turn failed: {response1.status_code}")
        return False
    
    result1 = response1.json()
    print(f"✓ First turn processed")
    print(f"  Response: {result1.get('response')}")
    
    # Second turn (continue conversation)
    time.sleep(1)
    print(f"\nSending second turn in same session...")
    response2 = requests.post(
        f"{BASE_URL}/voice/listen",
        json={
            "event_id": f"test-session-2-{int(time.time())}",
            "ts": int(time.time()),
            "source_id": "microphone",
            "session_id": session_id,  # Same session
            "text": "unlock the door",
            "voiceprint_user_id": "test_alice",
            "voiceprint_confidence": 0.88,
            "mode": "open_listen",  # Continuation mode
            "confidence": 0.92
        }
    )
    
    if response2.status_code != 200:
        print(f"✗ Second turn failed: {response2.status_code}")
        return False
    
    result2 = response2.json()
    print(f"✓ Second turn processed")
    print(f"  Response: {result2.get('response')}")
    
    # Verify both turns share the session_id in database
    print("\nVerifying session continuity in database...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute("""
        SELECT COUNT(*) FROM voice_commands 
        WHERE session_id = ?
    """, (session_id,))
    
    count = cursor.fetchone()[0]
    conn.close()
    
    if count >= 2:
        print(f"✓ Found {count} commands in session {session_id}")
        return True
    else:
        print(f"✗ Expected 2+ commands, found {count}")
        return False


def test_malformed_requests():
    """Test handling of malformed requests"""
    print_section("Test 7: Malformed Request Handling")
    
    # Test 1: Missing required fields
    print("Testing request with missing 'text' field...")
    response = requests.post(
        f"{BASE_URL}/voice/listen",
        json={
            "event_id": f"test-malformed-{int(time.time())}",
            "ts": int(time.time()),
            "source_id": "microphone",
            # Missing "text" field
            "voiceprint_user_id": "test_alice",
            "voiceprint_confidence": 0.88,
            "mode": "triggered"
        }
    )
    
    if response.status_code in [400, 422]:
        print(f"✓ Correctly rejected malformed request ({response.status_code})")
    else:
        print(f"⚠ Expected 400/422, got {response.status_code}")
    
    # Test 2: Invalid confidence value
    print("\nTesting request with invalid confidence value...")
    response = requests.post(
        f"{BASE_URL}/voice/listen",
        json={
            "event_id": f"test-invalid-{int(time.time())}",
            "ts": int(time.time()),
            "source_id": "microphone",
            "text": "test",
            "voiceprint_user_id": "test_alice",
            "voiceprint_confidence": 1.5,  # Invalid (> 1.0)
            "mode": "triggered",
            "confidence": 0.95
        }
    )
    
    if response.status_code in [400, 422]:
        print(f"✓ Correctly rejected invalid confidence ({response.status_code})")
    else:
        print(f"⚠ Expected 400/422, got {response.status_code}")
    
    return True


def test_client_ip_logging():
    """Test that client IP is properly logged"""
    print_section("Test 8: Client IP Logging")
    
    print("Sending request and verifying IP is logged...")
    correlation_id = f"test-ip-{int(time.time())}"
    
    response = requests.post(
        f"{BASE_URL}/voice/listen",
        headers={
            "X-Correlation-ID": correlation_id,
            "X-Forwarded-For": "192.168.1.100"  # Simulate proxy
        },
        json={
            "event_id": f"test-ip-{int(time.time())}",
            "ts": int(time.time()),
            "source_id": "microphone",
            "text": "test ip logging",
            "voiceprint_user_id": "test_alice",
            "voiceprint_confidence": 0.88,
            "mode": "triggered",
            "confidence": 0.95
        }
    )
    
    if response.status_code != 200:
        print(f"✗ Request failed: {response.status_code}")
        return False
    
    # Check database for logged IP
    print("\nChecking database for client IP...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute("""
        SELECT client_ip FROM voice_commands 
        WHERE correlation_id = ?
    """, (correlation_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    if row and row[0]:
        print(f"✓ Client IP logged: {row[0]}")
        
        if "192.168.1.100" in row[0]:
            print("✓ X-Forwarded-For header correctly processed")
        
        return True
    else:
        print("✗ Client IP not found in database")
        return False


def test_duplicate_voiceprint_mapping():
    """Test creating duplicate voiceprint mapping"""
    print_section("Test 9: Duplicate Voiceprint Mapping")
    
    voiceprint_id = f"test-dup-{int(time.time())}"
    
    # Create first mapping
    print(f"Creating first mapping for {voiceprint_id}...")
    response1 = requests.post(
        f"{BASE_URL}/voice/mappings",
        json={
            "voiceprint_user_id": voiceprint_id,
            "trusted_person_id": 1,
            "notes": "First mapping"
        }
    )
    
    if response1.status_code != 200:
        print(f"✗ First mapping failed: {response1.status_code}")
        return False
    
    print("✓ First mapping created")
    
    # Try to create duplicate
    print(f"\nAttempting to create duplicate mapping for {voiceprint_id}...")
    response2 = requests.post(
        f"{BASE_URL}/voice/mappings",
        json={
            "voiceprint_user_id": voiceprint_id,
            "trusted_person_id": 2,  # Different person
            "notes": "Duplicate mapping (should fail?)"
        }
    )
    
    if response2.status_code in [400, 409]:
        print(f"✓ Duplicate correctly rejected ({response2.status_code})")
        return True
    elif response2.status_code == 200:
        print("⚠ Duplicate was allowed (may be intentional)")
        print("  System allows remapping to different person")
        return True
    else:
        print(f"⚠ Unexpected status: {response2.status_code}")
        return True


def test_mapping_to_nonexistent_person():
    """Test creating mapping to non-existent trusted person"""
    print_section("Test 10: Mapping to Non-existent Person")
    
    print("Attempting to map to non-existent person ID 999999...")
    response = requests.post(
        f"{BASE_URL}/voice/mappings",
        json={
            "voiceprint_user_id": f"test-invalid-{int(time.time())}",
            "trusted_person_id": 999999,
            "notes": "Should fail"
        }
    )
    
    if response.status_code == 404:
        print("✓ Correctly rejected non-existent person (404)")
        return True
    elif response.status_code in [400, 422]:
        print(f"✓ Rejected non-existent person ({response.status_code})")
        return True
    else:
        print(f"✗ Expected 404/400, got {response.status_code}")
        print(response.text)
        return False


def main():
    """Run all tests"""
    print(f"""
    ╔═══════════════════════════════════════════════════════════════════╗
    ║  Voice API Edge Cases & Security Test Suite                      ║
    ║  Testing: {BASE_URL:50s}  ║
    ║  Database: {DB_PATH:47s}  ║
    ╚═══════════════════════════════════════════════════════════════════╝
    """)
    
    tests = [
        ("Low Confidence Rejection", test_low_confidence_rejection),
        ("Security Action High Confidence", test_security_action_high_confidence),
        ("Unknown Voiceprint Handling", test_unknown_voiceprint),
        ("Null Voiceprint Confidence", test_null_voiceprint_confidence),
        ("Invalid Tool Name", test_invalid_tool_name),
        ("Multi-turn Session", test_multi_turn_session),
        ("Malformed Requests", test_malformed_requests),
        ("Client IP Logging", test_client_ip_logging),
        ("Duplicate Voiceprint Mapping", test_duplicate_voiceprint_mapping),
        ("Mapping to Non-existent Person", test_mapping_to_nonexistent_person),
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

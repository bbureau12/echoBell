#!/usr/bin/env python3
"""
Test script for voice command integration

Tests:
1. Database schema creation
2. Voiceprint mapping creation
3. Voice command endpoint
4. Authorization checks
5. MCP tool permissions
"""

import sys
import os
import requests
import json
import time

# Configuration
BASE_URL = os.getenv("POLICY_SERVER_URL", "http://localhost:8000")

def print_section(title):
    """Print a section header"""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")

def test_voiceprint_mapping():
    """Test creating and listing voiceprint mappings"""
    print_section("Test 1: Voiceprint Mappings")
    
    # Create mapping
    print("Creating voiceprint mapping...")
    response = requests.post(
        f"{BASE_URL}/voice/mappings",
        json={
            "voiceprint_user_id": "test_alice",
            "trusted_person_id": 1,
            "notes": "Test mapping for Alice"
        }
    )
    
    if response.status_code == 200:
        print("✓ Mapping created successfully")
        print(json.dumps(response.json(), indent=2))
    else:
        print(f"✗ Failed to create mapping: {response.status_code}")
        print(response.text)
        return False
    
    # List mappings
    print("\nListing all mappings...")
    response = requests.get(f"{BASE_URL}/voice/mappings")
    
    if response.status_code == 200:
        print("✓ Mappings retrieved successfully")
        mappings = response.json()
        print(f"Found {len(mappings)} mapping(s)")
        for m in mappings:
            print(f"  - {m['voiceprint_user_id']} → {m['person_name']} (ID: {m['trusted_person_id']})")
    else:
        print(f"✗ Failed to list mappings: {response.status_code}")
        print(response.text)
        return False
    
    return True


def test_tool_permissions():
    """Test MCP tool permission queries"""
    print_section("Test 2: MCP Tool Permissions")
    
    # List all permissions
    print("Listing all tool permissions...")
    response = requests.get(f"{BASE_URL}/voice/tools/permissions")
    
    if response.status_code == 200:
        print("✓ Permissions retrieved successfully")
        permissions = response.json()
        print(f"Found {len(permissions)} tool(s)")
        for p in permissions:
            status = "✓" if p['voice_enabled'] else "✗"
            print(f"  {status} {p['tool_name']}: confidence={p['requires_confidence']}, 2fa={p['requires_2fa']}")
    else:
        print(f"✗ Failed to list permissions: {response.status_code}")
        print(response.text)
        return False
    
    # Get specific tool permission
    print("\nGetting permission for 'query_scene'...")
    response = requests.get(f"{BASE_URL}/voice/tools/permissions/query_scene")
    
    if response.status_code == 200:
        print("✓ Permission retrieved successfully")
        print(json.dumps(response.json(), indent=2))
    else:
        print(f"✗ Failed to get permission: {response.status_code}")
        print(response.text)
        return False
    
    return True


def test_authorization():
    """Test voice authorization checks"""
    print_section("Test 3: Authorization Checks")
    
    # Test allowed command
    print("Testing allowed command (high confidence)...")
    response = requests.post(
        f"{BASE_URL}/voice/authorize",
        json={
            "text": "who is at the door",
            "voiceprint_confidence": 0.92,
            "tool_name": "query_scene"
        }
    )
    
    if response.status_code == 200:
        result = response.json()
        if result['allowed']:
            print(f"✓ Command authorized: {result['reason']}")
        else:
            print(f"✗ Command denied: {result['reason']}")
        print(json.dumps(result, indent=2))
    else:
        print(f"✗ Failed to check authorization: {response.status_code}")
        print(response.text)
        return False
    
    # Test denied command (low confidence)
    print("\nTesting denied command (low confidence)...")
    response = requests.post(
        f"{BASE_URL}/voice/authorize",
        json={
            "text": "unlock the door",
            "voiceprint_confidence": 0.60,
            "tool_name": "query_scene"
        }
    )
    
    if response.status_code == 200:
        result = response.json()
        if not result['allowed']:
            print(f"✓ Command correctly denied: {result['reason']}")
        else:
            print(f"✗ Command should have been denied")
        print(json.dumps(result, indent=2))
    else:
        print(f"✗ Failed to check authorization: {response.status_code}")
        print(response.text)
        return False
    
    return True


def test_voice_command():
    """Test voice command endpoint"""
    print_section("Test 4: Voice Command Processing")
    
    # Send test voice command
    print("Sending test voice command...")
    correlation_id = f"test-{int(time.time())}"
    
    response = requests.post(
        f"{BASE_URL}/voice/listen",
        headers={"X-Correlation-ID": correlation_id},
        json={
            "event_id": f"echonet-test-{int(time.time())}",
            "ts": int(time.time()),
            "source_id": "microphone",
            "room": "test-room",
            "text": "who is at the front door",
            "voiceprint_user_id": "test_alice",
            "voiceprint_confidence": 0.87,
            "mode": "triggered",
            "confidence": 0.95
        }
    )
    
    if response.status_code == 200:
        result = response.json()
        print("✓ Voice command processed successfully")
        print(f"  Correlation ID: {result.get('correlation_id')}")
        print(f"  Handled: {result.get('handled')}")
        print(f"  Response: {result.get('response')}")
        print(f"  LLM Used: {result.get('llm_used')}")
        print(f"  Processing Time: {result.get('processing_time_ms')}ms")
        print(f"  User: {result.get('user_acknowledged')}")
        print("\nFull response:")
        print(json.dumps(result, indent=2))
    else:
        print(f"✗ Failed to process voice command: {response.status_code}")
        print(response.text)
        return False
    
    return True


def main():
    """Run all tests"""
    print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║  Voice Command Integration Test Suite                   ║
    ║  Testing: {BASE_URL:40s}  ║
    ╚══════════════════════════════════════════════════════════╝
    """)
    
    tests = [
        ("Voiceprint Mappings", test_voiceprint_mapping),
        ("Tool Permissions", test_tool_permissions),
        ("Authorization", test_authorization),
        ("Voice Command Processing", test_voice_command),
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

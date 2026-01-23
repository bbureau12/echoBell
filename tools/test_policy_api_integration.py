#!/usr/bin/env python3
"""
Test script to verify Policy API integration.

This script:
1. Starts the Policy API server (or verifies it's running)
2. Sends a test scene update request
3. Verifies the response
4. Checks active tracks
"""

import sys
import os
import time
import requests
import subprocess

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, PROJECT_ROOT)

POLICY_API_URL = "http://localhost:8000"
TIMEOUT = 5.0

def check_api_health():
    """Check if Policy API is running and healthy."""
    try:
        response = requests.get(f"{POLICY_API_URL}/health", timeout=TIMEOUT)
        response.raise_for_status()
        print("✅ Policy API is healthy")
        print(f"   Response: {response.json()}")
        return True
    except requests.RequestException as e:
        print(f"❌ Policy API is not running: {e}")
        return False


def test_scene_update():
    """Test the /scene/update endpoint with sample data."""
    print("\n🧪 Testing /scene/update endpoint...")
    
    payload = {
        "camera_id": 1,
        "timestamp": int(time.time()),
        "event_id": f"test_evt_{int(time.time())}",
        "detections": [
            {
                "object_id": 1,
                "cls": "vehicle",
                "raw_class": "car",
                "conf": 0.95,
                "bbox": {"x": 100.0, "y": 200.0, "w": 300.0, "h": 200.0},
                "props": {"vehicle_type": "car"}
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
    
    try:
        response = requests.post(
            f"{POLICY_API_URL}/scene/update",
            json=payload,
            timeout=TIMEOUT
        )
        response.raise_for_status()
        result = response.json()
        
        print("✅ Scene update successful")
        print(f"   Message: {result['message']}")
        print(f"   Scene evidence count: {len(result['scene_evidence'])}")
        print(f"   Track keys: {result['track_keys']}")
        
        if result['scene_evidence']:
            print("\n   Scene Evidence:")
            for ev in result['scene_evidence']:
                print(f"     - {ev['feature']}: {ev['value']} (conf={ev['conf']})")
        
        return True
        
    except requests.RequestException as e:
        print(f"❌ Scene update failed: {e}")
        return False


def test_get_active_tracks():
    """Test the /scene/tracks endpoint."""
    print("\n🧪 Testing /scene/tracks endpoint...")
    
    camera_id = 1
    
    try:
        response = requests.get(
            f"{POLICY_API_URL}/scene/tracks/{camera_id}",
            timeout=TIMEOUT
        )
        response.raise_for_status()
        result = response.json()
        
        print(f"✅ Retrieved active tracks for camera {camera_id}")
        print(f"   Active track count: {result['count']}")
        
        if result['active_tracks']:
            print("\n   Active Tracks:")
            for track in result['active_tracks']:
                print(f"     - {track['track_type']}: {track['track_key'][:30]}...")
                print(f"       First seen: {track['first_seen_ts']}, Last seen: {track['last_seen_ts']}")
        
        return True
        
    except requests.RequestException as e:
        print(f"❌ Get active tracks failed: {e}")
        return False


def main():
    """Run all tests."""
    print("=" * 60)
    print("EchoBell Policy API Integration Test")
    print("=" * 60)
    
    # Check if API is running
    if not check_api_health():
        print("\n⚠️  Policy API is not running.")
        print("   Start it with: cd apps/policy-server && python server.py")
        return 1
    
    # Run tests
    tests_passed = 0
    tests_total = 2
    
    if test_scene_update():
        tests_passed += 1
    
    # Give scene tracker a moment to process
    time.sleep(0.5)
    
    if test_get_active_tracks():
        tests_passed += 1
    
    # Summary
    print("\n" + "=" * 60)
    print(f"Tests passed: {tests_passed}/{tests_total}")
    print("=" * 60)
    
    if tests_passed == tests_total:
        print("✅ All tests passed!")
        return 0
    else:
        print("❌ Some tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())

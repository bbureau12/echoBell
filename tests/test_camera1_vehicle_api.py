"""
Test Script: Run Policy API and Submit Evidence

This script demonstrates:
1. How to start the policy API server
2. How to submit evidence for the camera 1 vehicle policy
3. Expected telegram notification

Prerequisites:
- Policy server dependencies installed: pip install -r central/policy-server/requirements.txt
- Database with policy created (already done via migration 021)
- Telegram bot configured (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables)

Usage:
1. Start server: python central/policy-server/server.py
2. In another terminal, run this test: python test_camera1_vehicle_api.py
"""

import requests
import json
import time
from pathlib import Path

# API Configuration
API_BASE_URL = "http://localhost:8000"
CAMERA_ID = 1
EVENT_ID = f"test_vehicle_evt_{int(time.time())}"

# Test image path (create a dummy one or use existing)
TEST_IMAGE = "data/edge_images/test_vehicle_frame.jpg"

def check_server_health():
    """Check if the API server is running"""
    try:
        response = requests.get(f"{API_BASE_URL}/health", timeout=2)
        if response.status_code == 200:
            print("✅ Server is healthy")
            print(json.dumps(response.json(), indent=2))
            return True
        else:
            print(f"❌ Server returned status {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print("❌ Server is not running!")
        print("\nTo start the server, run:")
        print("  cd central/policy-server")
        print("  python server.py")
        return False
    except Exception as e:
        print(f"❌ Error checking server: {e}")
        return False


def submit_vehicle_evidence():
    """
    Submit evidence for vehicle detection on camera 1
    
    This will trigger the 'camera1_vehicle_with_photo' policy if:
    1. Camera ID = 1 ✓
    2. Vehicle present ✓
    3. No alert in last 30 seconds ✓ (first run)
    """
    
    # Build evidence payload
    payload = {
        "camera_id": CAMERA_ID,
        "event_id": EVENT_ID,
        "timestamp": int(time.time()),
        "objects": [
            {
                "object_id": 1,
                "label": "vehicle",
                "bbox": [100, 200, 400, 400],  # x1, y1, x2, y2
                "props": {
                    "scene_track_key": "vehicle_test_abc123",
                    "vehicle_color": "white",
                    "vehicle_type": "sedan"
                }
            }
        ],
        "evidence": [
            # Core evidence: vehicle present (required by policy)
            {
                "source": "vision",
                "feature": "vehicle_present",
                "value": "true",
                "conf": 0.95,
                "object_id": 1
            },
            # Variable substitution: vehicle color
            {
                "source": "vision",
                "feature": "vehicle_color",
                "value": "white",
                "conf": 0.85,
                "object_id": 1
            },
            # Variable substitution: vehicle type
            {
                "source": "vision",
                "feature": "vehicle_type",
                "value": "sedan",
                "conf": 0.90,
                "object_id": 1
            },
            # Photo path for telegram (if exists)
            {
                "source": "vision",
                "feature": "latest_frame_path",
                "value": TEST_IMAGE,
                "conf": 1.0,
                "object_id": 1
            }
        ],
        "context": {
            "test_run": True,
            "notes": "Testing camera 1 vehicle detection policy"
        }
    }
    
    print(f"\n📤 Submitting evidence to {API_BASE_URL}/evidence")
    print(f"   Camera ID: {CAMERA_ID}")
    print(f"   Event ID: {EVENT_ID}")
    print(f"   Objects: {len(payload['objects'])}")
    print(f"   Evidence: {len(payload['evidence'])} items")
    
    try:
        response = requests.post(
            f"{API_BASE_URL}/evidence",
            json=payload,
            timeout=10
        )
        
        if response.status_code == 200:
            result = response.json()
            print("\n✅ Evidence submitted successfully!")
            print(json.dumps(result, indent=2))
            
            print("\n📱 Check your Telegram chat for notification:")
            print("   Expected message: 🚗 Vehicle detected on Camera 1: white sedan")
            print("   Expected photo: Attached (if image path exists)")
            
            return True
        else:
            print(f"\n❌ API returned status {response.status_code}")
            print(response.text)
            return False
            
    except Exception as e:
        print(f"\n❌ Error submitting evidence: {e}")
        return False


def submit_second_alert_test():
    """
    Submit a second alert within 30 seconds to test cooldown
    
    Expected: No telegram alert (cooldown active)
    """
    print("\n⏳ Testing alert cooldown (wait 2 seconds)...")
    time.sleep(2)
    
    print("\n📤 Submitting second evidence (should be blocked by cooldown)...")
    
    payload = {
        "camera_id": CAMERA_ID,
        "event_id": f"{EVENT_ID}_second",
        "timestamp": int(time.time()),
        "objects": [
            {
                "object_id": 1,
                "label": "vehicle",
                "bbox": [100, 200, 400, 400],
                "props": {
                    "scene_track_key": "vehicle_test_abc123",  # Same vehicle
                    "vehicle_color": "white",
                    "vehicle_type": "sedan"
                }
            }
        ],
        "evidence": [
            {
                "source": "vision",
                "feature": "vehicle_present",
                "value": "true",
                "conf": 0.95,
                "object_id": 1
            },
            {
                "source": "vision",
                "feature": "vehicle_color",
                "value": "white",
                "conf": 0.85,
                "object_id": 1
            },
            {
                "source": "vision",
                "feature": "vehicle_type",
                "value": "sedan",
                "conf": 0.90,
                "object_id": 1
            }
        ]
    }
    
    try:
        response = requests.post(f"{API_BASE_URL}/evidence", json=payload, timeout=10)
        if response.status_code == 200:
            print("\n✅ Second evidence submitted")
            print("   Expected: NO telegram alert (cooldown active)")
            print("   Cooldown: 30 seconds from first alert")
            return True
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def main():
    """Run the test sequence"""
    print("=" * 70)
    print("Camera 1 Vehicle Detection Policy - API Test")
    print("=" * 70)
    
    # Step 1: Check server
    if not check_server_health():
        print("\n⚠️  Please start the policy server first:")
        print("   cd central/policy-server")
        print("   python server.py")
        return
    
    # Step 2: Submit first evidence (should trigger alert)
    print("\n" + "=" * 70)
    print("Test 1: Submit vehicle evidence (should trigger alert)")
    print("=" * 70)
    
    if not submit_vehicle_evidence():
        print("\n❌ Test failed")
        return
    
    # Step 3: Submit second evidence within cooldown (should NOT trigger alert)
    print("\n" + "=" * 70)
    print("Test 2: Submit within cooldown window (should NOT trigger alert)")
    print("=" * 70)
    
    submit_second_alert_test()
    
    # Summary
    print("\n" + "=" * 70)
    print("Test Summary")
    print("=" * 70)
    print("\n✅ Tests completed!")
    print("\nExpected Results:")
    print("  1. First submission → Telegram alert with photo")
    print("  2. Second submission → No alert (cooldown active)")
    print("  3. Wait 30 seconds → Next alert will trigger")
    print("\n📋 View alert history:")
    print("  python -c \"import sqlite3; conn = sqlite3.connect('data/doorbell.db');")
    print("  cur = conn.cursor(); cur.execute('SELECT * FROM alert_history ORDER BY sent_ts DESC LIMIT 5');")
    print("  for row in cur: print(row)\"")


if __name__ == "__main__":
    main()

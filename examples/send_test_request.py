"""Simple test request - send vehicle evidence to API"""
import requests
import json
import time

# Build the test payload
payload = {
    "camera_id": 1,
    "event_id": f"test_vehicle_{int(time.time())}",
    "timestamp": int(time.time()),
    "objects": [
        {
            "object_id": 1,
            "label": "vehicle",
            "bbox": [100, 200, 400, 400],
            "props": {
                "scene_track_key": "vehicle_test_abc123",
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
        },
        {
            "source": "vision",
            "feature": "latest_frame_path",
            "value": "data/edge_images/cam1_1769480091.jpg",
            "conf": 1.0,
            "object_id": 1
        }
    ]
}

print("=" * 70)
print("Sending Test Request to Policy API")
print("=" * 70)
print(f"\nCamera ID: {payload['camera_id']}")
print(f"Event ID: {payload['event_id']}")
print(f"Vehicle: {payload['objects'][0]['props']['vehicle_color']} {payload['objects'][0]['props']['vehicle_type']}")

try:
    response = requests.post(
        "http://localhost:8000/evidence",
        json=payload,
        timeout=10
    )
    
    print(f"\n✅ Response Status: {response.status_code}")
    
    if response.status_code == 200:
        result = response.json()
        print("\n📦 Response:")
        print(json.dumps(result, indent=2))
        print("\n📱 Check your Telegram for the alert!")
    else:
        print(f"\n❌ Error: {response.text}")
        
except requests.exceptions.ConnectionError:
    print("\n❌ Cannot connect to server!")
    print("Make sure the server is running:")
    print("  cd central/policy-server")
    print("  python server.py")
except Exception as e:
    print(f"\n❌ Error: {e}")

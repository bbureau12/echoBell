"""Quick health check for the Policy API server"""
import requests
import json

API_URL = "http://localhost:8000"

def check_health():
    """Check if API server is running and healthy"""
    try:
        response = requests.get(f"{API_URL}/health", timeout=2)
        
        if response.status_code == 200:
            data = response.json()
            print("✅ Policy API Server is HEALTHY\n")
            print("Server Configuration:")
            print(f"  Database: {data.get('database')}")
            print(f"  Status: {data.get('status')}")
            
            if 'scene_tracker' in data:
                st = data['scene_tracker']
                print(f"\nScene Tracker:")
                print(f"  IOU Threshold: {st.get('iou_threshold')}")
                print(f"  Grace Period: {st.get('grace_period_s')}s")
            
            if 'watch_worker' in data:
                ww = data['watch_worker']
                print(f"\nWatch Worker:")
                print(f"  Running: {ww.get('running')}")
                print(f"  Poll Interval: {ww.get('poll_interval_seconds')}s")
                print(f"  Due Watches: {ww.get('due_watches_count', 'N/A')}")
            
            print(f"\n🌐 API Endpoints:")
            print(f"  Health: {API_URL}/health")
            print(f"  Evidence: {API_URL}/evidence")
            print(f"  Tracks: {API_URL}/scene/tracks/{{camera_id}}")
            
            return True
        else:
            print(f"❌ Server returned status {response.status_code}")
            return False
            
    except requests.exceptions.ConnectionError:
        print("❌ Cannot connect to Policy API Server")
        print(f"   Expected URL: {API_URL}")
        print("\nTo start the server:")
        print("  1. Open a terminal")
        print("  2. cd central/policy-server")
        print("  3. python server.py")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    check_health()

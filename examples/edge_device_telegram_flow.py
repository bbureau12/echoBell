#!/usr/bin/env python3
"""
Complete Example: Edge Device with Image Server + Telegram Alerts

This demonstrates the full flow:
1. Edge device runs HTTP server for images
2. Camera detects vehicle, saves frame
3. Sends observation with image URL to policy server
4. Policy server evaluates policy, downloads image, sends via Telegram

Run this example:
    python examples/edge_device_telegram_flow.py
"""

import os
import sys
import time
import cv2
import numpy as np
import requests
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)


# ============================================================================
# PART 1: Edge Device - HTTP Image Server
# ============================================================================

class EdgeImageServer:
    """Simple HTTP server for serving images from edge device"""
    
    def __init__(self, port=8080, directory="data/edge_images"):
        self.port = port
        self.directory = directory
        Path(directory).mkdir(parents=True, exist_ok=True)
        self.server = None
    
    def start(self):
        """Start HTTP server in background thread"""
        handler = lambda *args, **kwargs: SimpleHTTPRequestHandler(
            *args, directory=self.directory, **kwargs
        )
        self.server = HTTPServer(('127.0.0.1', self.port), handler)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        print(f"✅ Edge image server started on http://127.0.0.1:{self.port}")
        print(f"   Serving: {self.directory}")
    
    def stop(self):
        if self.server:
            self.server.shutdown()


# ============================================================================
# PART 2: Edge Device - Camera Agent
# ============================================================================

class MockCameraAgent:
    """Simulates edge device camera agent"""
    
    def __init__(self, camera_id, image_dir, http_port):
        self.camera_id = camera_id
        self.image_dir = image_dir
        self.http_port = http_port
        Path(image_dir).mkdir(parents=True, exist_ok=True)
    
    def create_vehicle_frame(self, plate_text="ABC-123"):
        """Create a mock vehicle image"""
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        img[:] = (40, 40, 40)
        
        # Draw car
        cv2.rectangle(img, (200, 200), (440, 350), (100, 100, 200), -1)
        cv2.rectangle(img, (220, 220), (280, 270), (150, 200, 255), 2)
        cv2.rectangle(img, (360, 220), (420, 270), (150, 200, 255), 2)
        cv2.circle(img, (250, 360), 30, (50, 50, 50), -1)
        cv2.circle(img, (390, 360), 30, (50, 50, 50), -1)
        
        # License plate
        cv2.rectangle(img, (270, 310), (370, 340), (255, 255, 255), -1)
        cv2.putText(img, plate_text, (280, 332),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
        
        # Label
        cv2.putText(img, "UNKNOWN VEHICLE", (180, 100),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
        
        return img
    
    def detect_and_save(self):
        """Simulate vehicle detection and save frame"""
        timestamp = int(time.time())
        
        # Create vehicle image
        frame = self.create_vehicle_frame("XYZ-789")
        
        # Save to local storage
        filename = f"cam{self.camera_id}_{timestamp}.jpg"
        filepath = os.path.join(self.image_dir, filename)
        cv2.imwrite(filepath, frame)
        
        print(f"📸 Camera {self.camera_id}: Saved image {filename}")
        
        # Return image URL (how policy server will access it)
        image_url = f"http://127.0.0.1:{self.http_port}/{filename}"
        
        return {
            "label": "car",
            "confidence": 0.94,
            "bbox": [200, 200, 440, 350],
            "plate_text": "XYZ-789",
            "snapshot_url": image_url  # <-- Key: HTTP URL to image
        }
    
    def send_to_policy_server(self, observation, policy_server_url):
        """Send observation to policy server"""
        payload = {
            "camera_id": self.camera_id,
            "timestamp": int(time.time()),
            "observations": [observation],
            "evidence": []
        }
        
        print(f"📤 Sending observation to policy server...")
        print(f"   Image URL: {observation['snapshot_url']}")
        
        try:
            # In real deployment, this would POST to policy server
            # response = requests.post(
            #     f"{policy_server_url}/observations",
            #     json=payload
            # )
            
            # For demo, we'll just print
            print(f"✅ Would send to: {policy_server_url}/observations")
            return payload
        except Exception as e:
            print(f"❌ Failed to send: {e}")
            return None


# ============================================================================
# PART 3: Policy Server - Fetch Image and Send via Telegram
# ============================================================================

class MockPolicyServer:
    """Simulates policy server receiving observations"""
    
    def __init__(self):
        pass
    
    def evaluate_and_act(self, observation):
        """Evaluate policy and execute actions"""
        
        print("\n" + "="*60)
        print("🔍 Policy Server: Evaluating observation...")
        print("="*60)
        
        # Check if unknown vehicle
        is_unknown = observation.get('label') == 'car'
        
        if is_unknown:
            print("✅ Policy matched: unknown_vehicle_alert")
            print("   Action: Send Telegram alert with photo")
            
            # Fetch image from edge device
            snapshot_url = observation.get('snapshot_url')
            if snapshot_url:
                self.download_and_send_telegram(
                    snapshot_url,
                    observation.get('plate_text', 'Unknown')
                )
        else:
            print("ℹ️  No policy matched")
    
    def download_and_send_telegram(self, image_url, plate_text):
        """Download image from edge device and send via Telegram"""
        
        print(f"\n📥 Downloading image from edge device...")
        print(f"   URL: {image_url}")
        
        try:
            # Download image from edge device HTTP server
            response = requests.get(image_url, timeout=10)
            
            if response.status_code == 200:
                print(f"✅ Downloaded image ({len(response.content)} bytes)")
                
                # Save to temp file
                temp_path = "temp_vehicle.jpg"
                with open(temp_path, 'wb') as f:
                    f.write(response.content)
                
                # Send via Telegram (if configured)
                self.send_telegram_photo(temp_path, plate_text)
                
                # Cleanup
                os.remove(temp_path)
                
            else:
                print(f"❌ Failed to download: HTTP {response.status_code}")
        
        except Exception as e:
            print(f"❌ Error downloading image: {e}")
    
    def send_telegram_photo(self, image_path, plate_text):
        """Send photo via Telegram"""
        from packages.integrations.telegram import load_telegram_config, TelegramNotifier
        
        config = load_telegram_config()
        
        if not config or not config.enabled:
            print("⚠️  Telegram not configured (skipping send)")
            print(f"   Would have sent: {image_path}")
            print(f"   With caption: 🚗 Unknown vehicle: {plate_text}")
            return
        
        # Send the photo
        notifier = TelegramNotifier(config)
        message = f"""🚗 Unknown Vehicle Alert

📸 Plate: {plate_text}
⏰ Time: {time.strftime("%Y-%m-%d %H:%M:%S")}
📍 Camera: Front Gate

⚠️ This vehicle is not recognized.
"""
        
        success = notifier.send_photo(image_path, caption=message)
        
        if success:
            print(f"✅ Telegram photo sent successfully!")
        else:
            print(f"❌ Failed to send Telegram photo")


# ============================================================================
# MAIN: Run Complete Flow
# ============================================================================

def main():
    print("\n" + "="*60)
    print("🚀 Complete Edge-to-Telegram Flow Demo")
    print("="*60)
    print("\nThis demonstrates:")
    print("1. Edge device HTTP server (serves images)")
    print("2. Camera agent (detects vehicle, saves image)")
    print("3. Policy server (downloads image, sends Telegram)")
    print("="*60 + "\n")
    
    # Configuration
    CAMERA_ID = 1
    EDGE_IMAGE_DIR = "data/edge_images"
    HTTP_PORT = 8080
    POLICY_SERVER_URL = "http://policy-server:8000"
    
    # Step 1: Start edge device HTTP server
    print("\n[STEP 1] Starting edge device HTTP image server...")
    print("-" * 60)
    image_server = EdgeImageServer(port=HTTP_PORT, directory=EDGE_IMAGE_DIR)
    image_server.start()
    time.sleep(0.5)
    
    # Step 2: Camera detects vehicle and saves image
    print("\n[STEP 2] Camera agent detects vehicle...")
    print("-" * 60)
    camera = MockCameraAgent(CAMERA_ID, EDGE_IMAGE_DIR, HTTP_PORT)
    observation = camera.detect_and_save()
    time.sleep(0.5)
    
    # Step 3: Send observation to policy server
    print("\n[STEP 3] Sending observation to policy server...")
    print("-" * 60)
    payload = camera.send_to_policy_server(observation, POLICY_SERVER_URL)
    time.sleep(0.5)
    
    # Step 4: Policy server evaluates and downloads image
    print("\n[STEP 4] Policy server processing...")
    print("-" * 60)
    policy_server = MockPolicyServer()
    policy_server.evaluate_and_act(observation)
    
    # Summary
    print("\n" + "="*60)
    print("✅ Demo Complete!")
    print("="*60)
    print("\nWhat happened:")
    print("1. ✅ Edge device started HTTP server on port 8080")
    print("2. ✅ Camera detected vehicle and saved image")
    print("3. ✅ Image URL sent to policy server")
    print("4. ✅ Policy server downloaded image from edge device")
    print("5. ✅ Policy server would send via Telegram (if configured)")
    
    print("\n" + "="*60)
    print("Image saved at:")
    print(f"  {os.path.abspath(EDGE_IMAGE_DIR)}/cam{CAMERA_ID}_*.jpg")
    
    print("\nTo enable real Telegram sending:")
    print("  export TELEGRAM_BOT_TOKEN='your_token'")
    print("  export TELEGRAM_CHAT_ID='your_chat_id'")
    
    print("\nImplementation:")
    print("  - Edge device code: apps/camera-agent/loop.py")
    print("  - HTTP server: apps/camera-agent/image_server.py")
    print("  - Policy server: apps/policy-server/server.py")
    print("  - Action handler: packages/policy/action_handlers.py")
    
    print("\nSee docs/EDGE_IMAGE_SERVING.md for deployment options")
    print("="*60 + "\n")
    
    # Cleanup
    image_server.stop()
    
    return 0


if __name__ == '__main__':
    sys.exit(main())

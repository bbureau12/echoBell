"""
Example: Full integration - Detect vehicle, check if first-time visitor, send alert.

This shows the complete workflow:
1. Vision detection (snapshot_and_detect)
2. Plate extraction and hashing
3. Scene tracking (SceneTracker)
4. Visit history check (PlateService)
5. Alert decision (Telegram notification)

This is the pattern you'd use in the orchestrator or a webhook handler.
"""

import sqlite3
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from packages.perception.vision import snapshot_and_detect
from packages.perception.plate_service import PlateService
from packages.scene.scene_tracker import SceneTracker
from packages.integrations.telegram import load_telegram_config, TelegramNotifier


def process_camera_frame_and_alert(
    db_path: str,
    rtsp_url: str,
    camera_id: int,
    plate_secret: bytes,
    send_alerts: bool = True,
) -> dict:
    """
    Complete workflow: Detect vehicles and send alerts for first-time visitors.
    
    Returns summary dict with:
        - vehicles_detected: Total vehicles in scene
        - first_time_visitors: Count of new vehicles
        - alerts_sent: Number of alerts sent
        - vehicle_details: List of vehicle info
    """
    conn = sqlite3.connect(db_path)
    
    # Initialize services
    plate_service = PlateService(secret_key=plate_secret)
    scene_tracker = SceneTracker(iou_match_threshold=0.3, grace_period_s=6)
    
    telegram_config = load_telegram_config()
    notifier = TelegramNotifier(telegram_config) if telegram_config else None
    
    # Step 1: Run vision detection
    print(f"[1/5] Running vision detection on camera {camera_id}...")
    vision_result = snapshot_and_detect(
        db=db_path,
        rtsp=rtsp_url,
        camera_id=str(camera_id),
        debug=False,
    )
    
    # Step 2: Extract vehicles and plates
    print(f"[2/5] Extracting vehicles and license plates...")
    vehicles = [obj for obj in vision_result.objects if obj.label == "vehicle"]
    
    if not vehicles:
        print("  No vehicles detected")
        conn.close()
        return {
            "vehicles_detected": 0,
            "first_time_visitors": 0,
            "alerts_sent": 0,
            "vehicle_details": [],
        }
    
    print(f"  Found {len(vehicles)} vehicle(s)")
    
    # Step 3: Process each vehicle
    print(f"[3/5] Processing vehicle plates and visit history...")
    vehicle_details = []
    first_time_count = 0
    
    for i, vehicle in enumerate(vehicles, 1):
        vehicle_info = {
            "vehicle_number": i,
            "color": vehicle.props.get("color", "unknown"),
            "raw_class": vehicle.props.get("raw_class", "vehicle"),
            "plate_detected": False,
            "plate_hmac": None,
            "is_first_time": False,
            "visit_count": 0,
            "is_trusted": False,
            "trusted_label": None,
        }
        
        # Check if vehicle has plate detection in evidence
        plate_texts = [
            ev.value for ev in vehicle.evidence 
            if ev.source == "ocr" and ev.feature == "text" and len(ev.value) >= 5
        ]
        
        if plate_texts:
            # Use first (highest confidence) plate
            raw_plate = plate_texts[0]
            print(f"  Vehicle {i}: Plate detected")
            
            # Get plate visit history
            result = plate_service.upsert_plate_visit(
                conn,
                raw_plate_text=raw_plate,
                camera_id=camera_id,
            )
            
            if result:
                vehicle_info["plate_detected"] = True
                vehicle_info["plate_hmac"] = result.plate_hmac
                vehicle_info["is_first_time"] = not result.is_repeat
                vehicle_info["visit_count"] = result.visit_count
                
                # Check if trusted
                trusted_info = plate_service.is_plate_trusted(conn, raw_plate)
                if trusted_info:
                    vehicle_info["is_trusted"] = True
                    vehicle_info["trusted_label"] = trusted_info["label"]
                
                if vehicle_info["is_first_time"]:
                    first_time_count += 1
                    print(f"    🆕 FIRST TIME VISITOR")
                else:
                    print(f"    🔁 Repeat visitor ({result.visit_count} total visits)")
                
                if vehicle_info["is_trusted"]:
                    print(f"    ✅ Trusted: {trusted_info['label']}")
        else:
            print(f"  Vehicle {i}: No plate detected")
        
        vehicle_details.append(vehicle_info)
    
    # Step 4: Send alerts for first-time, non-trusted vehicles
    print(f"[4/5] Deciding alerts...")
    alerts_sent = 0
    
    if send_alerts and notifier and first_time_count > 0:
        for vehicle in vehicle_details:
            if vehicle["is_first_time"] and not vehicle["is_trusted"]:
                # Compose alert message
                message = (
                    f"🚨 NEW VEHICLE DETECTED\n\n"
                    f"Camera: {camera_id}\n"
                    f"Type: {vehicle['raw_class']}\n"
                    f"Color: {vehicle['color']}\n"
                    f"Plate: {vehicle['plate_hmac'][:16] if vehicle['plate_hmac'] else 'None'}...\n"
                    f"Status: First time visitor\n"
                )
                
                success = notifier.send_message(message)
                if success:
                    alerts_sent += 1
                    print(f"  ✉️ Alert sent for {vehicle['color']} {vehicle['raw_class']}")
    
    # Step 5: Summary
    print(f"[5/5] Summary:")
    print(f"  Vehicles detected: {len(vehicles)}")
    print(f"  First-time visitors: {first_time_count}")
    print(f"  Alerts sent: {alerts_sent}")
    
    conn.commit()
    conn.close()
    
    return {
        "vehicles_detected": len(vehicles),
        "first_time_visitors": first_time_count,
        "alerts_sent": alerts_sent,
        "vehicle_details": vehicle_details,
    }


# =============================================================================
# USAGE EXAMPLES
# =============================================================================

def example_simple_check():
    """Simple example: Check camera and get summary."""
    import os
    
    db_path = "echoBell.db"
    rtsp_url = "rtsp://camera1.local/stream"  # Or path to test image
    camera_id = 1
    plate_secret = os.getenv("PLATE_SECRET", "default_secret_16!").encode()[:16]
    
    result = process_camera_frame_and_alert(
        db_path=db_path,
        rtsp_url=rtsp_url,
        camera_id=camera_id,
        plate_secret=plate_secret,
        send_alerts=False,  # Don't send alerts in example
    )
    
    print("\n" + "=" * 60)
    print("RESULT:")
    print("=" * 60)
    print(f"Vehicles detected: {result['vehicles_detected']}")
    print(f"First-time visitors: {result['first_time_visitors']}")
    print(f"Alerts sent: {result['alerts_sent']}")
    
    for vehicle in result['vehicle_details']:
        print(f"\nVehicle {vehicle['vehicle_number']}:")
        print(f"  Type: {vehicle['raw_class']}")
        print(f"  Color: {vehicle['color']}")
        if vehicle['plate_detected']:
            print(f"  Visit count: {vehicle['visit_count']}")
            print(f"  First time: {vehicle['is_first_time']}")
            if vehicle['is_trusted']:
                print(f"  Trusted: {vehicle['trusted_label']}")


def example_monitoring_webhook():
    """
    Example webhook handler for continuous monitoring.
    
    This could be called by:
    - Motion detection trigger
    - Scheduled polling
    - RTSP frame callback
    - External system webhook
    """
    import os
    import time
    
    db_path = "echoBell.db"
    plate_secret = os.getenv("PLATE_SECRET", "default_secret_16!").encode()[:16]
    
    # Camera configuration
    cameras = [
        {"id": 1, "rtsp": "rtsp://driveway.local/stream"},
        {"id": 2, "rtsp": "rtsp://frontdoor.local/stream"},
    ]
    
    print("Starting monitoring webhook handler...")
    print(f"Monitoring {len(cameras)} camera(s)")
    print("=" * 60)
    
    for camera in cameras:
        print(f"\nProcessing Camera {camera['id']}...")
        
        try:
            result = process_camera_frame_and_alert(
                db_path=db_path,
                rtsp_url=camera['rtsp'],
                camera_id=camera['id'],
                plate_secret=plate_secret,
                send_alerts=True,  # Actually send alerts
            )
            
            # Log to file or database
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{timestamp}] Camera {camera['id']}: "
                  f"{result['vehicles_detected']} vehicles, "
                  f"{result['first_time_visitors']} new, "
                  f"{result['alerts_sent']} alerts")
            
        except Exception as e:
            print(f"Error processing camera {camera['id']}: {e}")
            continue


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Vehicle detection with first-time visitor alerts")
    parser.add_argument("--example", choices=["simple", "webhook"], default="simple")
    args = parser.parse_args()
    
    if args.example == "simple":
        example_simple_check()
    else:
        example_monitoring_webhook()

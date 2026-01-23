"""
Example: Programmatic API for querying scene and vehicle history.

Shows clean Python API for:
- Checking current scene status
- Determining if vehicles are first-time visitors
- Getting plate visit history
"""

import sqlite3
from typing import Optional


class SceneQuery:
    """Helper class for querying current scene status and vehicle history."""
    
    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
    
    def get_active_vehicles(self, camera_id: int) -> list[dict]:
        """
        Get all vehicles currently in scene.
        
        Returns:
            List of dicts with vehicle info (track_id, plate_hmac, color, etc.)
        """
        rows = self.conn.execute("""
            SELECT 
                id, track_key, key_kind, raw_class, color,
                first_seen_ts, last_seen_ts, last_box_json
            FROM scene_tracks
            WHERE camera_id = ? AND track_type = 'vehicle' AND active = 1
            ORDER BY last_seen_ts DESC
        """, (camera_id,)).fetchall()
        
        vehicles = []
        for row in rows:
            track_id, track_key, key_kind, raw_class, color, first_seen, last_seen, box_json = row
            vehicles.append({
                "track_id": track_id,
                "plate_hmac": track_key if key_kind == "plate" else None,
                "key_kind": key_kind,
                "raw_class": raw_class,
                "color": color,
                "first_seen_ts": first_seen,
                "last_seen_ts": last_seen,
            })
        return vehicles
    
    def is_first_time_visitor(self, plate_hmac: str) -> bool:
        """
        Check if a vehicle (by plate hash) is visiting for the first time.
        
        Args:
            plate_hmac: Hashed license plate
            
        Returns:
            True if first visit, False if repeat visitor
        """
        row = self.conn.execute("""
            SELECT visit_count FROM plate_visitors WHERE plate_hmac = ?
        """, (plate_hmac,)).fetchone()
        
        if not row:
            return True  # No history = first time
        
        return row[0] == 1
    
    def get_visit_count(self, plate_hmac: str) -> int:
        """Get total visit count for a plate. Returns 0 if never seen."""
        row = self.conn.execute("""
            SELECT visit_count FROM plate_visitors WHERE plate_hmac = ?
        """, (plate_hmac,)).fetchone()
        
        return row[0] if row else 0
    
    def is_trusted(self, plate_hmac: str) -> bool:
        """Check if plate is in trusted list."""
        row = self.conn.execute("""
            SELECT 1 FROM trusted_plates WHERE plate_hmac = ? AND enabled = 1
        """, (plate_hmac,)).fetchone()
        
        return row is not None
    
    def get_trusted_label(self, plate_hmac: str) -> Optional[str]:
        """Get label for trusted plate (e.g., 'Family Car', 'Work Truck')."""
        row = self.conn.execute("""
            SELECT label FROM trusted_plates WHERE plate_hmac = ? AND enabled = 1
        """, (plate_hmac,)).fetchone()
        
        return row[0] if row else None
    
    def close(self):
        self.conn.close()


# =============================================================================
# USAGE EXAMPLES
# =============================================================================

def example_check_scene_and_alert():
    """Example: Check current scene and decide whether to send alert."""
    
    # Connect to database
    scene = SceneQuery("echoBell.db")
    camera_id = 1
    
    # Get active vehicles
    vehicles = scene.get_active_vehicles(camera_id)
    
    print(f"Found {len(vehicles)} active vehicle(s) in scene")
    
    for vehicle in vehicles:
        if not vehicle['plate_hmac']:
            print(f"  - {vehicle['color']} {vehicle['raw_class']} (no plate detected)")
            continue
        
        plate_hash = vehicle['plate_hmac']
        
        # Check if trusted
        if scene.is_trusted(plate_hash):
            label = scene.get_trusted_label(plate_hash)
            print(f"  ✅ {label} - Trusted, no alert needed")
            continue
        
        # Check if first time visitor
        if scene.is_first_time_visitor(plate_hash):
            print(f"  🚨 NEW VEHICLE DETECTED!")
            print(f"     Color: {vehicle['color']}")
            print(f"     Type: {vehicle['raw_class']}")
            print(f"     Plate: {plate_hash[:16]}...")
            print(f"     Action: Send alert to owner")
            
            # Here you would:
            # - Send Telegram notification
            # - Log to security system
            # - Take snapshot
            # etc.
        else:
            visit_count = scene.get_visit_count(plate_hash)
            print(f"  🔁 Known vehicle (visited {visit_count} times) - Low priority")
    
    scene.close()


def example_monitor_loop():
    """
    Example: Continuous monitoring loop (simplified).
    
    In a real system, this would run after each vision detection.
    """
    import time
    
    scene = SceneQuery("echoBell.db")
    camera_id = 1
    
    last_vehicle_count = 0
    
    print("Monitoring scene for new vehicles...")
    print("(Press Ctrl+C to stop)\n")
    
    try:
        while True:
            vehicles = scene.get_active_vehicles(camera_id)
            
            # Detect when new vehicle appears
            if len(vehicles) > last_vehicle_count:
                print(f"[{time.strftime('%H:%M:%S')}] Vehicle detected!")
                
                # Check each vehicle
                for vehicle in vehicles:
                    if vehicle['plate_hmac']:
                        if scene.is_first_time_visitor(vehicle['plate_hmac']):
                            print(f"  🆕 FIRST TIME VISITOR")
                            print(f"     Send alert: Unknown {vehicle['color']} {vehicle['raw_class']}")
                        else:
                            visits = scene.get_visit_count(vehicle['plate_hmac'])
                            print(f"  ✓ Known vehicle ({visits} total visits)")
            
            last_vehicle_count = len(vehicles)
            time.sleep(5)  # Check every 5 seconds
            
    except KeyboardInterrupt:
        print("\nMonitoring stopped")
        scene.close()


def example_get_scene_summary():
    """Example: Get quick summary of current scene."""
    
    scene = SceneQuery("echoBell.db")
    camera_id = 1
    
    vehicles = scene.get_active_vehicles(camera_id)
    
    if not vehicles:
        print("Scene is empty (no vehicles detected)")
        return
    
    first_time = sum(1 for v in vehicles if v['plate_hmac'] and scene.is_first_time_visitor(v['plate_hmac']))
    trusted = sum(1 for v in vehicles if v['plate_hmac'] and scene.is_trusted(v['plate_hmac']))
    repeat = sum(1 for v in vehicles if v['plate_hmac'] and not scene.is_first_time_visitor(v['plate_hmac']) and not scene.is_trusted(v['plate_hmac']))
    no_plate = sum(1 for v in vehicles if not v['plate_hmac'])
    
    print(f"Scene Summary (Camera {camera_id}):")
    print(f"  Total vehicles: {len(vehicles)}")
    print(f"  🆕 First-time visitors: {first_time}")
    print(f"  ✅ Trusted vehicles: {trusted}")
    print(f"  🔁 Repeat visitors: {repeat}")
    print(f"  📍 No plate detected: {no_plate}")
    
    scene.close()


if __name__ == "__main__":
    # Run examples
    print("Example 1: Check scene and decide alerts")
    print("=" * 60)
    example_check_scene_and_alert()
    
    print("\n\nExample 2: Get scene summary")
    print("=" * 60)
    example_get_scene_summary()
    
    # Uncomment to run monitoring loop
    # example_monitor_loop()

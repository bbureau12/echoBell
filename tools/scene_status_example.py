"""
Example: Query current scene status and vehicle visit history.

Shows how to:
1. Get all active vehicles in current scene
2. Check if each vehicle is a first-time visitor
3. Get visit history for known plates

Usage:
    python tools/scene_status_example.py --db path/to/echoBell.db --camera 1
"""

import sqlite3
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def get_active_scene_vehicles(conn: sqlite3.Connection, camera_id: int) -> list[dict]:
    """
    Get all active vehicles currently tracked in the scene.
    
    Returns list of dicts with:
        - track_id: Scene track ID
        - track_key: Unique identifier (plate_hmac if available, else iou-based)
        - plate_hmac: License plate hash (if detected)
        - raw_class: Vehicle type (car, truck, etc.)
        - color: Vehicle color
        - first_seen_ts: When vehicle first appeared
        - last_seen_ts: Most recent observation
    """
    rows = conn.execute("""
        SELECT 
            id,
            track_key,
            key_kind,
            raw_class,
            color,
            first_seen_ts,
            last_seen_ts,
            last_box_json
        FROM scene_tracks
        WHERE camera_id = ?
          AND track_type = 'vehicle'
          AND active = 1
        ORDER BY last_seen_ts DESC
    """, (camera_id,)).fetchall()
    
    vehicles = []
    for row in rows:
        track_id, track_key, key_kind, raw_class, color, first_seen, last_seen, box_json = row
        
        # Extract plate_hmac if this track is keyed by plate
        plate_hmac = track_key if key_kind == "plate" else None
        
        vehicles.append({
            "track_id": track_id,
            "track_key": track_key,
            "key_kind": key_kind,
            "plate_hmac": plate_hmac,
            "raw_class": raw_class,
            "color": color,
            "first_seen_ts": first_seen,
            "last_seen_ts": last_seen,
            "box_json": box_json,
        })
    
    return vehicles


def get_plate_visit_history(conn: sqlite3.Connection, plate_hmac: str) -> Optional[dict]:
    """
    Get visit history for a specific license plate.
    
    Returns dict with:
        - plate_hmac: The hashed plate
        - visit_count: Total number of visits
        - first_seen_ts: First time this plate was seen
        - last_seen_ts: Most recent sighting
        - last_camera_id: Which camera last saw it
    """
    row = conn.execute("""
        SELECT 
            plate_hmac,
            visit_count,
            first_seen_ts,
            last_seen_ts,
            last_camera_id
        FROM plate_visitors
        WHERE plate_hmac = ?
    """, (plate_hmac,)).fetchone()
    
    if not row:
        return None
    
    return {
        "plate_hmac": row[0],
        "visit_count": row[1],
        "first_seen_ts": row[2],
        "last_seen_ts": row[3],
        "last_camera_id": row[4],
    }


def is_plate_trusted(conn: sqlite3.Connection, plate_hmac: str) -> Optional[dict]:
    """
    Check if a plate is in the trusted list.
    
    Returns dict with label and enabled status, or None if not trusted.
    """
    row = conn.execute("""
        SELECT label, enabled
        FROM trusted_plates
        WHERE plate_hmac = ? AND enabled = 1
    """, (plate_hmac,)).fetchone()
    
    if not row:
        return None
    
    return {
        "label": row[0],
        "enabled": bool(row[1]),
    }


def format_timestamp(ts: int) -> str:
    """Convert unix timestamp to human-readable datetime."""
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Query current scene status")
    parser.add_argument("--db", required=True, help="Path to echoBell.db")
    parser.add_argument("--camera", type=int, default=1, help="Camera ID (default: 1)")
    args = parser.parse_args()
    
    # Connect to database
    conn = sqlite3.connect(args.db)
    
    print(f"\n{'='*80}")
    print(f"SCENE STATUS - Camera {args.camera}")
    print(f"{'='*80}\n")
    
    # Get active vehicles
    vehicles = get_active_scene_vehicles(conn, args.camera)
    
    if not vehicles:
        print("No active vehicles in scene.\n")
        return
    
    print(f"Found {len(vehicles)} active vehicle(s) in scene:\n")
    
    for i, vehicle in enumerate(vehicles, 1):
        print(f"Vehicle #{i}")
        print(f"  Track ID: {vehicle['track_id']}")
        print(f"  Type: {vehicle['raw_class'] or 'unknown'}")
        print(f"  Color: {vehicle['color'] or 'unknown'}")
        print(f"  Key Kind: {vehicle['key_kind']}")
        print(f"  First Seen: {format_timestamp(vehicle['first_seen_ts'])}")
        print(f"  Last Seen: {format_timestamp(vehicle['last_seen_ts'])}")
        
        # If vehicle has plate, check visit history
        if vehicle['plate_hmac']:
            print(f"  Plate Hash: {vehicle['plate_hmac'][:16]}... (truncated)")
            
            # Check if trusted
            trusted = is_plate_trusted(conn, vehicle['plate_hmac'])
            if trusted:
                print(f"  ✅ TRUSTED: {trusted['label']}")
            
            # Get visit history
            history = get_plate_visit_history(conn, vehicle['plate_hmac'])
            if history:
                if history['visit_count'] == 1:
                    print(f"  🆕 FIRST TIME VISITOR")
                else:
                    print(f"  🔁 REPEAT VISITOR ({history['visit_count']} total visits)")
                    print(f"     First Visit: {format_timestamp(history['first_seen_ts'])}")
                
                # Check if this is a new visit (vs same ongoing visit)
                time_diff = vehicle['last_seen_ts'] - history['first_seen_ts']
                if time_diff < 3600:  # Within 1 hour
                    print(f"     Status: Same ongoing visit")
                else:
                    print(f"     Status: Returning visitor (last visit was {time_diff // 86400} days ago)")
        else:
            print(f"  📍 No plate detected (tracked by IoU)")
        
        print()
    
    # Summary statistics
    print(f"{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    
    first_time_count = 0
    repeat_count = 0
    no_plate_count = 0
    trusted_count = 0
    
    for vehicle in vehicles:
        if vehicle['plate_hmac']:
            history = get_plate_visit_history(conn, vehicle['plate_hmac'])
            if history and history['visit_count'] == 1:
                first_time_count += 1
            elif history:
                repeat_count += 1
            
            if is_plate_trusted(conn, vehicle['plate_hmac']):
                trusted_count += 1
        else:
            no_plate_count += 1
    
    print(f"First-time visitors: {first_time_count}")
    print(f"Repeat visitors: {repeat_count}")
    print(f"Trusted vehicles: {trusted_count}")
    print(f"No plate detected: {no_plate_count}")
    print()
    
    conn.close()


if __name__ == "__main__":
    main()

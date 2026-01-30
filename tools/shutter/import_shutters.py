"""
Import Shutters from JSON to Database

Loads shutter polygons from JSON file (created by shutter_editor.py)
and imports them into the database for a specific camera.

Usage:
    python import_shutters.py <camera_id> <shutters.json>
    
Example:
    python import_shutters.py 1 config/camera1_shutters.json
"""

import json
import sqlite3
import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from packages.data.shutter_service import ShutterService


def import_shutters(db_path: str, camera_id: int, json_path: str):
    """Import shutters from JSON file into database"""
    
    # Load JSON
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    shutters = data.get("shutters", [])
    if not shutters:
        print(f"No shutters found in {json_path}")
        return
    
    # Connect to database
    conn = sqlite3.connect(db_path)
    
    # Import each shutter
    imported = 0
    for idx, sh_dict in enumerate(shutters):
        polygon = [tuple(pt) for pt in sh_dict["points_norm"]]
        mode = sh_dict.get("mode", "ignore")
        name = sh_dict.get("name") or f"Region {idx + 1}"
        
        shutter_id = ShutterService.create_shutter(
            conn=conn,
            camera_id=camera_id,
            polygon=polygon,
            name=name,
            mode=mode,
            enabled=True
        )
        
        print(f"✓ Imported shutter #{shutter_id}: {name} ({len(polygon)} points, mode={mode})")
        imported += 1
    
    conn.close()
    
    print(f"\n✅ Successfully imported {imported} shutters for camera {camera_id}")
    print(f"   Database: {db_path}")
    print(f"   Source: {json_path}")


def main():
    if len(sys.argv) != 3:
        print("Usage: python import_shutters.py <camera_id> <shutters.json>")
        print("\nExample:")
        print("  python import_shutters.py 1 config/camera1_shutters.json")
        print("\nThis imports shutter regions from JSON into the database")
        print("for the specified camera ID.")
        sys.exit(1)
    
    camera_id = int(sys.argv[1])
    json_path = sys.argv[2]
    
    # Use default database path
    db_path = "data/echoBell.db"
    
    if not Path(json_path).exists():
        print(f"Error: JSON file not found: {json_path}")
        sys.exit(1)
    
    if not Path(db_path).exists():
        print(f"Error: Database not found: {db_path}")
        print("Make sure you're running this from the project root directory")
        sys.exit(1)
    
    import_shutters(db_path, camera_id, json_path)


if __name__ == "__main__":
    main()

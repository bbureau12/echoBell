"""
Update cam1_vehicle_simple policy to support photo download from snapshot_url
"""
import sqlite3
import json

conn = sqlite3.connect('data/echoBell.db')
cur = conn.cursor()

# New actions with photo support (works with both snapshot_path and snapshot_url)
new_actions = [
    {
        "type": "telegram",
        "message": "🚗 Vehicle detected on Camera 1: {vehicle_color} {vehicle_type}",
        "send_photo": True,
        # No photo_path specified - will auto-use snapshot_url or snapshot_path from context
        "priority": "normal"
    }
]

cur.execute("""
    UPDATE policy_rules
    SET actions_json = ?
    WHERE id = 'cam1_vehicle_simple'
""", (json.dumps(new_actions),))

conn.commit()

# Verify
row = cur.execute("""
    SELECT id, name, actions_json 
    FROM policy_rules 
    WHERE id = 'cam1_vehicle_simple'
""").fetchone()

print("Updated policy:")
print(f"ID: {row[0]}")
print(f"Name: {row[1]}")
print(f"Actions: {json.dumps(json.loads(row[2]), indent=2)}")

conn.close()
print("\n✅ Policy updated to support photo download from snapshot_url!")

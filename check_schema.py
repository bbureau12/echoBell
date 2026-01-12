import sqlite3

conn = sqlite3.connect('data/doorbell.db')
cur = conn.cursor()

# Get current version
cur.execute('PRAGMA user_version;')
version = cur.fetchone()[0]
print(f"Current database version: {version}")

# List all tables
print("\nExisting tables:")
cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
for row in cur.fetchall():
    print(f"  - {row[0]}")

# Check visitor_events schema
print("\nvisitor_events columns:")
cur.execute("PRAGMA table_info(visitor_events);")
for row in cur.fetchall():
    print(f"  {row[1]} ({row[2]})")

# Check if scene_tracks exists
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='scene_tracks';")
has_scene_tracks = cur.fetchone() is not None
print(f"\nscene_tracks table exists: {has_scene_tracks}")

if has_scene_tracks:
    print("\nscene_tracks columns:")
    cur.execute("PRAGMA table_info(scene_tracks);")
    for row in cur.fetchall():
        print(f"  {row[1]} ({row[2]})")

conn.close()

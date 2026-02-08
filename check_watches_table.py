import sqlite3

conn = sqlite3.connect('data/echoBell.db')
cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [row[0] for row in cursor.fetchall()]

if 'watches' in tables:
    print("✓ watches table exists!")
    
    # Show schema
    cursor = conn.execute("PRAGMA table_info(watches)")
    columns = cursor.fetchall()
    print(f"\nwatches table has {len(columns)} columns:")
    for col in columns:
        print(f"  - {col[1]} ({col[2]})")
else:
    print("✗ watches table NOT found")
    print(f"\nExisting tables: {', '.join(tables)}")

conn.close()

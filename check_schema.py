import sqlite3

conn = sqlite3.connect('doorbell.db')
cur = conn.cursor()

# Check for trusted tables
cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name LIKE 'trusted%'")
tables = cur.fetchall()

if tables:
    print("Found trusted tables:")
    for name, sql in tables:
        print(f"\n=== {name} ===")
        print(sql)
else:
    print("No trusted tables found in database")

# List all tables
cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
all_tables = [row[0] for row in cur.fetchall()]
print(f"\n\nAll tables in database: {', '.join(all_tables)}")

conn.close()

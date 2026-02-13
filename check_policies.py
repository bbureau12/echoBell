import sqlite3

conn = sqlite3.connect('data/echoBell.db')
cur = conn.cursor()

rows = cur.execute("""
    SELECT id, name, enabled, actions_json 
    FROM policy_rules 
    WHERE id LIKE '%cam1%' OR id LIKE '%vehicle%' 
    ORDER BY priority DESC 
    LIMIT 5
""").fetchall()

print("Current vehicle/camera1 policies:")
print("=" * 80)
for row in rows:
    print(f"ID: {row[0]}")
    print(f"Name: {row[1]}")
    print(f"Enabled: {row[2]}")
    print(f"Actions: {row[3][:100]}...")
    print("-" * 80)

conn.close()

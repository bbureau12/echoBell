import sqlite3

conn = sqlite3.connect('data/doorbell.db')

# Check schema
print("signal_rule schema:")
for row in conn.execute("PRAGMA table_info(signal_rule)").fetchall():
    print(f"  {row}")

print("\nRule 36 full row:")
rule = conn.execute('SELECT * FROM signal_rule WHERE id=36').fetchone()
print(rule)

print("\nLast column (contributes_standalone):", rule[-1] if rule else "N/A")

conn.close()

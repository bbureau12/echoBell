import sqlite3
from pathlib import Path

# Connect to database
db_path = Path("doorbell.db")
conn = sqlite3.connect(str(db_path))

# Read and execute migration
migration_path = Path("infra/db/migrations/006_add_trusted_person.sql")
with open(migration_path, 'r') as f:
    migration_sql = f.read()

print(f"Applying migration: {migration_path.name}")
conn.executescript(migration_sql)
conn.commit()

# Verify tables were created
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'trusted%' ORDER BY name")
tables = [row[0] for row in cur.fetchall()]

print(f"\nTrusted tables created: {', '.join(tables)}")

# Check indexes
cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_trusted%' ORDER BY name")
indexes = [row[0] for row in cur.fetchall()]
print(f"Indexes created: {', '.join(indexes)}")

conn.close()
print("\n✓ Migration completed successfully")

import sqlite3, glob, os, pathlib

DB_PATH = pathlib.Path(__file__).resolve().parents[1] / "data" / "doorbell.db"
SCHEMA_PATH = pathlib.Path(__file__).resolve().parents[1] / "infra" / "db" / "schema.sql"
MIGRATIONS_PATH = pathlib.Path(__file__).resolve().parents[1] / "infra" / "db" / "migrations"

def ensure_db_exists():
    """Create DB file and base schema if missing."""
    DB_PATH.parent.mkdir(exist_ok=True)
    new_db = not DB_PATH.exists()
    conn = sqlite3.connect(DB_PATH)
    if new_db:
        print("Initializing new database…")
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()
    conn.close()
    return new_db

def migrate():
    """Apply any migration files newer than PRAGMA user_version."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("PRAGMA user_version;")
    current = cur.fetchone()[0]

    migrations = sorted(glob.glob(os.path.join(MIGRATIONS_PATH, "*.sql")))
    for path in migrations:
        version = int(os.path.basename(path).split("_")[0])
        if version > current:
            print(f"Applying migration {version}: {os.path.basename(path)}")
            with open(path, "r", encoding="utf-8") as f:
                cur.executescript(f.read())
            cur.execute(f"PRAGMA user_version = {version};")
            conn.commit()
    conn.close()

def init_or_migrate():
    ensure_db_exists()
    migrate()

if __name__ == "__main__":
    init_or_migrate()

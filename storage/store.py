import sqlite3, json, datetime

def log_event(db_path, *, etype, intent=None, confidence=None, urgency=None, mode=None, snapshot=None, transcript=None, actions=None):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""INSERT INTO events(type,intent,confidence,urgency,mode,snapshot_path,transcript,actions)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (etype,intent,confidence,urgency,mode,snapshot,transcript,json.dumps(actions) if actions else None))
    conn.commit(); conn.close()

import requests, sqlite3

def send(message:str, priority="normal", db_path="data/doorbell.db"):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    tok = cur.execute("SELECT value FROM settings WHERE key='telegram_token'").fetchone()
    rows = cur.execute("SELECT target FROM notifiers WHERE kind='telegram' AND priority IN (?, 'normal')", (priority,)).fetchall()
    conn.close()
    if not tok: return
    token = tok[0]
    for (chat_id,) in rows:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=5)
        except Exception:
            pass

# packages/classify/intent.py
from dataclasses import dataclass
import sqlite3, re, os

@dataclass
class Classified:
    intent: str
    conf: float
    urgency: int

def _fetch_rules(conn):
    intents = [r[0] for r in conn.execute("SELECT name FROM intent_def").fetchall()]
    patterns = conn.execute("""
        SELECT pattern, is_regex, COALESCE(intent_name,'') AS intent_name,
               COALESCE(entity_name,'') AS entity_name, weight
        FROM pattern_def
    """).fetchall()
    entities = {(n or ''): (t or '', w or 0.5)
                for (n,t,w) in conn.execute("SELECT name, tag, weight FROM entity_def").fetchall()}
    return intents, patterns, entities

def classify(text: str, vision, db_path=None) -> Classified:
    if db_path is None:
        # Get project root (three levels up from this file)
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        db_path = os.path.join(project_root, "data", "doorbell.db")
    
    t = (text or "").lower()

    # Vision-first
    if vision.package_box:
        return Classified("package_drop", 0.9, 10)
    if vision.uniform in ("police","fire"):
        return Classified("authority_urgent", 0.9, 90)

    conn = sqlite3.connect(db_path)
    intents, patterns, entities = _fetch_rules(conn)
    scores = {i: 0.0 for i in intents}

    # Text pattern scoring
    for pattern, is_regex, intent_name, entity_name, weight in patterns:
        hit = False
        if is_regex:
            if re.search(pattern, t, flags=re.IGNORECASE):
                hit = True
        else:
            if pattern.lower() in t:
                hit = True
        if not hit:
            continue
        if intent_name:
            scores[intent_name] = scores.get(intent_name, 0.0) + float(weight)
        if entity_name:
            tag, ew = entities.get(entity_name, ('', 0.0))
            # Entity hint → add some score to typical intent buckets
            if tag == 'utility':
                scores['technician_visit'] = scores.get('technician_visit', 0.0) + ew
            elif tag == 'delivery':
                scores['package_drop'] = scores.get('package_drop', 0.0) + ew
            elif tag == 'authority':
                scores['authority_urgent'] = scores.get('authority_urgent', 0.0) + ew
            elif tag == 'neighbor':
                scores['neighbor_help'] = scores.get('neighbor_help', 0.0) + ew
            elif tag == 'sales':
                scores['sales_solicit'] = scores.get('sales_solicit', 0.0) + ew

    conn.close()

    # Choose top intent
    intent = max(scores, key=scores.get) if scores else "unknown"
    raw = scores.get(intent, 0.0)
    # Convert score to a 0..1-ish confidence (tweakable)
    conf = max(0.4, min(0.95, 0.5 + 0.15 * raw))
    if raw < 0.5:
        intent, conf = "unknown", 0.45

    urgency = 10
    if intent == "neighbor_help": urgency = 20
    if intent == "technician_visit": urgency = 30
    if intent == "authority_urgent": urgency = 90
    return Classified(intent, conf, urgency)

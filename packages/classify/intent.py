# packages/classify/intent.py
from __future__ import annotations
from dataclasses import dataclass
from collections import defaultdict
import sqlite3, re, os
from typing import Dict, List, Tuple

@dataclass(slots=True)
class Classified:
    intent: str
    conf: float
    urgency: int

def _project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

def _default_db_path() -> str:
    return os.path.join(_project_root(), "data", "doorbell.db")

def _fetch_rules(conn: sqlite3.Connection) -> Tuple[List[str], List[Tuple[str,int,str,str,float]], Dict[str, Tuple[str, float]]]:
    # intents
    intents = [r[0] for r in conn.execute("SELECT name FROM intent_def").fetchall()]
    # patterns: (pattern, is_regex, intent_name, entity_name, weight)
    patterns = conn.execute("""
        SELECT pattern, is_regex, COALESCE(intent_name,''), COALESCE(entity_name,''), weight
        FROM pattern_def
    """).fetchall()
    # entities: entity_name -> (tag, weight); tag is used as the *intent key* 1:1
    entities = {(n or ''): (t or '', w if w is not None else 0.5)
                for (n,t,w) in conn.execute("SELECT name, tag, weight FROM entity_def").fetchall()}
    return intents, patterns, entities

def _confidence(raw: float) -> float:
    # tweakable sigmoid-ish clamp
    conf = 0.5 + 0.15 * raw
    return max(0.4, min(0.95, conf))

def classify(text: str, vision, db_path: str | None = None) -> Classified:
    db_path = db_path or _default_db_path()
    t = (text or "").lower()

    # Vision-first short-circuits
    if getattr(vision, "package_box", False):
        return Classified("package_drop", 0.9, 10)
    if getattr(vision, "uniform", None) in {"police", "fire"}:
        return Classified("authority_urgent", 0.9, 90)

    with sqlite3.connect(db_path) as conn:
        intents, patterns, entities = _fetch_rules(conn)

    scores: Dict[str, float] = defaultdict(float)
    for name in intents:
        scores[name] = 0.0  # ensure all defined intents exist

    # Text pattern scoring
    for pattern, is_regex, intent_name, entity_name, weight in patterns:
        # hit?
        hit = False
        if is_regex:
            if re.search(pattern, t, flags=re.IGNORECASE):
                hit = True
        else:
            if pattern.lower() in t:
                hit = True
        if not hit:
            continue

        w = float(weight or 0.0)

        # direct intent bump if present
        if intent_name:
            scores[intent_name] += w

        # entity hint → add score to the tag-as-intent directly (1:1)
        if entity_name:
            tag, ew = entities.get(entity_name, ('', 0.0))
            if tag:  # tag is already the canonical intent key
                scores[tag] += float(ew or 0.0)

    # choose top
    intent = max(scores, key=scores.get) if scores else "unknown"
    raw = scores.get(intent, 0.0)

    # confidence & unknown fallback
    conf = _confidence(raw)
    if raw < 0.5:
        intent, conf = "unknown", 0.45

    # urgency mapping
    urgency_map = {
        "neighbor_help": 20,
        "technician_visit": 30,
        "authority_urgent": 90,
    }
    urgency = urgency_map.get(intent, 10)

    return Classified(intent, conf, urgency)

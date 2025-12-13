# packages/classify/intent.py
from __future__ import annotations
from dataclasses import dataclass, field
from collections import defaultdict
import sqlite3, re, os, sys
from typing import Dict, List, Tuple


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from packages.common.types import Evidence, VisionResult  # shared dataclasses


@dataclass(slots=True)
class Classified:
    intent: str
    conf: float
    urgency: int
    trace: List[str] = field(default_factory=list)


def _project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def _default_db_path() -> str:
    return os.path.join(_project_root(), "data", "doorbell.db")


def _fetch_rules(conn: sqlite3.Connection) -> Tuple[
    List[str],
    List[Tuple[str, int, str, str, float]],
    Dict[str, Tuple[str, float]]
]:
    """
    Text rules:

    - intent_def(name)
    - pattern_def(pattern, is_regex, intent_name, entity_name, weight)
    - entity_def(name, tag, weight)  -- tag is the 'canonical' intent key
    """
    intents = [r[0] for r in conn.execute("SELECT name FROM intent_def").fetchall()]

    patterns = conn.execute("""
        SELECT pattern, is_regex,
               COALESCE(intent_name, ''),
               COALESCE(entity_name, ''),
               weight
        FROM pattern_def
    """).fetchall()

    entities = {
        (n or ''): (t or '', w if w is not None else 0.5)
        for (n, t, w) in conn.execute(
            "SELECT name, tag, weight FROM entity_def"
        ).fetchall()
    }

    return intents, patterns, entities


def _confidence(raw: float) -> float:
    """
    Map a raw score into [0.4, 0.95].
    """
    conf = 0.5 + 0.15 * raw
    return max(0.4, min(0.95, conf))


def _score_signal_rules(conn: sqlite3.Connection, vision: VisionResult):
    """
    Apply signal_rule rows to the evidence in VisionResult.

    Returns:
      scores:    dict[intent_name -> float]
      urgencies: dict[intent_name -> list[int]]
      trace:     list[str]  (human-readable matches)
    """
    evidence: List[Evidence] = getattr(vision, "evidence", []) or []

    rows = conn.execute("""
        SELECT id, source, feature, operator, value, intent_name,
               weight, min_conf, urgency
        FROM signal_rule
        WHERE enabled = 1
        ORDER BY id
    """).fetchall()

    scores: Dict[str, float] = defaultdict(float)
    urgencies: Dict[str, List[int]] = defaultdict(list)
    trace: List[str] = []

    for ev in evidence:
        ev_source = ev.source
        ev_feature = ev.feature
        ev_val = str(ev.value).lower()
        ev_conf = float(ev.conf)
        ev_obj = getattr(ev, "object_id", None)

        for rule_id, source, feature, op, val, intent, weight, min_conf, urg in rows:
            if source != ev_source or feature != ev_feature:
                continue

            min_c = float(min_conf or 0.0)
            if ev_conf < min_c:
                continue

            rule_val = str(val).lower()
            matched = False

            if op == "equals":
                matched = (ev_val == rule_val)
            elif op == "contains":
                matched = (rule_val in ev_val)

            if not matched:
                continue

            w = float(weight or 1.0)
            delta = w * ev_conf
            scores[intent] += delta
            urgencies[intent].append(int(urg or 10))

            trace.append(
                f"[rule {rule_id}] {intent} +{delta:.2f} "
                f"(w={w:.2f}*conf={ev_conf:.2f}, urg={int(urg or 10)}) "
                f"because ev(src={ev_source} feat={ev_feature} val={ev_val} obj={ev_obj}) {op} '{rule_val}'"
            )

    return scores, urgencies, trace



def classify(text: str, vision: VisionResult, db_path: str | None = None) -> Classified:
    """
    Combine TEXT rules + multimodal EVIDENCE rules into a final intent.

    - Text rules come from: intent_def / pattern_def / entity_def
    - Vision/OCR/future fashion/audio rules come from: signal_rule
      acting on `vision.evidence`.
    """
    db_path = db_path or _default_db_path()
    t = (text or "").lower()

    scores: Dict[str, float] = defaultdict(float)
    intent_urgencies: Dict[str, List[int]] = defaultdict(list)

    # Hard-coded fallback urgency for text-only intents.
    # You can move this to intent_def if you want later.
    urgency_map = {
        "neighbor_help": 20,
        "technician_visit": 30,
        "authority_urgent": 90,
    }

    with sqlite3.connect(db_path) as conn:
        # 1) TEXT: pattern/entity scoring
        intents, patterns, entities = _fetch_rules(conn)

        text_raw_scores: Dict[str, float] = defaultdict(float)
        for name in intents:
            text_raw_scores[name] = 0.0

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

            w = float(weight or 0.0)

            if intent_name:
                text_raw_scores[intent_name] += w

            if entity_name:
                tag, ew = entities.get(entity_name, ('', 0.0))
                if tag:
                    text_raw_scores[tag] += float(ew or 0.0)

        # fold best text intent (if any) into unified scores
        if text_raw_scores:
            best_text_intent = max(text_raw_scores, key=text_raw_scores.get)
            raw = text_raw_scores[best_text_intent]
            if raw > 0.0:
                text_conf = _confidence(raw)
                scores[best_text_intent] += text_conf
                intent_urgencies[best_text_intent].append(
                    urgency_map.get(best_text_intent, 10)
                )

        # 2) MULTIMODAL EVIDENCE: signal_rule over vision.evidence
        trace: List[str] = []

        sig_scores, sig_urgencies, sig_trace  = _score_signal_rules(conn, vision)
        trace.extend(sig_trace)

        for intent_name, s in sig_scores.items():
            scores[intent_name] += s
            intent_urgencies[intent_name].extend(sig_urgencies[intent_name])

    # 3) Final decision
    if not scores:
        return Classified("unknown", 0.45, 10, trace=[])

    best_intent = max(scores, key=scores.get)
    total_score = scores[best_intent]

    # simple mapping of total_score to confidence
    #  - 1 strong signal → ~0.75
    #  - multiple agreeing signals → up towards 0.95
    conf = 0.5 + 0.25 * min(total_score, 2.0)
    conf = max(0.4, min(0.95, conf))

    urg_list = intent_urgencies.get(best_intent) or [10]
    urgency = max(urg_list)

    return Classified(best_intent, conf, urgency, trace=trace)

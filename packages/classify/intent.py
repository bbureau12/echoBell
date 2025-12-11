# packages/classify/intent.py
from __future__ import annotations
from dataclasses import dataclass
from collections import defaultdict
import sqlite3, re, os
import sys
from typing import Dict, List, Tuple

from pyparsing import Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from packages.perception.types import Evidence, VisionResult

@dataclass(slots=True)
class Classified:
    intent: str
    conf: float
    urgency: int
    trace: Optional[List[str]] = None  

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

def classify(text: str, vision: VisionResult, db_path: str | None = None, debug: bool = False) -> Classified:
    db_path = db_path or _default_db_path()
    t = (text or "").lower()

    trace: List[str] = []

    scores: Dict[str, float] = defaultdict(float)
    intent_urgencies: Dict[str, List[int]] = defaultdict(list)

    urgency_map = {
        "neighbor_help": 20,
        "technician_visit": 30,
        "authority_urgent": 90,
    }

    with sqlite3.connect(db_path) as conn:
        # 1) TEXT: pattern_def / entity_def scoring
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

        if text_raw_scores and any(v != 0.0 for v in text_raw_scores.values()):
            best_text_intent = max(text_raw_scores, key=text_raw_scores.get)
            raw = text_raw_scores[best_text_intent]
            text_conf = _confidence(raw)

            scores[best_text_intent] += text_conf
            intent_urgencies[best_text_intent].append(
                urgency_map.get(best_text_intent, 10)
            )

            trace.append(
                f"[text] best text intent={best_text_intent}, raw={raw:.3f}, "
                f"mapped_conf={text_conf:.3f}, contributes to scores[{best_text_intent}]"
            )
        else:
            trace.append("[text] no text patterns matched")

        # 2) PERCEPTION: apply signal_rule to vision.evidence
        sig_scores, sig_urgencies = _score_signal_rules(conn, vision, trace=trace)
        for intent_name, s in sig_scores.items():
            scores[intent_name] += s
            intent_urgencies[intent_name].extend(sig_urgencies[intent_name])

    # 3) Decide final intent
    if not scores:
        trace.append("[final] no scores from text or signal → unknown")
        if debug:
            print("\n".join(trace))
        return Classified("unknown", 0.45, 10, trace=trace)

    best_intent = max(scores, key=scores.get)
    total_score = scores[best_intent]
    conf = _confidence(total_score)

    urg_list = intent_urgencies.get(best_intent) or [10]
    urgency = max(urg_list)

    trace.append(
        f"[final] chosen intent={best_intent}, raw_score={total_score:.3f}, "
        f"mapped_conf={conf:.3f}, urgency={urgency}"
    )

    if debug:
        print("\n".join(trace))

    return Classified(best_intent, conf, urgency, trace=trace)




def _score_signal_rules(
    conn: sqlite3.Connection,
    vision: VisionResult,
    trace: Optional[List[str]] = None,
) -> tuple[Dict[str, float], Dict[str, List[int]]]:
    """
    Apply signal_rule rows to the evidence in VisionResult.
    Returns: (scores, urgencies)
      scores:    dict[intent_name -> float]
      urgencies: dict[intent_name -> list[int]]
    """
    evidence: List[Evidence] = getattr(vision, "evidence", []) or []

    rows = conn.execute("""
        SELECT source, feature, operator, value, intent_name,
               weight, min_conf, urgency
        FROM signal_rule
        WHERE enabled = 1
    """).fetchall()

    scores: Dict[str, float] = defaultdict(float)
    urgencies: Dict[str, List[int]] = defaultdict(list)

    if trace is not None:
        trace.append(f"[signal] {len(evidence)} evidence items")

    for ev in evidence:
        ev_source = ev.source
        ev_feature = ev.feature
        ev_val = str(ev.value).lower()
        ev_conf = float(ev.conf)

        for source, feature, op, val, intent, weight, min_conf, urg in rows:
            if source != ev_source or feature != ev_feature:
                continue

            min_c = float(min_conf or 0.0)
            if ev_conf < min_c:
                if trace is not None:
                    trace.append(
                        f"[signal] skip rule intent={intent} because "
                        f"conf={ev_conf:.2f} < min_conf={min_c:.2f} "
                        f"for {source}.{feature}={ev_val!r}"
                    )
                continue

            rule_val = str(val).lower()
            matched = False

            if op == "equals":
                matched = (ev_val == rule_val)
            elif op == "contains":
                matched = (rule_val in ev_val)
            # future: gte, lte, etc.

            if not matched:
                continue

            w = float(weight or 1.0)
            delta = w * ev_conf
            scores[intent] += delta
            urgencies[intent].append(int(urg or 10))

            if trace is not None:
                trace.append(
                    f"[signal] HIT: {source}.{feature}={ev_val!r} (conf={ev_conf:.2f}) "
                    f"matched rule value={rule_val!r} for intent={intent}, "
                    f"weight={w:.2f} → +{delta:.3f} (total={scores[intent]:.3f}), "
                    f"urgency={urg}"
                )

    if trace is not None:
        if scores:
            for intent, s in scores.items():
                trace.append(
                    f"[signal] aggregate for {intent}: score={s:.3f}, urgencies={urgencies[intent]}"
                )
        else:
            trace.append("[signal] no signal_rule matches")

    return scores, urgencies
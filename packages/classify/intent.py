# packages/classify/intent.py
from __future__ import annotations
from dataclasses import dataclass, field
from collections import defaultdict
import sqlite3, re, os, sys
from typing import Dict, List, Tuple


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from packages.common.types import Evidence, VisionResult , RuleMatch # shared dataclasses


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

def _resolve_bind_id(vision: VisionResult, ev_obj_id: int | None, bind_scope: str | None) -> int | None:
    """
    bind_scope controls what "thing" the group binds to.

    Supported:
      - 'scene' -> all evidence shares one bind (None)
      - 'self'  -> bind to the evidence's object_id
      - 'root'  -> bind to top-most ancestor
      - <label> -> bind to nearest ancestor whose label matches (e.g. 'person', 'vehicle')
    """
    scope = (bind_scope or "scene").strip().lower()

    if scope == "scene":
        return None
    if ev_obj_id is None:
        return None

    objs = getattr(vision, "objects", []) or []
    id_to_obj = {o.object_id: o for o in objs}

    if scope == "self":
        return ev_obj_id

    # Walk up parent chain helper
    def walk_up(start_id: int):
        cur = id_to_obj.get(start_id)
        while cur is not None:
            yield cur
            pid = getattr(cur, "parent_id", None)
            if pid is None:
                break
            cur = id_to_obj.get(pid)

    if scope == "root":
        last = None
        for node in walk_up(ev_obj_id):
            last = node
        return getattr(last, "object_id", ev_obj_id) if last else ev_obj_id

    # Otherwise treat scope as a label, e.g. 'person'
    for node in walk_up(ev_obj_id):
        if (getattr(node, "label", "") or "").lower() == scope:
            return node.object_id

    # No matching ancestor label → no bind (prevents accidental cross-object grouping)
    return None


def _score_signal_groups(conn, vision: VisionResult, rule_matches: list[RuleMatch]):
    groups = conn.execute("""
      SELECT id, name, intent_name, group_mode, bind_scope, base_weight, urgency
      FROM signal_group WHERE enabled=1
    """).fetchall()

    members = conn.execute("""
      SELECT group_id, rule_id, required, weight_mul
      FROM signal_group_member
      WHERE enabled=1
    """).fetchall()

    members_by_group = defaultdict(list)
    required_by_group = defaultdict(set)
    for gid, rid, req, mul in members:
        members_by_group[gid].append((int(rid), int(req or 0), float(mul or 1.0)))
        if int(req or 0) == 1:
            required_by_group[gid].add(int(rid))

    # Index matches by rule_id only; bind depends on group.bind_scope
    matches_by_rule = defaultdict(list)
    for m in rule_matches:
        matches_by_rule[int(m.rule_id)].append(m)

    scores = defaultdict(float)
    urgencies = defaultdict(list)
    trace = []

    for gid, name, intent, mode, bind_scope, base_w, g_urg in groups:
        group_members = members_by_group.get(gid, [])
        if not group_members:
            continue

        # Build (rule_id, bind_id) -> [matches] for THIS group (bind_scope aware)
        by_rule_and_bind = defaultdict(list)
        candidate_binds = set()

        for rid, _req, _mul in group_members:
            for m in matches_by_rule.get(rid, []):
                bind_id = _resolve_bind_id(vision, m.ev_obj_id, bind_scope)
                by_rule_and_bind[(rid, bind_id)].append(m)
                candidate_binds.add(bind_id)

        for bind_id in candidate_binds or {None}:
            # required check
            ok = True
            for rid in required_by_group.get(gid, set()):
                if not by_rule_and_bind.get((rid, bind_id)):
                    ok = False
                    break
            if not ok:
                continue

            total = float(base_w or 0.0)

            # add contributions per member (best match wins per rule_id)
            for rid, _req, mul in group_members:
                ms = by_rule_and_bind.get((rid, bind_id), [])
                if not ms:
                    continue
                best = max(ms, key=lambda x: x.delta)
                total += best.delta * float(mul or 1.0)

            scores[str(intent)] += total
            urgencies[str(intent)].append(int(g_urg or 10))
            trace.append(f"[group {name}] {intent} +{total:.2f} bind={bind_id} scope={bind_scope}")

    return scores, urgencies, trace



def _score_signal_rules(conn: sqlite3.Connection, vision: VisionResult):
    evidence: List[Evidence] = getattr(vision, "evidence", []) or []
    objects = getattr(vision, "objects", []) or []
    id_to_obj = {o.object_id: o for o in objects}

    def ancestor_labels(obj_id: int) -> set[str]:
        labels: set[str] = set()
        cur = id_to_obj.get(obj_id)
        while cur is not None:
            if getattr(cur, "label", None):
                labels.add(cur.label.lower())
            pid = getattr(cur, "parent_id", None)
            if pid is None:
                break
            cur = id_to_obj.get(pid)
        return labels

    def parse_scope_any_of(s: str | None) -> set[str]:
        if not s:
            return set()
        raw = {tok.strip().lower() for tok in s.split(",") if tok.strip()}
        if not raw or raw.intersection({"*", "any"}):
            return set()
        return raw

    rows = conn.execute("""
        SELECT id, source, feature, operator, value, intent_name,
               weight, min_conf, urgency,
               COALESCE(scope_any_of,'')
        FROM signal_rule
        WHERE enabled = 1
    """).fetchall()

    # Index rules by (source, feature) so we don't scan all rules for every evidence item
    rules_by_key = defaultdict(list)
    for (rule_id, source, feature, op, val, intent, weight, min_conf, urg, scope_any_of) in rows:
        rules_by_key[(str(source), str(feature))].append(
            (int(rule_id), str(op), str(val), str(intent),
             float(weight or 1.0), float(min_conf or 0.0), int(urg or 10),
             str(scope_any_of or ""))
        )

    scores: Dict[str, float] = defaultdict(float)
    urgencies: Dict[str, List[int]] = defaultdict(list)
    trace: List[str] = []
    rule_matches: List[RuleMatch] = []  # expects your common dataclass

    for ev in evidence:
        ev_source = str(ev.source)
        ev_feature = str(ev.feature)
        ev_val = str(ev.value).lower()
        ev_conf = float(ev.conf)
        ev_obj_id = getattr(ev, "object_id", None)

        # precompute labels for scoped rules
        ev_labels = ancestor_labels(ev_obj_id) if ev_obj_id is not None else set()

        for (rule_id, op, val, intent, weight, min_conf, urg, scope_any_of) in rules_by_key.get((ev_source, ev_feature), []):
            # confidence gate
            if ev_conf < min_conf:
                continue

            # scope gate
            allowed_scopes = parse_scope_any_of(scope_any_of)
            if allowed_scopes:
                if ev_obj_id is None:
                    continue  # scoped rules can't match scene-level evidence
                if ev_labels.isdisjoint(allowed_scopes):
                    continue

            rule_val = str(val).lower()
            matched = False
            if op == "equals":
                matched = (ev_val == rule_val)
            elif op == "contains":
                matched = (rule_val in ev_val)
            else:
                continue  # unknown operator

            if not matched:
                continue

            delta = float(weight) * ev_conf

            # standalone scoring (if you want some rules to be "group-only" later,
            # this is where you'd gate it with a contributes_standalone column)
            scores[intent] += delta
            urgencies[intent].append(urg)

            scope_dbg = ",".join(sorted(allowed_scopes)) if allowed_scopes else "*"
            trace.append(
                f"[signal_rule {rule_id}] {intent} +{delta:.2f} "
                f"(w={weight:.2f}*conf={ev_conf:.2f}, urg={urg}) "
                f"because ev(src={ev_source} feat={ev_feature} val={ev_val} obj={ev_obj_id}) "
                f"{op} '{rule_val}' scope={scope_dbg}"
            )

            # record match for grouping
            rule_matches.append(
            RuleMatch(
                rule_id=rule_id,
                intent_name=str(intent),
                delta=delta,
                urgency=int(urg or 10),

                ev_source=ev_source,
                ev_feature=ev_feature,
                ev_value=ev_val,
                ev_conf=ev_conf,
                ev_obj_id=ev_obj_id,

                op=op,
                rule_value=rule_val,
                scope_any_of=scope_any_of or ""
            )
        )


    return scores, urgencies, trace, rule_matches



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

        sig_scores, sig_urgencies, sig_trace, rule_matches = _score_signal_rules(conn, vision)
        trace.extend(sig_trace)

        grp_scores, grp_urgencies, grp_trace = _score_signal_groups(conn, vision, rule_matches)
        trace.extend(grp_trace)

        for intent_name, s in sig_scores.items():
            scores[intent_name] += s
            intent_urgencies[intent_name].extend(sig_urgencies[intent_name])

        for intent_name, s in grp_scores.items():
            scores[intent_name] += s
            intent_urgencies[intent_name].extend(grp_urgencies[intent_name])

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

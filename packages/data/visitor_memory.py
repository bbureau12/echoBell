# packages/data/visitor_memory.py
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class PriorIntent:
    intent: str
    conf: float
    ts: int
    # Optional: helps you measure "certainty separation" if available
    runnerup_conf: float | None = None
    # Optional: debug/tracing
    source: str | None = None


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    # row tuple: (cid, name, type, notnull, dflt_value, pk)
    return {r[1] for r in rows}


def _pick_col(cols: set[str], *candidates: str) -> str | None:
    """Return the first candidate that exists in cols."""
    for c in candidates:
        if c in cols:
            return c
    return None


def _loads_json(s: Any) -> Any:
    if s is None:
        return None
    if isinstance(s, (dict, list)):
        return s
    if not isinstance(s, str):
        return None
    s = s.strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return None


def _normalize_conf(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
    except Exception:
        return default
    if v != v:  # NaN
        return default
    # keep within [0,1] if it looks like a confidence
    if v < 0.0:
        return 0.0
    if v > 1.0:
        # if you store "scores" that can exceed 1, don't clamp here
        # but for "confidence"-style columns we expect 0..1
        return min(v, 1.0)
    return v


# ----------------------------
# READ: derive a prior intent
# ----------------------------

def fetch_best_prior_intent(
    conn: sqlite3.Connection,
    visitor_id: str,
    *,
    now_ts: int | None = None,
    max_age_days: int = 30,
    min_conf: float = 0.65,
    max_rows: int = 50,
) -> Optional[PriorIntent]:
    """
    Returns the single most useful prior intent for a visitor, derived from visitor_events.

    Strategy (v1):
      - Look at recent events (<= max_age_days)
      - Prefer the most recent high-confidence locked intent
      - If score distribution JSON exists, also return runner-up confidence (optional)

    This function is schema-flexible: it finds column names that exist.
    """
    now_ts = int(now_ts or time.time())
    cols = _table_columns(conn, "visitor_events")

    col_visitor = _pick_col(cols, "visitor_id", "reid_visitor_id", "person_id")
    col_ts = _pick_col(cols, "event_ts", "ts", "created_ts", "created_at_ts", "start_ts")
    col_intent = _pick_col(cols, "intent", "intent_final", "intent_inferred", "classified_intent")
    col_conf = _pick_col(cols, "intent_conf", "intent_confidence", "conf", "confidence")
    col_score_json = _pick_col(cols, "intent_score_json", "intent_scores_json", "scores_json", "score_json")

    if not (col_visitor and col_ts and col_intent):
        # Schema isn't ready / table missing expected fields
        return None

    min_ts = now_ts - int(max_age_days * 86400)

    # Pull the most recent events first; we’ll pick the first acceptable one.
    # (This aligns with “priors should be recent and high-confidence.”)
    select_cols = [col_ts, col_intent]
    if col_conf:
        select_cols.append(col_conf)
    if col_score_json:
        select_cols.append(col_score_json)

    sql = (
        f"SELECT {', '.join(select_cols)} "
        f"FROM visitor_events "
        f"WHERE {col_visitor}=? AND {col_ts}>=? "
        f"ORDER BY {col_ts} DESC "
        f"LIMIT ?"
    )

    rows = conn.execute(sql, (visitor_id, min_ts, max_rows)).fetchall()
    if not rows:
        return None

    for r in rows:
        # Unpack by position
        idx = 0
        ev_ts = int(r[idx]); idx += 1
        intent = (r[idx] or "").strip(); idx += 1
        if not intent:
            continue

        conf = 0.0
        if col_conf:
            conf = _normalize_conf(r[idx], default=0.0)
            idx += 1

        scores = None
        if col_score_json:
            scores = _loads_json(r[idx])
            idx += 1

        # If confidence column absent, attempt to infer from scores JSON.
        if conf <= 0.0 and isinstance(scores, dict) and intent in scores:
            conf = _normalize_conf(scores.get(intent), default=0.0)

        if conf < float(min_conf):
            continue

        runnerup_conf = None
        if isinstance(scores, dict) and scores:
            # Find runner-up confidence (if any)
            items = []
            for k, v in scores.items():
                try:
                    items.append((str(k), float(v)))
                except Exception:
                    continue
            items.sort(key=lambda kv: kv[1], reverse=True)
            if len(items) >= 2:
                if items[0][0] == intent:
                    runnerup_conf = float(items[1][1])
                else:
                    # if stored intent differs from top score, still compute runner-up
                    runnerup_conf = float(items[0][1])

        return PriorIntent(
            intent=intent,
            conf=conf,
            ts=ev_ts,
            runnerup_conf=runnerup_conf,
            source="visitor_events",
        )

    return None


# --------------------------------
# WRITE: record intent to events
# --------------------------------

def log_visitor_event_intent(
    conn: sqlite3.Connection,
    *,
    visitor_id: str,
    event_ts: int,
    intent: str,
    intent_conf: float,
    intent_scores: dict[str, float] | None = None,
    evidence: dict[str, Any] | None = None,
    event_id: str | None = None,
) -> None:
    """
    Writes an intent result into visitor_events.

    You can call this when intent is LOCKED for the visit session.
    If your schema doesn't have some columns yet, the function will write what it can.

    NOTE: This assumes visitor_events exists.
    """
    cols = _table_columns(conn, "visitor_events")

    col_event_id = _pick_col(cols, "event_id", "visit_id", "session_id")
    col_visitor = _pick_col(cols, "visitor_id", "reid_visitor_id", "person_id")
    col_ts = _pick_col(cols, "event_ts", "ts", "created_ts", "created_at_ts", "start_ts")
    col_intent = _pick_col(cols, "intent", "intent_final", "intent_inferred", "classified_intent")
    col_conf = _pick_col(cols, "intent_conf", "intent_confidence", "conf", "confidence")
    col_score_json = _pick_col(cols, "intent_score_json", "intent_scores_json", "scores_json", "score_json")
    col_evidence_json = _pick_col(cols, "evidence_json", "evidence", "trace_json", "debug_json")

    if not (col_visitor and col_ts and col_intent):
        raise RuntimeError("visitor_events schema missing required columns (visitor_id, event_ts, intent).")

    fields: list[str] = []
    values: list[Any] = []

    def add(col: str | None, val: Any) -> None:
        if col and col in cols:
            fields.append(col)
            values.append(val)

    add(col_event_id, event_id)
    add(col_visitor, visitor_id)
    add(col_ts, int(event_ts))
    add(col_intent, intent)
    add(col_conf, float(intent_conf))

    if intent_scores is not None:
        add(col_score_json, json.dumps(intent_scores, separators=(",", ":"), ensure_ascii=False))

    if evidence is not None:
        add(col_evidence_json, json.dumps(evidence, separators=(",", ":"), ensure_ascii=False))

    placeholders = ", ".join(["?"] * len(fields))
    sql = f"INSERT INTO visitor_events ({', '.join(fields)}) VALUES ({placeholders})"
    conn.execute(sql, values)


# ----------------------------
# OPTIONAL: helper utilities
# ----------------------------

def compute_prior_weight(
    prior: PriorIntent,
    *,
    now_ts: int | None = None,
    half_life_days: float = 14.0,
    max_weight: float = 0.25,
) -> float:
    """
    Turns a prior intent into a capped weight to add into your classifier score.
    Decays over time; caps to max_weight.
    """
    now_ts = int(now_ts or time.time())
    age_s = max(0, now_ts - int(prior.ts))
    age_days = age_s / 86400.0
    # Exponential-ish decay using half-life
    if half_life_days <= 0:
        decay = 1.0
    else:
        decay = 0.5 ** (age_days / half_life_days)

    w = float(prior.conf) * decay * float(max_weight)
    if w < 0:
        return 0.0
    return min(w, float(max_weight))
# packages/data/visitor_memory.py
from __future__ import annotations
import json, sqlite3
from typing import Any, Optional

def create_visitor_event(
    conn: sqlite3.Connection,
    *,
    event_id: str,
    visitor_id: str,
    detected_ts_iso: str,   # e.g. "2025-12-18 19:22:11"
    evidence: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO visitor_events (
            event_id, visitor_id, detected_ts, evidence_json
        ) VALUES (?, ?, ?, ?)
        """,
        (
            event_id,
            visitor_id,
            detected_ts_iso,
            json.dumps(evidence, separators=(",", ":"), ensure_ascii=False) if evidence else None,
        ),
    )
    

def update_visitor_event_intent(
    conn: sqlite3.Connection,
    *,
    event_id: str,
    intent: str,
    intent_conf: float,
    evidence: dict[str, Any] | None = None,
    duration_s: float | None = None,
) -> None:
    conn.execute(
        """
        UPDATE visitor_events
        SET intent_inferred=?,
            intent_confidence=?,
            duration_s=COALESCE(?, duration_s),
            evidence_json=COALESCE(?, evidence_json)
        WHERE event_id=?
        """,
        (
            intent,
            float(intent_conf),
            duration_s,
            json.dumps(evidence, separators=(",", ":"), ensure_ascii=False) if evidence else None,
            event_id,
        ),
    )

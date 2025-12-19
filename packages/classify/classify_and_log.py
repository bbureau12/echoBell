# packages/classify/classify_and_log.py
from __future__ import annotations

import sqlite3, time, uuid
from datetime import datetime
from typing import Optional

from packages.common.types import VisionResult
from packages.classify.intent import classify, Classified
from packages.data.visitor_memory import create_visitor_event, update_visitor_event_intent

def _choose_actor_visitor_id(vr: VisionResult) -> Optional[str]:
    best_vid = None
    best_sim = -1.0
    best_conf = -1.0

    for obj in (vr.objects or []):
        if (obj.label or "").lower() != "person":
            continue
        vid = obj.props.get("visitor_id")
        if not vid:
            continue

        sim = float(obj.props.get("visitor_similarity") or 0.0)
        conf = float(obj.props.get("conf") or 0.0)

        if sim > best_sim or (sim == best_sim and conf > best_conf):
            best_sim = sim
            best_conf = conf
            best_vid = str(vid)

    return best_vid

def _iso_now(now_ts: int) -> str:
    # SQLite DATETIME friendly "YYYY-MM-DD HH:MM:SS"
    return datetime.fromtimestamp(now_ts).strftime("%Y-%m-%d %H:%M:%S")

def classify_and_log(
    *,
    db_path: str,
    vision: VisionResult,
    text: str = "",
    event_id: str | None = None,
    now_ts: int | None = None,
    lock_conf_threshold: float = 0.85,
) -> tuple[Classified, str]:
    now_ts = int(now_ts or time.time())
    event_id = event_id or str(uuid.uuid4())

    # Choose actor first so we can log REID info even if we later skip intent updates.
    actor = _choose_actor(vision)  # return (visitor_id, object_id, similarity, kind)
    if not actor:
        classified = classify(text=text, vision=vision, db_path=db_path)
        return classified, event_id

    visitor_id, person_object_id, similarity, kind = actor

    classified = classify(text=text, vision=vision, db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        create_visitor_event(
            conn,
            event_id=event_id,
            visitor_id=visitor_id,
            detected_ts_iso=_iso_now(now_ts),
            evidence={
                "snapshot_path": getattr(vision, "snapshot_path", None),
                "actor_object_id": person_object_id,
                "visitor_kind": kind,
                "visitor_similarity": similarity,
                "intent": classified.intent,
                "intent_conf": classified.conf,
                "trace": classified.trace,
            },
        )

        if classified.conf >= lock_conf_threshold:
            update_visitor_event_intent(
                conn,
                event_id=event_id,
                intent=classified.intent,
                intent_conf=classified.conf,
                evidence={
                    "snapshot_path": getattr(vision, "snapshot_path", None),
                    "actor_object_id": person_object_id,
                    "visitor_kind": kind,
                    "visitor_similarity": similarity,
                    "trace": classified.trace,
                },
            )

        conn.commit()

    return classified, event_id

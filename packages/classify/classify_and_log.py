# packages/classify/classify_and_log.py
from __future__ import annotations

import sqlite3, time, uuid
from datetime import datetime
from typing import Optional

from packages.common.types import VisionResult
from packages.classify.intent import classify, Classified
from packages.data.visitor_memory import create_visitor_event, update_visitor_event_intent
from packages.common.config_models import RetentionSettings

def _choose_actor_visitor_id(vr: VisionResult) -> Optional[tuple[str, str, float, str]]:
    """
    Find the best visitor match from vision results.
    Returns (visitor_id, object_id, similarity, kind) or None.
    """
    best_vid = None
    best_object_id = None
    best_sim = -1.0
    best_conf = -1.0
    best_kind = None

    for obj in (vr.objects or []):
        if (obj.label or "").lower() != "person":
            continue
        vid = obj.props.get("visitor_id")
        if not vid:
            continue

        sim = float(obj.props.get("visitor_similarity") or 0.0)
        conf = float(obj.props.get("conf") or 0.0)
        kind = obj.props.get("visitor_kind", "unknown")

        if sim > best_sim or (sim == best_sim and conf > best_conf):
            best_sim = sim
            best_conf = conf
            best_vid = str(vid)
            best_object_id = obj.object_id
            best_kind = str(kind)

    if best_vid is None:
        return None
    
    return (best_vid, best_object_id, best_sim, best_kind)

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
    snapshot_service = None,
    frame_bgr = None,
    camera_id: int | None = None,
    retention: RetentionSettings | None = None,
) -> tuple[Classified, str]:
    """
    Classify intent and log visitor event.
    
    Args:
        retention: RetentionSettings for snapshot saving behavior. 
                   If None, uses defaults (save_visitor_snapshot=True, gap_between_visits_seconds=3600)
    """
    if retention is None:
        retention = RetentionSettings()
    
    now_ts = int(now_ts or time.time())
    event_id = event_id or str(uuid.uuid4())

    # Choose actor first so we can log REID info even if we later skip intent updates.
    actor = _choose_actor_visitor_id(vision)  # return (visitor_id, object_id, similarity, kind)
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
            intent=classified.intent,
            intent_conf=classified.conf,
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

        # Save snapshot if needed (after event is created so we have event_id)
        if retention.save_visitor_snapshot and snapshot_service and camera_id is not None and frame_bgr is not None:
            from packages.data.snapshot_service import SnapshotMetadata
            
            # Determine if we should save snapshot
            is_new_visitor = (kind == "new")
            should_save = snapshot_service.should_save_snapshot(
                conn=conn,
                visitor_id=visitor_id,
                camera_id=camera_id,
                now_ts=now_ts,
                is_new_visitor=is_new_visitor,
                min_interval_seconds=retention.gap_between_visits_seconds,
            )
            
            if should_save:
                snapshot_service.save_snapshot(
                    conn=conn,
                    image=frame_bgr,
                    metadata=SnapshotMetadata(
                        camera_id=camera_id,
                        timestamp=now_ts,
                        visitor_event_id=event_id,
                    ),
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

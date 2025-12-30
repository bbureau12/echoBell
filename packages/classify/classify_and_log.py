# packages/classify/classify_and_log.py
from __future__ import annotations

import sqlite3, time, uuid
from datetime import datetime
from typing import Optional, Sequence

from packages.common.types import VisionResult
from packages.classify.intent import classify, Classified
from packages.data.visitor_memory import create_visitor_event, update_visitor_event_intent
from packages.common.config_models import RetentionSettings

# NEW: only for typing; avoid hard import cycles
from dataclasses import dataclass

@dataclass(frozen=True)
class PlateRead:
    raw_text: str
    conf: float
    object_id: Optional[int] = None


def _choose_actor_visitor_id(vr: VisionResult) -> Optional[tuple[str, str, float, str]]:
    ...
    # unchanged


def _iso_now(now_ts: int) -> str:
    return datetime.fromtimestamp(now_ts).strftime("%Y-%m-%d %H:%M:%S")


def classify_and_log(
    *,
    db_path: str,
    vision: VisionResult,
    text: str = "",
    event_id: str | None = None,
    now_ts: int | None = None,
    lock_conf_threshold: float = 0.85,
    snapshot_service=None,
    frame_bgr=None,
    camera_id: int | None = None,
    retention: RetentionSettings | None = None,

    # NEW:
    plate_service=None,                       # PlateService
    plate_reads: Sequence[PlateRead] = (),    # extracted upstream
    plate_conf_threshold: float = 0.65,
) -> tuple[Classified, str]:
    if retention is None:
        retention = RetentionSettings()

    now_ts = int(now_ts or time.time())
    event_id = event_id or str(uuid.uuid4())

    classified = classify(
        text=text, 
        vision=vision, 
        db_path=db_path,
        plate_service=plate_service,
    )

    actor = _choose_actor_visitor_id(vision)
    visitor_id = None
    person_object_id = None
    similarity = None
    kind = None
    if actor:
        visitor_id, person_object_id, similarity, kind = actor

    with sqlite3.connect(db_path) as conn:
        # 1) Always create the event (visitor_id may be None)
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

        # 2) Link plates to event (evidence only)
        if plate_service is not None and plate_reads:
            # Ensure link table exists (or do this in a migration/ensure_schema elsewhere)
            conn.execute("""
            CREATE TABLE IF NOT EXISTS visitor_event_plate_sightings (
              id          INTEGER PRIMARY KEY AUTOINCREMENT,
              event_id    TEXT NOT NULL,
              plate_hmac  TEXT NOT NULL,
              confidence  REAL,
              camera_id   INTEGER,
              object_id   INTEGER,
              created_ts  INTEGER NOT NULL,
              FOREIGN KEY (event_id) REFERENCES visitor_events(event_id)
            );
            """)
            conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_veps_event_plate
              ON visitor_event_plate_sightings(event_id, plate_hmac);
            """)
            conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_veps_event
              ON visitor_event_plate_sightings(event_id);
            """)
            conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_veps_plate
              ON visitor_event_plate_sightings(plate_hmac);
            """)

            for pr in plate_reads:
                if not pr.raw_text or float(pr.conf) < plate_conf_threshold:
                    continue

                rr = plate_service.upsert_plate_visit(
                    conn,
                    raw_plate_text=pr.raw_text,
                    camera_id=camera_id,
                    seen_ts=now_ts,
                )
                if rr is None:
                    continue

                # Insert if new; if it exists, keep the max confidence
                conn.execute(
                    """
                    INSERT INTO visitor_event_plate_sightings
                      (event_id, plate_hmac, confidence, camera_id, object_id, created_ts)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(event_id, plate_hmac) DO UPDATE SET
                      confidence = CASE
                        WHEN excluded.confidence > visitor_event_plate_sightings.confidence
                        THEN excluded.confidence
                        ELSE visitor_event_plate_sightings.confidence
                      END,
                      camera_id = COALESCE(excluded.camera_id, visitor_event_plate_sightings.camera_id),
                      object_id = COALESCE(excluded.object_id, visitor_event_plate_sightings.object_id);
                    """,
                    (event_id, rr.plate_hmac, float(pr.conf), camera_id, pr.object_id, now_ts),
                )

        # 3) Snapshot saving (unchanged; now works even for visitor_id=None? you'll likely want to guard)
        if (
            retention.save_visitor_snapshot
            and snapshot_service
            and camera_id is not None
            and frame_bgr is not None
            and visitor_id is not None
        ):
            from packages.data.snapshot_service import SnapshotMetadata

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

        # 4) Lock intent (only if we have an actor? you decide; currently it assumes event exists)
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

# packages/classify/classify_and_log.py
from __future__ import annotations

import sqlite3, time, uuid
from datetime import datetime
from typing import Optional, Sequence

from packages.common.types import VisionResult
from packages.classify.intent import classify, Classified
from packages.data.visitor_memory import create_visitor_event, update_visitor_event_intent
from packages.common.config_models import RetentionSettings
from packages.scene.scene_tracker import SceneTracker, build_observations_from_vision

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


def _ensure_plate_sighting_schema(conn: sqlite3.Connection) -> None:
    """Create visitor_event_plate_sightings table if it doesn't exist."""
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


def _link_plates_to_event(
    conn: sqlite3.Connection,
    *,
    plate_service,
    plate_reads: Sequence[PlateRead],
    plate_conf_threshold: float,
    event_id: str,
    camera_id: int | None,
    now_ts: int,
) -> dict[int, str]:
    """
    Process plate reads and link them to the visitor event.
    Returns a dict mapping object_id -> plate_hmac for scene tracking.
    """
    plate_hmac_by_object_id = {}
    
    if not plate_service or not plate_reads:
        return plate_hmac_by_object_id
    
    _ensure_plate_sighting_schema(conn)
    
    for pr in plate_reads:
        if not pr.raw_text:
            print(f"[DEBUG] Skipping plate read: empty raw_text")
            continue
            
        if float(pr.conf) < plate_conf_threshold:
            print(f"[DEBUG] Skipping plate '{pr.raw_text}': conf {pr.conf:.4f} < threshold {plate_conf_threshold}")
            continue
        
        print(f"[DEBUG] Processing plate '{pr.raw_text}' with conf {pr.conf:.4f}")

        rr = plate_service.upsert_plate_visit(
            conn,
            raw_plate_text=pr.raw_text,
            camera_id=camera_id,
            seen_ts=now_ts,
        )
        print(f"[DEBUG] upsert_plate_visit returned: {rr}")
        if rr is None:
            print(f"[DEBUG] Skipping plate '{pr.raw_text}': upsert returned None")
            continue

        # Store plate_hmac for scene tracking (if object_id is available)
        if pr.object_id is not None and rr.plate_hmac:
            plate_hmac_by_object_id[pr.object_id] = rr.plate_hmac

        # Link plate to event
        print(f"[DEBUG] Inserting into visitor_event_plate_sightings: event_id={event_id}, plate_hmac={rr.plate_hmac}, conf={pr.conf:.4f}")
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
    
    return plate_hmac_by_object_id


def _update_scene_tracking(
    conn: sqlite3.Connection,
    *,
    scene_tracker,
    vision: VisionResult,
    plate_hmac_by_object_id: dict[int, str],
    camera_id: int,
    now_ts: int,
    event_id: str,
) -> None:
    """Update scene tracks and add scene evidence to vision result."""
    if not scene_tracker or camera_id is None:
        return
    
    scene_tracker.ensure_schema(conn)
    observations = build_observations_from_vision(vision, plate_hmac_by_object_id=plate_hmac_by_object_id)
    
    scene_evidence = scene_tracker.update(
        conn,
        camera_id=camera_id,
        now_ts=now_ts,
        observations=observations,
        event_id=event_id,
    )
    
    if scene_evidence:
        vision.evidence.extend(scene_evidence)
        print(f"[SCENE] Added {len(scene_evidence)} scene tracking evidence entries")


def _save_visitor_snapshot(
    conn: sqlite3.Connection,
    *,
    snapshot_service,
    retention: RetentionSettings,
    frame_bgr,
    camera_id: int | None,
    visitor_id: str | None,
    kind: str | None,
    now_ts: int,
    event_id: str,
) -> None:
    """Save visitor snapshot if conditions are met."""
    if not (
        retention.save_visitor_snapshot
        and snapshot_service
        and camera_id is not None
        and frame_bgr is not None
        and visitor_id is not None
    ):
        return
    
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
    plate_service=None,
    plate_reads: Sequence[PlateRead] = (),
    plate_conf_threshold: float = 0.65,
    scene_tracker=None,
) -> tuple[Classified, str]:
    """
    Classify intent and log visitor event with all associated data.
    
    Handles:
    - Intent classification from text and vision evidence
    - Visitor event creation
    - Plate sighting linkage
    - Scene tracking (vehicle/person enter/exit)
    - Snapshot saving
    - Intent locking when confidence is high
    """
    # Initialize defaults
    retention = retention or RetentionSettings()
    now_ts = int(now_ts or time.time())
    event_id = event_id or str(uuid.uuid4())

    # Classify intent
    classified = classify(
        text=text, 
        vision=vision, 
        db_path=db_path,
        plate_service=plate_service,
    )

    # Extract actor information
    actor = _choose_actor_visitor_id(vision)
    visitor_id, person_object_id, similarity, kind = None, None, None, None
    if actor:
        visitor_id, person_object_id, similarity, kind = actor

    # Database operations
    with sqlite3.connect(db_path) as conn:
        # 1) Create visitor event
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

        # 2) Link plates to event and get HMACs for scene tracking
        plate_hmac_by_object_id = _link_plates_to_event(
            conn,
            plate_service=plate_service,
            plate_reads=plate_reads,
            plate_conf_threshold=plate_conf_threshold,
            event_id=event_id,
            camera_id=camera_id,
            now_ts=now_ts,
        )
        
        # 3) Update scene tracking (vehicles/people entering/exiting)
        _update_scene_tracking(
            conn,
            scene_tracker=scene_tracker,
            vision=vision,
            plate_hmac_by_object_id=plate_hmac_by_object_id,
            camera_id=camera_id,
            now_ts=now_ts,
            event_id=event_id,
        )

        # 4) Save visitor snapshot if applicable
        _save_visitor_snapshot(
            conn,
            snapshot_service=snapshot_service,
            retention=retention,
            frame_bgr=frame_bgr,
            camera_id=camera_id,
            visitor_id=visitor_id,
            kind=kind,
            now_ts=now_ts,
            event_id=event_id,
        )

        # 5) Lock intent if confidence is high enough
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

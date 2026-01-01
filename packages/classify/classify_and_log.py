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
from packages.scene import scene_linkage

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
    vision: VisionResult,
) -> tuple[dict[int, str], list]:
    """
    Process plate reads and link them to the visitor event.
    Also adds trusted plate info to vehicle SceneObject props.
    Returns:
        - dict mapping object_id -> plate_hmac for scene tracking
        - list of Evidence for trusted plates
    """
    plate_hmac_by_object_id = {}
    trusted_plate_evidence = []
    
    if not plate_service or not plate_reads:
        return plate_hmac_by_object_id, trusted_plate_evidence
    
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

        # Check if plate is trusted and add evidence
        trusted_info = plate_service.is_plate_trusted(conn, pr.raw_text)
        if trusted_info:
            print(f"[DEBUG] Plate '{pr.raw_text}' is TRUSTED with label '{trusted_info['label']}'")
            from packages.common.types import Evidence
            trusted_plate_evidence.append(
                Evidence(
                    source="plate_trust",
                    key="trusted_plate",
                    value=trusted_info["label"],
                    confidence=1.0,
                    object_id=pr.object_id
                )
            )
            
            # Also add to vehicle SceneObject props
            if pr.object_id is not None and vision.objects:
                for obj in vision.objects:
                    if obj.object_id == pr.object_id and obj.label == "vehicle":
                        obj.props["trusted_plate_label"] = trusted_info["label"]
                        obj.props["is_trusted_plate"] = True
                        print(f"[DEBUG] Added trusted_plate_label='{trusted_info['label']}' to vehicle object_id={pr.object_id}")
                        break

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
    
    return plate_hmac_by_object_id, trusted_plate_evidence


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


def _add_visitor_intent_history(
    conn: sqlite3.Connection,
    *,
    vision: VisionResult,
    now_ts: int,
    intent_persistence_window_s: int = 3600,
) -> None:
    """
    Add recent intent history for known visitors (cross-camera intent persistence).
    
    If this visitor_id was recently classified with an intent at ANY camera,
    add it as evidence to help maintain intent consistency across cameras.
    
    Example: Fire fighter exits truck at camera 1 (classified as "authority_urgent"),
    then walks to camera 2 (front door). This function adds evidence that they
    were recently classified as authority, enabling consistent classification.
    
    Args:
        intent_persistence_window_s: How long to carry forward intent (default 1 hour)
    """
    if not vision.objects:
        return
    
    try:
        from packages.common.types import Evidence
        
        for obj in vision.objects:
            if obj.label.lower() != "person":
                continue
            
            visitor_id = obj.props.get("visitor_id")
            if not visitor_id:
                continue
            
            # Query most recent intent for this visitor_id
            row = conn.execute("""
                SELECT intent_inferred, urgency, intent_confidence, detected_ts
                FROM visitor_events
                WHERE visitor_id = ?
                  AND intent_inferred IS NOT NULL
                ORDER BY detected_ts DESC
                LIMIT 1
            """, (visitor_id,)).fetchone()
            
            if not row:
                continue
            
            intent, urgency, conf, detected_ts = row
            age_s = now_ts - int(detected_ts)
            
            # Only carry forward if within persistence window (same visit)
            if age_s > intent_persistence_window_s:
                print(f"[INTENT_HISTORY] Visitor {visitor_id[:8]}... last seen {age_s}s ago (beyond {intent_persistence_window_s}s window)")
                continue
            
            # Add historical intent as evidence
            vision.evidence.append(
                Evidence(
                    source="visitor_history",
                    key="recent_intent",
                    value=str(intent),
                    confidence=float(conf or 0.5) * 0.8,  # Slightly reduce confidence for historical data
                    object_id=obj.object_id,
                    metadata={
                        "age_seconds": age_s,
                        "urgency": int(urgency or 10),
                    }
                )
            )
            print(f"[INTENT_HISTORY] Added recent intent '{intent}' for visitor {visitor_id[:8]}... (age={age_s}s, conf={conf:.2f})")
            
    except Exception as e:
        # Don't fail the whole request if intent history lookup fails
        print(f"[INTENT_HISTORY] Warning: Intent history lookup failed: {e}")


def _link_people_to_vehicles(
    conn: sqlite3.Connection,
    *,
    vision: VisionResult,
    camera_id: int,
    now_ts: int,
    event_id: str,
    first_appearance_window_s: int = 3,
) -> None:
    """
    Link people to vehicles they arrived with (first appearance only).
    Adds evidence to vision result for classification.
    """
    try:
        # Compute person-to-vehicle links
        scene_linkage.ensure_schema(conn)
        
        links = scene_linkage.compute_visit_links_for_snapshot(
            objects=vision.objects or [],
            relation="arrived_with_vehicle",
            conn=conn,
            camera_id=camera_id,
            now_ts=now_ts,
            first_appearance_window_s=first_appearance_window_s,
        )
        
        if links:
            # Persist the links
            count = scene_linkage.upsert_visit_links(
                conn,
                visit_id=event_id,
                camera_id=camera_id,
                now_ts=now_ts,
                links=links,
            )
            print(f"[LINKAGE] Created {count} person-to-vehicle links")
            
            # Add evidence for classification
            link_evidence = scene_linkage.links_to_evidence(links)
            if link_evidence:
                vision.evidence.extend(link_evidence)
                print(f"[LINKAGE] Added {len(link_evidence)} linkage evidence entries")
    except Exception as e:
        # Don't fail the whole request if linkage fails
        print(f"[LINKAGE] Warning: Person-to-vehicle linkage failed: {e}")
    
    # PHASE 1c2: Link packages to people (carrying detection)
    try:
        package_links = scene_linkage.compute_package_to_person_links(
            objects=vision.objects or [],
            conn=conn,
            camera_id=camera_id,
            now_ts=now_ts,
            relation="carrying_package",
            first_appearance_window_s=first_appearance_window_s,
        )
        
        if package_links:
            # Persist the links
            count = scene_linkage.upsert_visit_links(
                conn,
                visit_id=event_id,
                camera_id=camera_id,
                now_ts=now_ts,
                links=package_links,
            )
            print(f"[LINKAGE] Created {count} package-to-person links")
            
            # Add evidence for classification
            pkg_evidence = scene_linkage.links_to_evidence(package_links)
            if pkg_evidence:
                vision.evidence.extend(pkg_evidence)
                print(f"[LINKAGE] Added {len(pkg_evidence)} package linkage evidence entries")
    except Exception as e:
        # Don't fail the whole request if linkage fails
        print(f"[LINKAGE] Warning: Package-to-person linkage failed: {e}")
    
    # PHASE 1c3: Detect package pickups (person takes existing package)
    try:
        pickup_links = scene_linkage.detect_package_pickup(
            objects=vision.objects or [],
            conn=conn,
            camera_id=camera_id,
            now_ts=now_ts,
            relation="picked_up_package",
            min_dwell_time_s=2,  # Package must be in bbox for 2+ seconds
        )
        
        if pickup_links:
            # Persist the links
            count = scene_linkage.upsert_visit_links(
                conn,
                visit_id=event_id,
                camera_id=camera_id,
                now_ts=now_ts,
                links=pickup_links,
            )
            print(f"[LINKAGE] Detected {count} package pickup events")
            
            # Add evidence for classification
            pickup_evidence = scene_linkage.links_to_evidence(pickup_links)
            if pickup_evidence:
                vision.evidence.extend(pickup_evidence)
                print(f"[LINKAGE] Added {len(pickup_evidence)} pickup evidence entries")
    except Exception as e:
        # Don't fail the whole request if linkage fails
        print(f"[LINKAGE] Warning: Package pickup detection failed: {e}")
    
    # PHASE 1c4: Detect package drop-offs (person leaves package)
    try:
        dropoff_links = scene_linkage.detect_package_dropoff(
            objects=vision.objects or [],
            conn=conn,
            camera_id=camera_id,
            now_ts=now_ts,
            relation="dropped_off_package",
            min_separation_time_s=2,  # Package must be separated for 2+ seconds
        )
        
        if dropoff_links:
            # Persist the links
            count = scene_linkage.upsert_visit_links(
                conn,
                visit_id=event_id,
                camera_id=camera_id,
                now_ts=now_ts,
                links=dropoff_links,
            )
            print(f"[LINKAGE] Detected {count} package drop-off events")
            
            # Add evidence for classification
            dropoff_evidence = scene_linkage.links_to_evidence(dropoff_links)
            if dropoff_evidence:
                vision.evidence.extend(dropoff_evidence)
                print(f"[LINKAGE] Added {len(dropoff_evidence)} drop-off evidence entries")
    except Exception as e:
        # Don't fail the whole request if linkage fails
        print(f"[LINKAGE] Warning: Package drop-off detection failed: {e}")


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
    
    Flow:
    1. Enrich vision.evidence with all available context (plates, scene, linkage, history)
    2. Classify intent using enriched evidence
    3. Create visitor event and persist all data
    
    Handles:
    - Trusted plate detection and evidence generation
    - Scene tracking (vehicle/person enter/exit)
    - Person-vehicle linkage
    - Cross-camera intent persistence (visitor history)
    - Intent classification from text and enriched vision evidence
    - Visitor event creation
    - Snapshot saving
    - Intent locking when confidence is high
    
    Args:
        retention: Retention settings including intent_persistence_window_s (default 3600s = 1 hour)
    """
    # Initialize defaults
    retention = retention or RetentionSettings()
    now_ts = int(now_ts or time.time())
    event_id = event_id or str(uuid.uuid4())

    # PHASE 1: Enrich vision.evidence with contextual data
    # This must happen BEFORE classification so the classifier sees complete evidence
    with sqlite3.connect(db_path) as conn:
        # 1a) Link plates to event - adds trusted_plate evidence to vision.evidence
        plate_hmac_by_object_id, trusted_plate_evidence = _link_plates_to_event(
            conn,
            plate_service=plate_service,
            plate_reads=plate_reads,
            plate_conf_threshold=plate_conf_threshold,
            event_id=event_id,
            camera_id=camera_id,
            now_ts=now_ts,
            vision=vision,
        )
        
        if trusted_plate_evidence:
            vision.evidence.extend(trusted_plate_evidence)
            print(f"[ENRICH] Added {len(trusted_plate_evidence)} trusted plate evidence entries")
        
        # 1b) Update scene tracking - adds scene.* evidence to vision.evidence
        _update_scene_tracking(
            conn,
            scene_tracker=scene_tracker,
            vision=vision,
            plate_hmac_by_object_id=plate_hmac_by_object_id,
            camera_id=camera_id,
            now_ts=now_ts,
            event_id=event_id,
        )

        # 1c) Link people to vehicles - adds linkage evidence to vision.evidence
        if camera_id is not None:
            _link_people_to_vehicles(
                conn,
                vision=vision,
                camera_id=camera_id,
                now_ts=now_ts,
                event_id=event_id,
                first_appearance_window_s=3,  # 3 second window for "just arrived"
            )
        
        # 1d) Add visitor intent history - adds cross-camera intent persistence
        _add_visitor_intent_history(
            conn,
            vision=vision,
            now_ts=now_ts,
            intent_persistence_window_s=retention.intent_persistence_window_s,
        )

    # PHASE 2: Classify intent with ENRICHED evidence
    # Now the classifier sees: trusted plates, scene tracking, person-vehicle links, visitor history
    
    # 2a) Add scene context evidence (what other intents are currently active?)
    if scene_tracker and camera_id is not None:
        try:
            from packages.scene.scene_context import get_active_scene_intents
            active_intents = get_active_scene_intents(conn, camera_id, now_ts, grace_period_s=6)
            
            if active_intents:
                from packages.common.types import Evidence
                # Add evidence about concurrent intents
                for active in active_intents:
                    vision.evidence.append(
                        Evidence(
                            source="scene",
                            key="concurrent_intent",
                            value=active["intent"],
                            confidence=1.0,
                            metadata={
                                "track_key": active["track_key"],
                                "urgency": active["urgency"],
                                "duration_seconds": now_ts - active["first_seen_ts"],
                            }
                        )
                    )
                print(f"[SCENE_CONTEXT] Found {len(active_intents)} concurrent intents: {[a['intent'] for a in active_intents]}")
        except Exception as e:
            print(f"[SCENE_CONTEXT] Warning: Failed to query active scene intents: {e}")
    
    classified = classify(
        text=text, 
        vision=vision, 
        db_path=db_path,
        plate_service=plate_service,
    )
    print(f"[CLASSIFY] Intent={classified.intent}, Conf={classified.conf:.2f}, Urgency={classified.urgency}")

    # Extract actor information
    actor = _choose_actor_visitor_id(vision)
    visitor_id, person_object_id, similarity, kind = None, None, None, None
    if actor:
        visitor_id, person_object_id, similarity, kind = actor

    # PHASE 3: Persist results to database
    with sqlite3.connect(db_path) as conn:
        # 3a) Create visitor event with classified intent
        create_visitor_event(
            conn,
            event_id=event_id,
            visitor_id=visitor_id,
            detected_ts_iso=_iso_now(now_ts),
            intent=classified.intent,
            intent_conf=classified.conf,
            camera_id=camera_id,
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

        # 3b) Save visitor snapshot if applicable
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

        # 3c) Lock intent if confidence is high enough
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

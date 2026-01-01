# packages/perception/scene_associations.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Iterable
import json
import math
import sqlite3
import time

# If you want evidence output, import lazily to avoid dependency loops.
def _make_evidence(source: str, feature: str, value: str, conf: float, object_id: Optional[int]):
    try:
        from packages.common.types import Evidence  # type: ignore
        return Evidence(source=source, feature=feature, value=value, conf=float(conf), object_id=object_id)
    except Exception:
        return None


@dataclass(frozen=True)
class VisitEntityLink:
    relation: str
    confidence: float

    subject_type: str
    subject_object_id: int
    subject_key: Optional[str] = None
    subject_meta: Optional[dict] = None

    object_type: str = ""
    object_object_id: int = -1
    object_key: Optional[str] = None
    object_meta: Optional[dict] = None

    notes: Optional[str] = None


# -----------------------------
# Schema
# -----------------------------

def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS visit_entity_links (
          link_id            INTEGER PRIMARY KEY AUTOINCREMENT,
          visit_id            TEXT    NOT NULL,
          camera_id           INTEGER,
          relation            TEXT    NOT NULL,
          confidence          REAL    NOT NULL DEFAULT 0.0,
          subject_type        TEXT    NOT NULL,
          subject_object_id   INTEGER NOT NULL,
          subject_key         TEXT,
          subject_meta_json   TEXT,
          object_type         TEXT    NOT NULL,
          object_object_id    INTEGER NOT NULL,
          object_key          TEXT,
          object_meta_json    TEXT,
          created_ts          INTEGER NOT NULL,
          updated_ts          INTEGER NOT NULL,
          notes               TEXT,
          UNIQUE (visit_id, relation, subject_type, subject_object_id, object_type, object_object_id)
        );
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_visit_entity_links_visit ON visit_entity_links(visit_id);")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_visit_entity_links_visit_relation ON visit_entity_links(visit_id, relation);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_visit_entity_links_camera_updated ON visit_entity_links(camera_id, updated_ts DESC);"
    )
    conn.commit()


# -----------------------------
# Geometry helpers
# -----------------------------

def _center(box: tuple[int, int, int, int]) -> tuple[float, float]:
    x1, y1, x2, y2 = box
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

def _wh(box: tuple[int, int, int, int]) -> tuple[float, float]:
    x1, y1, x2, y2 = box
    return (max(1.0, float(x2 - x1)), max(1.0, float(y2 - y1)))

def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])

def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))

def _exp_falloff(x: float, k: float = 1.0) -> float:
    # x=0 -> 1, x=1 -> ~0.368 when k=1
    return math.exp(-k * x)


# -----------------------------
# Association logic
# -----------------------------

def compute_visit_links_for_snapshot(
    *,
    objects: list,  # list[SceneObject], but keep loose to avoid import cycles
    relation: str = "arrived_with_vehicle",
    max_norm_dist: float = 1.20,
    falloff_k: float = 1.25,
    min_confidence: float = 0.35,
    conn: Optional[sqlite3.Connection] = None,
    camera_id: Optional[int] = None,
    now_ts: Optional[int] = None,
    first_appearance_window_s: int = 3,
) -> list[VisitEntityLink]:
    """
    Heuristic:
      - For each person, find nearest vehicle by bbox-center distance.
      - Normalize distance by vehicle max(width, height).
      - Convert to confidence via exponential falloff and mix in detector confidences.
      - ONLY link if person JUST appeared (within first_appearance_window_s).

    Args:
        objects: List of SceneObject from vision
        relation: Relationship type (e.g., "arrived_with_vehicle")
        max_norm_dist: Maximum normalized distance to consider
        falloff_k: Exponential falloff rate
        min_confidence: Minimum confidence threshold
        conn: Database connection (for checking first_seen_ts)
        camera_id: Camera ID (for track lookup)
        now_ts: Current timestamp
        first_appearance_window_s: Only link if person appeared within this window (default 3s)

    Notes:
      - This is intentionally visit-scoped.
      - Works even when plate OCR fails.
      - Requires scene_tracker to have run first to populate scene_tracks.
      - Only links people who JUST entered the scene (prevents linking passersby).
    """
    persons = [o for o in objects if (getattr(o, "label", "") or "").lower() == "person" and getattr(o, "box", None)]
    vehicles = [o for o in objects if (getattr(o, "label", "") or "").lower() == "vehicle" and getattr(o, "box", None)]

    if not persons or not vehicles:
        return []

    # Build lookup of person first_seen_ts from scene_tracks
    person_first_seen = {}
    if conn and camera_id is not None:
        try:
            # Get visitor_id for each person (if available)
            visitor_ids = {}
            for p in persons:
                visitor_id = getattr(p, "props", {}).get("visitor_id")
                if visitor_id:
                    visitor_ids[int(p.object_id)] = visitor_id
            
            # Query scene_tracks for person tracks
            rows = conn.execute("""
                SELECT track_key, first_seen_ts
                FROM scene_tracks
                WHERE camera_id = ? AND track_type = 'person' AND active = 1
            """, (camera_id,)).fetchall()
            
            # Map track_key (visitor_id or temp UUID) to first_seen_ts
            track_first_seen = {key: ts for key, ts in rows}
            
            # Map object_id to first_seen_ts
            for p in persons:
                p_id = int(p.object_id)
                visitor_id = visitor_ids.get(p_id)
                
                if visitor_id and visitor_id in track_first_seen:
                    person_first_seen[p_id] = track_first_seen[visitor_id]
                else:
                    # Try to find by temp key (would need object_id mapping, skip for now)
                    # Default: assume new if not found
                    pass
        except Exception as e:
            # If track lookup fails, proceed without first-appearance filtering
            print(f"[LINKAGE] Warning: Could not check first_seen_ts: {e}")

    now = int(now_ts or time.time())
    links: list[VisitEntityLink] = []

    for p in persons:
        p_id = int(p.object_id)
        p_box = tuple(int(v) for v in p.box)
        pc = _center(p_box)

        # Check if person JUST appeared (within window)
        if person_first_seen:
            first_seen = person_first_seen.get(p_id)
            if first_seen is not None:
                age_s = now - first_seen
                if age_s > first_appearance_window_s:
                    # Person has been around too long, don't link
                    # (prevents linking passersby to parked vehicles)
                    continue
            # If first_seen not found, assume new (allow linking)

        best = None
        best_norm = 1e9
        best_vehicle = None

        for v in vehicles:
            v_id = int(v.object_id)
            v_box = tuple(int(x) for x in v.box)
            vc = _center(v_box)
            vw, vh = _wh(v_box)
            scale = max(vw, vh)

            d = _dist(pc, vc)
            norm = d / scale  # normalized distance
            if norm < best_norm:
                best_norm = norm
                best_vehicle = v
                best = (v_id, norm, d)

        if best_vehicle is None or best is None:
            continue

        v_id, norm, raw_d = best

        # Gate: too far? skip
        if norm > float(max_norm_dist):
            continue

        # Base proximity confidence
        prox = _exp_falloff(norm, k=float(falloff_k))

        # Mix in detector confidences if present
        p_det = float(getattr(p, "props", {}).get("conf", 0.7) or 0.7)
        v_det = float(getattr(best_vehicle, "props", {}).get("conf", 0.7) or 0.7)

        conf = prox * math.sqrt(_clamp01(p_det) * _clamp01(v_det))

        if conf < float(min_confidence):
            continue

        # Optional stable keys if you have them:
        subject_key = None
        try:
            subject_key = getattr(p, "props", {}).get("visitor_id")
        except Exception:
            pass

        object_key = None
        # If you later store plate_hmac on the vehicle, you can fill this in.
        # (Right now your OCR stores plate_text evidence; plate_service stores plate_hmac in DB.)
        try:
            object_key = getattr(best_vehicle, "props", {}).get("plate_hmac")
        except Exception:
            pass

        links.append(
            VisitEntityLink(
                relation=relation,
                confidence=float(_clamp01(conf)),
                subject_type="person",
                subject_object_id=p_id,
                subject_key=str(subject_key) if subject_key else None,
                subject_meta={
                    "person_conf": p_det,
                },
                object_type="vehicle",
                object_object_id=int(v_id),
                object_key=str(object_key) if object_key else None,
                object_meta={
                    "vehicle_conf": v_det,
                    "norm_dist": float(norm),
                    "px_dist": float(raw_d),
                },
                notes="nearest_vehicle_by_center_distance",
            )
        )

    return links


# -----------------------------
# Persistence (upsert)
# -----------------------------

def upsert_visit_links(
    conn: sqlite3.Connection,
    *,
    visit_id: str,
    camera_id: Optional[int],
    now_ts: Optional[int] = None,
    links: Iterable[VisitEntityLink],
) -> int:
    """
    Upsert links for a given visit_id.
    Returns number of rows written (best effort).
    """
    ts = int(now_ts or time.time())
    count = 0

    for link in links:
        subj_meta = json.dumps(link.subject_meta or {}, separators=(",", ":"))
        obj_meta = json.dumps(link.object_meta or {}, separators=(",", ":"))

        conn.execute(
            """
            INSERT INTO visit_entity_links (
              visit_id, camera_id,
              relation, confidence,
              subject_type, subject_object_id, subject_key, subject_meta_json,
              object_type, object_object_id, object_key, object_meta_json,
              created_ts, updated_ts,
              notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(visit_id, relation, subject_type, subject_object_id, object_type, object_object_id)
            DO UPDATE SET
              camera_id = excluded.camera_id,
              confidence = excluded.confidence,
              subject_key = COALESCE(excluded.subject_key, visit_entity_links.subject_key),
              object_key  = COALESCE(excluded.object_key,  visit_entity_links.object_key),
              subject_meta_json = excluded.subject_meta_json,
              object_meta_json  = excluded.object_meta_json,
              updated_ts = excluded.updated_ts,
              notes = excluded.notes;
            """,
            (
                visit_id,
                int(camera_id) if camera_id is not None else None,
                link.relation,
                float(link.confidence),
                link.subject_type,
                int(link.subject_object_id),
                link.subject_key,
                subj_meta,
                link.object_type,
                int(link.object_object_id),
                link.object_key,
                obj_meta,
                ts,
                ts,
                link.notes,
            ),
        )
        count += 1

    conn.commit()
    return count


# -----------------------------
# Evidence output (optional)
# -----------------------------

def links_to_evidence(links: Iterable[VisitEntityLink]) -> list:
    """
    Emit object-level evidence on the subject (usually the person) so intent.classify can use it.
    """
    out = []
    for l in links:
        # For classifier convenience: put the vehicle object_id in the value.
        ev = _make_evidence(
            source="scene",
            feature=f"link.{l.relation}",
            value=f"{l.object_type}:{l.object_object_id}",
            conf=float(l.confidence),
            object_id=int(l.subject_object_id),
        )
        if ev is not None:
            out.append(ev)

        # Also emit confidence + debugging signals if you want
        ev2 = _make_evidence(
            source="scene",
            feature=f"link_conf.{l.relation}",
            value=f"{l.confidence:.3f}",
            conf=1.0,
            object_id=int(l.subject_object_id),
        )
        if ev2 is not None:
            out.append(ev2)

    return out

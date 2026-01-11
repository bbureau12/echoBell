# packages/perception/scene_associations.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Iterable
import json
import math
import sqlite3
import time

from packages.common.config_models import LinkageSettings

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

def _bbox_area(box: tuple[int, int, int, int]) -> float:
    x1, y1, x2, y2 = box
    return max(0.0, float(x2 - x1) * float(y2 - y1))

def _intersection_area(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    return max(0.0, float(ix2 - ix1) * float(iy2 - iy1))

def _json_to_box(s: str | None) -> tuple[int, int, int, int] | None:
    """Convert JSON string to box tuple."""
    if not s:
        return None
    try:
        o = json.loads(s)
        return (int(o["x1"]), int(o["y1"]), int(o["x2"]), int(o["y2"]))
    except Exception:
        return None

def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])

def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))

def _exp_falloff(x: float, k: float = 1.0) -> float:
    # x=0 -> 1, x=1 -> ~0.368 when k=1
    return math.exp(-k * x)


def _size_ratio_check(
    person_box: tuple[int, int, int, int],
    vehicle_box: tuple[int, int, int, int],
    vehicle_type: Optional[str] = None,
) -> bool:
    """
    Check if person and vehicle sizes are proportionally reasonable.
    
    Uses vehicle_type (raw YOLO class) to apply appropriate thresholds:
    - Bicycles/motorcycles: Person can be larger (0.8x to 2.5x vehicle size)
    - Cars/trucks/buses: Person should be smaller (0.15x to 0.85x vehicle size)
    
    Args:
        person_box: Person bounding box (x1, y1, x2, y2)
        vehicle_box: Vehicle bounding box (x1, y1, x2, y2)
        vehicle_type: Raw YOLO class ("bicycle", "car", "truck", etc.)
    
    Returns:
        True if size ratio is reasonable for linkage, False otherwise
    """
    pw, ph = _wh(person_box)
    vw, vh = _wh(vehicle_box)
    
    # Use diagonal for scale-invariant comparison
    p_diag = math.hypot(pw, ph)
    v_diag = math.hypot(vw, vh)
    
    if v_diag < 5:  # Suspiciously small vehicle
        return False
    
    ratio = p_diag / v_diag
    
    # Small vehicles (bikes, motorcycles, scooters)
    # Person is often same size or larger
    if vehicle_type in ("bicycle", "motorbike", "motorcycle"):
        # Person can be 0.8x to 2.5x vehicle size
        # Filters out: tiny head clip (< 0.8x), toy bike (> 2.5x)
        return 0.8 <= ratio <= 2.5
    
    # Large vehicles (cars, trucks, buses)
    # Person should be clearly smaller
    else:
        # Person should be 15% to 85% of vehicle size
        # Filters out: tiny head clip (< 15%), person same size as car (> 85%)
        return 0.15 <= ratio <= 0.85



# -----------------------------
# Association logic
# -----------------------------

def compute_visit_links_for_snapshot(
    *,
    objects: list,  # list[SceneObject], but keep loose to avoid import cycles
    relation: str = "arrived_with_vehicle",
    conn: Optional[sqlite3.Connection] = None,
    camera_id: Optional[int] = None,
    now_ts: Optional[int] = None,
    config: Optional[LinkageSettings] = None,
    # Deprecated parameters (kept for backwards compatibility, ignored if config provided)
    max_norm_dist: Optional[float] = None,
    falloff_k: Optional[float] = None,
    min_confidence: Optional[float] = None,
    first_appearance_window_s: Optional[int] = None,
    max_person_age_s: Optional[int] = None,
) -> list[VisitEntityLink]:
    """
    Heuristic: Link people to nearby vehicles if the person JUST appeared.
    
    Args:
        objects: List of detected objects (people, vehicles, packages)
        relation: Type of relationship (default: "arrived_with_vehicle")
        conn: Database connection for querying scene tracks
        camera_id: Camera ID for scene track lookup
        now_ts: Current timestamp
        config: LinkageSettings configuration object (recommended)
        
        # Deprecated (use config instead):
        max_norm_dist: Maximum normalized distance
        falloff_k: Distance falloff parameter
        min_confidence: Minimum confidence threshold
        first_appearance_window_s: First appearance window in seconds
        max_person_age_s: Maximum person age in seconds
    
    Returns:
        List of VisitEntityLink objects
    """
    # Use config if provided, otherwise fall back to individual params or defaults
    if config is None:
        config = LinkageSettings()
    
    # Override config with individual params if explicitly provided (backwards compatibility)
    _max_norm_dist = max_norm_dist if max_norm_dist is not None else config.person_vehicle_max_norm_distance
    _falloff_k = falloff_k if falloff_k is not None else config.person_vehicle_falloff_k
    _min_confidence = min_confidence if min_confidence is not None else config.person_vehicle_min_confidence
    _first_appearance_window_s = first_appearance_window_s if first_appearance_window_s is not None else config.person_vehicle_first_appearance_window_s
    _max_person_age_s = max_person_age_s if max_person_age_s is not None else config.person_vehicle_max_person_age_s

    persons = [o for o in objects if (getattr(o, "label", "") or "").lower() == "person" and getattr(o, "box", None)]
    vehicles = [o for o in objects if (getattr(o, "label", "") or "").lower() == "vehicle" and getattr(o, "box", None)]

    if not persons or not vehicles:
        return []

    # Build lookup of person and vehicle first_seen_ts from scene_tracks
    person_first_seen = {}
    vehicle_first_seen = {}
    
    if conn and camera_id is not None:
        try:
            # Query scene_tracks for all active tracks (person and vehicle)
            rows = conn.execute("""
                SELECT track_key, first_seen_ts, track_type
                FROM scene_tracks
                WHERE camera_id = ? AND active = 1 AND track_type IN ('person', 'vehicle')
            """, (camera_id,)).fetchall()
            
            # Build lookup: track_key -> first_seen_ts
            track_first_seen = {key: ts for key, ts, _ in rows}
            
            # Map object_id to first_seen_ts using scene_track_key
            for p in persons:
                p_id = int(p.object_id)
                # Try scene_track_key first (set by scene_tracker), fallback to visitor_id
                track_key = getattr(p, "props", {}).get("scene_track_key") or getattr(p, "props", {}).get("visitor_id")
                
                if track_key and track_key in track_first_seen:
                    person_first_seen[p_id] = track_first_seen[track_key]
            
            # Map vehicle object_id to first_seen_ts using scene_track_key or plate_hmac
            for v in vehicles:
                v_id = int(v.object_id)
                # Try scene_track_key first (set by scene_tracker), fallback to plate_hmac
                track_key = getattr(v, "props", {}).get("scene_track_key") or getattr(v, "props", {}).get("plate_hmac")
                
                if track_key and track_key in track_first_seen:
                    vehicle_first_seen[v_id] = track_first_seen[track_key]
            
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
                
                # Don't link if person has been around too long (over max age)
                if age_s > _max_person_age_s:
                    # Person has been in scene for too long (e.g., 1+ hour)
                    # They likely got out of a vehicle or are a long-time visitor
                    continue
                
                # Don't link if person didn't JUST appear (outside first-appearance window)
                if age_s > _first_appearance_window_s:
                    # Person has been around too long for initial arrival linking
                    # (prevents linking passersby to parked vehicles)
                    continue
            # If first_seen not found, assume new (allow linking)

        best = None
        best_norm = 1e9
        best_vehicle = None

        for v in vehicles:
            v_id = int(v.object_id)
            
            # Check if vehicle has been on scene too long
            if vehicle_first_seen:
                v_first_seen = vehicle_first_seen.get(v_id)
                if v_first_seen is not None:
                    vehicle_age_s = now - v_first_seen
                    if vehicle_age_s > _max_person_age_s:
                        # Vehicle has been parked for over an hour
                        # Don't link people to it (they're not arriving)
                        continue
            
            v_box = tuple(int(x) for x in v.box)
            
            # Get vehicle type for size ratio check
            vehicle_type = getattr(v, "props", {}).get("raw_class")
            
            # Check size ratio (filters out head clips, misdetections)
            if not _size_ratio_check(p_box, v_box, vehicle_type):
                continue
            
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
        if norm > float(_max_norm_dist):
            continue

        # Base proximity confidence
        prox = _exp_falloff(norm, k=float(_falloff_k))

        # Mix in detector confidences if present
        p_det = float(getattr(p, "props", {}).get("conf", 0.7) or 0.7)
        v_det = float(getattr(best_vehicle, "props", {}).get("conf", 0.7) or 0.7)

        conf = prox * math.sqrt(_clamp01(p_det) * _clamp01(v_det))

        if conf < float(_min_confidence):
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


def compute_package_to_person_links(
    *,
    objects: list,  # list[SceneObject]
    conn: sqlite3.Connection,
    camera_id: int,
    now_ts: int,
    relation: str = "carrying_package",
    config: Optional[LinkageSettings] = None,
    # Deprecated parameters - use config instead
    first_appearance_window_s: Optional[int] = None,
    min_confidence: Optional[float] = None,
) -> list[VisitEntityLink]:
    """
    Link packages to people if the package FIRST APPEARS inside a person's bounding box.
    
    Constraints:
    - Package must be NEW (first_seen_ts within first_appearance_window_s)
    - Package bbox must be INSIDE person bbox (fully contained)
    - Package must be SMALLER than person (prevents false positives)
    
    Use cases:
    - Delivery person arriving WITH package (delivery_person intent)
    - Porch pirate leaving WITHOUT package they arrived with
    - Neighbor bringing package to your door
    
    Args:
        objects: List of SceneObject from vision
        conn: Database connection (for checking first_seen_ts from scene_tracks)
        camera_id: Camera ID
        now_ts: Current timestamp
        relation: Relationship type (default "carrying_package")
        config: LinkageSettings with all threshold configuration
        first_appearance_window_s: DEPRECATED - use config.package_person_first_appearance_window_s
        min_confidence: DEPRECATED - use config.package_person_min_confidence
    
    Returns:
        List of VisitEntityLink objects linking packages to people
    """
    if config is None:
        config = LinkageSettings()
    
    # Support deprecated parameters
    _first_appearance_window_s = (
        first_appearance_window_s 
        if first_appearance_window_s is not None 
        else config.package_person_first_appearance_window_s
    )
    _min_confidence = (
        min_confidence 
        if min_confidence is not None 
        else config.package_person_min_confidence
    )
    
    persons = [o for o in objects if (getattr(o, "label", "") or "").lower() == "person" and getattr(o, "box", None)]
    packages = [o for o in objects if (getattr(o, "label", "") or "").lower() == "package" and getattr(o, "box", None)]
    
    if not persons or not packages:
        return []
    
    # Get package first_seen_ts from scene_tracks
    package_first_seen = {}
    for pkg in packages:
        pkg_id = getattr(pkg, "object_id", None)
        if pkg_id is None:
            continue
        
        # Query scene_tracks for this package
        row = conn.execute(
            """
            SELECT first_seen_ts, track_key
            FROM scene_tracks
            WHERE camera_id=? AND track_type='package' AND active=1
            ORDER BY id DESC
            LIMIT 1
            """,
            (camera_id,)
        ).fetchone()
        
        if row:
            package_first_seen[int(pkg_id)] = int(row[0])
    
    links: list[VisitEntityLink] = []
    cutoff_ts = now_ts - _first_appearance_window_s
    
    for pkg in packages:
        pkg_id = getattr(pkg, "object_id", None)
        if pkg_id is None:
            continue
        
        # Only link packages that JUST appeared
        first_ts = package_first_seen.get(int(pkg_id))
        if first_ts is None or first_ts < cutoff_ts:
            continue
        
        pkg_box = getattr(pkg, "box")
        pkg_x1, pkg_y1, pkg_x2, pkg_y2 = pkg_box
        pkg_area = _bbox_area(pkg_box)
        
        # Find person whose bbox CONTAINS this package
        best_person = None
        best_containment = 0.0
        
        for person in persons:
            person_box = getattr(person, "box")
            person_x1, person_y1, person_x2, person_y2 = person_box
            person_area = _bbox_area(person_box)
            
            # Package must be SMALLER than person
            if pkg_area >= person_area:
                continue
            
            # Check if package is INSIDE person bbox
            is_inside = (
                pkg_x1 >= person_x1 and
                pkg_y1 >= person_y1 and
                pkg_x2 <= person_x2 and
                pkg_y2 <= person_y2
            )
            
            if not is_inside:
                continue
            
            # Calculate containment score (how well package fits inside person)
            # Higher score = package is more centered / better contained
            containment = _intersection_area(pkg_box, person_box) / pkg_area if pkg_area > 0 else 0.0
            
            if containment > best_containment:
                best_containment = containment
                best_person = person
        
        if best_person is None or best_containment < _min_confidence:
            continue
        
        # Get object IDs and detector confidences
        person_id = getattr(best_person, "object_id", None)
        if person_id is None:
            continue
        
        person_det_conf = getattr(best_person, "conf", 0.9)
        pkg_det_conf = getattr(pkg, "conf", 0.9)
        
        # Final confidence: mix containment with detector confidences
        final_conf = best_containment * person_det_conf * pkg_det_conf
        
        if final_conf < min_confidence:
            continue
        
        # Get visitor_id if available
        visitor_id = None
        try:
            visitor_id = getattr(best_person, "props", {}).get("visitor_id")
        except Exception:
            pass
        
        links.append(
            VisitEntityLink(
                relation=relation,
                confidence=float(_clamp01(final_conf)),
                subject_type="person",
                subject_object_id=int(person_id),
                subject_key=str(visitor_id) if visitor_id else None,
                subject_meta={
                    "person_conf": float(person_det_conf),
                },
                object_type="package",
                object_object_id=int(pkg_id),
                object_key=None,  # Packages don't have stable keys
                object_meta={
                    "package_conf": float(pkg_det_conf),
                    "containment": float(best_containment),
                    "pkg_area": float(pkg_area),
                    "person_area": float(_bbox_area(best_person.box)),
                },
                notes="package_first_appeared_inside_person_bbox",
            )
        )
    
    return links


def detect_package_pickup(
    *,
    objects: list,  # list[SceneObject]
    conn: sqlite3.Connection,
    camera_id: int,
    now_ts: int,
    relation: str = "picked_up_package",
    config: Optional[LinkageSettings] = None,
    # Deprecated parameters - use config instead
    min_dwell_time_s: Optional[int] = None,
    min_confidence: Optional[float] = None,
) -> list[VisitEntityLink]:
    """
    Detect when someone picks up a package that was already on the ground.
    
    Detection logic:
    1. Package existed BEFORE person arrived (not carrying_package)
    2. Package is now INSIDE person's bbox
    3. Package has been inside person's bbox for >= min_dwell_time_s
    
    This differentiates:
    - Delivery person (arrives WITH package) vs Porch pirate (picks UP existing package)
    - Homeowner retrieving their delivery vs Thief stealing package
    
    Uses scene_tracks to determine:
    - Package age (first_seen_ts)
    - Person age (first_seen_ts)
    - How long package has been contained (via tags tracking)
    
    Args:
        objects: List of SceneObject from vision
        conn: Database connection
        camera_id: Camera ID
        now_ts: Current timestamp
        relation: Relationship type (default "picked_up_package")
        config: LinkageSettings with all threshold configuration
        min_dwell_time_s: DEPRECATED - use config.package_pickup_min_stationary_duration_s
        min_confidence: DEPRECATED - use config.package_pickup_min_confidence
    
    Returns:
        List of VisitEntityLink for pickup events
    """
    if config is None:
        config = LinkageSettings()
    
    # Support deprecated parameters
    _min_dwell_time_s = (
        min_dwell_time_s 
        if min_dwell_time_s is not None 
        else config.package_pickup_min_stationary_duration_s
    )
    _min_confidence = (
        min_confidence 
        if min_confidence is not None 
        else config.package_pickup_min_confidence
    )
    
    persons = [o for o in objects if (getattr(o, "label", "") or "").lower() == "person" and getattr(o, "box", None)]
    packages = [o for o in objects if (getattr(o, "label", "") or "").lower() == "package" and getattr(o, "box", None)]
    
    if not persons or not packages:
        return []
    
    # Get package and person first_seen_ts from scene_tracks
    package_info = {}  # pkg_id -> {first_seen_ts, track_id, track_key, tags}
    person_info = {}   # person_id -> {first_seen_ts, track_id, visitor_id}
    
    for pkg in packages:
        pkg_id = getattr(pkg, "object_id", None)
        if pkg_id is None:
            continue
        
        # Find this package's track (match by most recent for this camera)
        rows = conn.execute(
            """
            SELECT id, first_seen_ts, track_key, tags
            FROM scene_tracks
            WHERE camera_id=? AND track_type='package' AND active=1
            ORDER BY last_seen_ts DESC
            LIMIT 5
            """,
            (camera_id,)
        ).fetchall()
        
        # Simple heuristic: use the most recent package track
        # (In future, could match by IoU with pkg.box)
        if rows:
            package_info[int(pkg_id)] = {
                "first_seen_ts": int(rows[0][1]),
                "track_id": int(rows[0][0]),
                "track_key": str(rows[0][2]),
                "tags": str(rows[0][3]) if rows[0][3] else "",
            }
    
    for person in persons:
        person_id = getattr(person, "object_id", None)
        if person_id is None:
            continue
        
        # Get visitor_id if available
        visitor_id = None
        try:
            visitor_id = getattr(person, "props", {}).get("visitor_id")
        except Exception:
            pass
        
        if not visitor_id:
            continue
        
        # Find this person's track
        row = conn.execute(
            """
            SELECT id, first_seen_ts
            FROM scene_tracks
            WHERE camera_id=? AND track_type='person' AND track_key=? AND active=1
            ORDER BY last_seen_ts DESC
            LIMIT 1
            """,
            (camera_id, visitor_id)
        ).fetchone()
        
        if row:
            person_info[int(person_id)] = {
                "first_seen_ts": int(row[1]),
                "track_id": int(row[0]),
                "visitor_id": str(visitor_id),
            }
    
    links: list[VisitEntityLink] = []
    
    for pkg in packages:
        pkg_id = getattr(pkg, "object_id", None)
        if pkg_id is None or int(pkg_id) not in package_info:
            continue
        
        pkg_box = getattr(pkg, "box")
        pkg_info = package_info[int(pkg_id)]
        pkg_first_seen = pkg_info["first_seen_ts"]
        pkg_area = _bbox_area(pkg_box)
        
        # Find person whose bbox CONTAINS this package
        best_person = None
        best_containment = 0.0
        best_person_info = None
        
        for person in persons:
            person_id = getattr(person, "object_id", None)
            if person_id is None or int(person_id) not in person_info:
                continue
            
            person_box = getattr(person, "box")
            person_area = _bbox_area(person_box)
            person_pinfo = person_info[int(person_id)]
            person_first_seen = person_pinfo["first_seen_ts"]
            
            # KEY CHECK: Package must have existed BEFORE person arrived
            # (If person arrived first, they're delivering, not picking up)
            if pkg_first_seen >= person_first_seen:
                continue
            
            # Package must be SMALLER than person
            if pkg_area >= person_area:
                continue
            
            # Check if package is INSIDE person bbox
            pkg_x1, pkg_y1, pkg_x2, pkg_y2 = pkg_box
            person_x1, person_y1, person_x2, person_y2 = person_box
            
            is_inside = (
                pkg_x1 >= person_x1 and
                pkg_y1 >= person_y1 and
                pkg_x2 <= person_x2 and
                pkg_y2 <= person_y2
            )
            
            if not is_inside:
                continue
            
            # Calculate containment score
            containment = _intersection_area(pkg_box, person_box) / pkg_area if pkg_area > 0 else 0.0
            
            if containment > best_containment:
                best_containment = containment
                best_person = person
                best_person_info = person_pinfo
        
        if best_person is None or best_containment < _min_confidence:
            continue
        
        # Check dwell time using tags
        # Tags format: "contained_by:<visitor_id>_since:<timestamp>"
        tags = pkg_info["tags"]
        contained_duration = 0
        
        if tags and "contained_by:" in tags:
            # Parse tags to find when containment started
            try:
                parts = tags.split()
                for part in parts:
                    if part.startswith("contained_since:"):
                        contained_since = int(part.split(":")[1])
                        contained_duration = now_ts - contained_since
                        break
            except Exception:
                pass
        
        # If not tagged yet, or if person changed, update tags and skip (wait for next frame)
        expected_tag = f"contained_by:{best_person_info['visitor_id']} contained_since:{now_ts}"
        if not tags or "contained_by:" not in tags or contained_duration == 0:
            # First time seeing this package contained - tag it and wait
            try:
                conn.execute(
                    "UPDATE scene_tracks SET tags=? WHERE id=?",
                    (f"contained_by:{best_person_info['visitor_id']} contained_since:{now_ts}", pkg_info["track_id"])
                )
                conn.commit()
            except Exception as e:
                print(f"[PICKUP] Warning: Failed to tag package: {e}")
            continue
        
        # Check if dwell time threshold met
        if contained_duration < _min_dwell_time_s:
            continue  # Not long enough yet
        
        # PICKUP DETECTED!
        person_id = getattr(best_person, "object_id", None)
        person_det_conf = getattr(best_person, "conf", 0.9)
        pkg_det_conf = getattr(pkg, "conf", 0.9)
        
        # Confidence: containment * detector confs * time factor
        time_factor = min(1.0, contained_duration / (_min_dwell_time_s * 2))  # Maxes at 2x min_dwell
        final_conf = best_containment * person_det_conf * pkg_det_conf * time_factor
        
        if final_conf < _min_confidence:
            continue
        
        links.append(
            VisitEntityLink(
                relation=relation,
                confidence=float(_clamp01(final_conf)),
                subject_type="person",
                subject_object_id=int(person_id),
                subject_key=best_person_info["visitor_id"],
                subject_meta={
                    "person_conf": float(person_det_conf),
                    "person_age_s": now_ts - best_person_info["first_seen_ts"],
                },
                object_type="package",
                object_object_id=int(pkg_id),
                object_key=None,
                object_meta={
                    "package_conf": float(pkg_det_conf),
                    "package_age_s": now_ts - pkg_first_seen,
                    "containment": float(best_containment),
                    "dwell_time_s": contained_duration,
                },
                notes=f"package_picked_up_after_{contained_duration}s_dwell",
            )
        )
    
    return links


def detect_package_dropoff(
    *,
    objects: list,  # list[SceneObject]
    conn: sqlite3.Connection,
    camera_id: int,
    now_ts: int,
    relation: str = "dropped_off_package",
    min_separation_time_s: int = 2,
    max_separation_distance: float = 2.0,  # meters (heuristic: ~2 box widths)
    min_confidence: float = 0.60,
) -> list[VisitEntityLink]:
    """
    Detect when someone drops off a package (delivery scenario).
    
    Detection logic:
    1. Package has "carrying_package" link (person arrived WITH it)
    2. Package is now OUTSIDE person's bbox (separated)
    3. Package has been outside person's bbox for >= min_separation_time_s
    4. Package is stationary (not moving with person)
    
    This detects:
    - Delivery person leaving package at door
    - Neighbor dropping off package
    - Mail carrier leaving parcel
    
    Uses scene_tracks tags to track separation state:
    - "separated_from:<visitor_id>_since:<timestamp>"
    
    Args:
        objects: List of SceneObject from vision
        conn: Database connection
        camera_id: Camera ID
        now_ts: Current timestamp
        relation: Relationship type (default "dropped_off_package")
        min_separation_time_s: Package must be separated for this long
        max_separation_distance: Max distance (in normalized units) to still consider "near"
        min_confidence: Minimum confidence threshold
    
    Returns:
        List of VisitEntityLink for drop-off events
    """
    persons = [o for o in objects if (getattr(o, "label", "") or "").lower() == "person" and getattr(o, "box", None)]
    packages = [o for o in objects if (getattr(o, "label", "") or "").lower() == "package" and getattr(o, "box", None)]
    
    if not persons or not packages:
        return []
    
    # Get packages that were carried (have carrying_package links)
    # We need to check visit_entity_links to see which packages were being carried
    carried_packages = {}  # pkg_track_key -> {person_visitor_id, link_created_ts}
    
    try:
        # Query recent carrying_package links for this camera
        rows = conn.execute(
            """
            SELECT object_type, object_object_id, subject_key, created_ts, object_meta_json
            FROM visit_entity_links
            WHERE camera_id=? 
              AND relation='carrying_package'
              AND created_ts >= ?
            ORDER BY created_ts DESC
            LIMIT 50
            """,
            (camera_id, now_ts - 300)  # Last 5 minutes
        ).fetchall()
        
        for row in rows:
            obj_type, obj_id, subj_key, created_ts, obj_meta = row
            if obj_type == "package" and subj_key:
                # Note: We store by object_id, but packages have temp track_keys
                # We'll match by proximity later
                carried_packages[int(obj_id)] = {
                    "person_visitor_id": str(subj_key),
                    "link_created_ts": int(created_ts),
                }
    except Exception as e:
        print(f"[DROPOFF] Warning: Failed to query carrying links: {e}")
        return []
    
    # Get package and person info from scene_tracks
    package_info = {}  # pkg_id -> {track_id, track_key, tags, first_seen_ts, last_box}
    person_info = {}   # person_id -> {visitor_id, track_id, first_seen_ts}
    
    for pkg in packages:
        pkg_id = getattr(pkg, "object_id", None)
        if pkg_id is None:
            continue
        
        rows = conn.execute(
            """
            SELECT id, track_key, tags, first_seen_ts, last_box_json
            FROM scene_tracks
            WHERE camera_id=? AND track_type='package' AND active=1
            ORDER BY last_seen_ts DESC
            LIMIT 5
            """,
            (camera_id,)
        ).fetchall()
        
        if rows:
            package_info[int(pkg_id)] = {
                "track_id": int(rows[0][0]),
                "track_key": str(rows[0][1]),
                "tags": str(rows[0][2]) if rows[0][2] else "",
                "first_seen_ts": int(rows[0][3]),
                "last_box": _json_to_box(rows[0][4]) if rows[0][4] else None,
            }
    
    for person in persons:
        person_id = getattr(person, "object_id", None)
        if person_id is None:
            continue
        
        visitor_id = None
        try:
            visitor_id = getattr(person, "props", {}).get("visitor_id")
        except Exception:
            pass
        
        if not visitor_id:
            continue
        
        row = conn.execute(
            """
            SELECT id, first_seen_ts
            FROM scene_tracks
            WHERE camera_id=? AND track_type='person' AND track_key=? AND active=1
            ORDER BY last_seen_ts DESC
            LIMIT 1
            """,
            (camera_id, visitor_id)
        ).fetchone()
        
        if row:
            person_info[int(person_id)] = {
                "visitor_id": str(visitor_id),
                "track_id": int(row[0]),
                "first_seen_ts": int(row[1]),
            }
    
    links: list[VisitEntityLink] = []
    
    for pkg in packages:
        pkg_id = getattr(pkg, "object_id", None)
        if pkg_id is None or int(pkg_id) not in package_info:
            continue
        
        # Check if this package was being carried
        if int(pkg_id) not in carried_packages:
            continue
        
        pkg_box = getattr(pkg, "box")
        pkg_info = package_info[int(pkg_id)]
        carry_info = carried_packages[int(pkg_id)]
        carrier_visitor_id = carry_info["person_visitor_id"]
        
        # Find the person who was carrying it
        carrier_person = None
        carrier_person_info = None
        
        for person in persons:
            person_id = getattr(person, "object_id", None)
            if person_id is None or int(person_id) not in person_info:
                continue
            
            pinfo = person_info[int(person_id)]
            if pinfo["visitor_id"] == carrier_visitor_id:
                carrier_person = person
                carrier_person_info = pinfo
                break
        
        if carrier_person is None:
            # Person who was carrying has left the scene - STRONG dropoff signal!
            # But we can't create a link without the person object_id
            # Instead, just log it
            print(f"[DROPOFF] Package {pkg_id} carrier left scene - package dropped off")
            continue
        
        # Person is still in scene - check if package separated
        person_box = getattr(carrier_person, "box")
        
        # Check if package is OUTSIDE person bbox
        pkg_x1, pkg_y1, pkg_x2, pkg_y2 = pkg_box
        person_x1, person_y1, person_x2, person_y2 = person_box
        
        is_inside = (
            pkg_x1 >= person_x1 and
            pkg_y1 >= person_y1 and
            pkg_x2 <= person_x2 and
            pkg_y2 <= person_y2
        )
        
        if is_inside:
            # Still carrying - clear any separation tags
            if "separated_from:" in pkg_info["tags"]:
                try:
                    conn.execute(
                        "UPDATE scene_tracks SET tags=? WHERE id=?",
                        ("", pkg_info["track_id"])
                    )
                    conn.commit()
                except Exception:
                    pass
            continue
        
        # Package is outside person bbox - check distance
        pkg_center = _center(pkg_box)
        person_center = _center(person_box)
        distance = _dist(pkg_center, person_center)
        
        # Normalize by person width
        person_width = person_box[2] - person_box[0]
        norm_distance = distance / max(1.0, person_width)
        
        # Check separation tags
        tags = pkg_info["tags"]
        separation_duration = 0
        
        if tags and "separated_from:" in tags:
            try:
                parts = tags.split()
                for part in parts:
                    if part.startswith("separated_since:"):
                        separated_since = int(part.split(":")[1])
                        separation_duration = now_ts - separated_since
                        break
            except Exception:
                pass
        
        # First time seeing separation - tag it and wait
        expected_tag = f"separated_from:{carrier_visitor_id} separated_since:{now_ts}"
        if separation_duration == 0:
            try:
                conn.execute(
                    "UPDATE scene_tracks SET tags=? WHERE id=?",
                    (expected_tag, pkg_info["track_id"])
                )
                conn.commit()
            except Exception as e:
                print(f"[DROPOFF] Warning: Failed to tag package separation: {e}")
            continue
        
        # Check if separation time threshold met
        if separation_duration < min_separation_time_s:
            continue  # Not long enough yet
        
        # DROP-OFF DETECTED!
        person_id = getattr(carrier_person, "object_id", None)
        person_det_conf = getattr(carrier_person, "conf", 0.9)
        pkg_det_conf = getattr(pkg, "conf", 0.9)
        
        # Confidence: distance factor * detector confs * time factor
        distance_factor = max(0.0, 1.0 - (norm_distance / max_separation_distance))
        time_factor = min(1.0, separation_duration / (min_separation_time_s * 2))
        final_conf = distance_factor * person_det_conf * pkg_det_conf * time_factor
        
        if final_conf < min_confidence:
            continue
        
        links.append(
            VisitEntityLink(
                relation=relation,
                confidence=float(_clamp01(final_conf)),
                subject_type="person",
                subject_object_id=int(person_id),
                subject_key=carrier_visitor_id,
                subject_meta={
                    "person_conf": float(person_det_conf),
                    "person_age_s": now_ts - carrier_person_info["first_seen_ts"],
                },
                object_type="package",
                object_object_id=int(pkg_id),
                object_key=None,
                object_meta={
                    "package_conf": float(pkg_det_conf),
                    "package_age_s": now_ts - pkg_info["first_seen_ts"],
                    "separation_time_s": separation_duration,
                    "norm_distance": float(norm_distance),
                },
                notes=f"package_dropped_after_{separation_duration}s_separation",
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

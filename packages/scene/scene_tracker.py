# packages/scene/scene_tracker.py
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple, List, Dict

# EchoBell types (adjust import paths if yours differ)
from packages.common.types import Evidence, VisionResult, SceneObject


Box = Tuple[int, int, int, int]


def _bbox_area(b: Box) -> float:
    x1, y1, x2, y2 = b
    return max(0, x2 - x1) * max(0, y2 - y1)


def _intersection_area(a: Box, b: Box) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    return max(0, ix2 - ix1) * max(0, iy2 - iy1)


def iou(a: Box, b: Box) -> float:
    inter = _intersection_area(a, b)
    if inter <= 0:
        return 0.0
    union = _bbox_area(a) + _bbox_area(b) - inter
    return (inter / union) if union > 0 else 0.0


@dataclass(frozen=True)
class Observation:
    track_type: str            # 'vehicle' | 'person' | 'package'
    box: Box
    raw_class: str | None = None
    color: str | None = None
    # Strong keys (optional)
    plate_hmac: str | None = None
    visitor_id: str | None = None


@dataclass(frozen=True)
class TrackRow:
    id: int
    camera_id: int
    track_type: str
    key_kind: str
    track_key: str
    first_seen_ts: int
    last_seen_ts: int
    active: int
    last_box: Box | None
    raw_class: str | None
    color: str | None
    tags: str | None = None


def _box_to_json(b: Box) -> str:
    x1, y1, x2, y2 = b
    return json.dumps({"x1": x1, "y1": y1, "x2": x2, "y2": y2}, separators=(",", ":"))


def _json_to_box(s: str | None) -> Box | None:
    if not s:
        return None
    try:
        o = json.loads(s)
        return (int(o["x1"]), int(o["y1"]), int(o["x2"]), int(o["y2"]))
    except Exception:
        return None


class SceneTracker:
    """
    DB-backed scene tracker.
    Tracks objects across frames and emits 'scene.*' Evidence entries.

    v1 strategy:
    - If plate_hmac / visitor_id exists, match on that first.
    - Otherwise match by IoU against active tracks.
    - Tracks are marked exited after grace_period_s without being seen.
    """

    def __init__(
        self,
        *,
        iou_match_threshold: float = 0.30,
        grace_period_s: int = 6,
    ):
        self.iou_match_threshold = float(iou_match_threshold)
        self.grace_period_s = int(grace_period_s)

    def ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS scene_tracks (
          id            INTEGER PRIMARY KEY AUTOINCREMENT,
          camera_id      INTEGER NOT NULL,
          track_type     TEXT NOT NULL,
          key_kind       TEXT NOT NULL,
          track_key      TEXT NOT NULL,
          first_seen_ts  INTEGER NOT NULL,
          last_seen_ts   INTEGER NOT NULL,
          active         INTEGER NOT NULL DEFAULT 1,
          last_box_json  TEXT,
          raw_class      TEXT,
          color          TEXT,
          last_event_id  TEXT,
          tags           TEXT,
          UNIQUE(camera_id, track_type, track_key)
        );
        """)
        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_scene_tracks_active
          ON scene_tracks(camera_id, track_type, active, last_seen_ts);
        """)
        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_scene_tracks_tags
          ON scene_tracks(tags);
        """)
        conn.commit()

    def _load_active_tracks(self, conn: sqlite3.Connection, *, camera_id: int, track_type: str) -> list[TrackRow]:
        rows = conn.execute(
            """
            SELECT id, camera_id, track_type, key_kind, track_key,
                   first_seen_ts, last_seen_ts, active, last_box_json, raw_class, color, tags
            FROM scene_tracks
            WHERE camera_id=? AND track_type=? AND active=1
            """,
            (camera_id, track_type),
        ).fetchall()

        out: list[TrackRow] = []
        for (tid, cam, ttype, kind, tkey, fst, lst, active, box_json, raw_class, color, tags) in rows:
            out.append(
                TrackRow(
                    id=int(tid),
                    camera_id=int(cam),
                    track_type=str(ttype),
                    key_kind=str(kind),
                    track_key=str(tkey),
                    first_seen_ts=int(fst),
                    last_seen_ts=int(lst),
                    active=int(active),
                    last_box=_json_to_box(box_json),
                    raw_class=raw_class,
                    color=color,
                    tags=tags,
                )
            )
        return out

    def _update_track_seen(
        self,
        conn: sqlite3.Connection,
        *,
        track_id: int,
        now_ts: int,
        box: Box,
        raw_class: str | None,
        color: str | None,
        last_event_id: str | None,
    ) -> None:
        conn.execute(
            """
            UPDATE scene_tracks
            SET last_seen_ts=?, last_box_json=?, raw_class=COALESCE(?, raw_class),
                color=COALESCE(?, color), last_event_id=COALESCE(?, last_event_id)
            WHERE id=?
            """,
            (now_ts, _box_to_json(box), raw_class, color, last_event_id, track_id),
        )

    def _insert_track(
        self,
        conn: sqlite3.Connection,
        *,
        camera_id: int,
        track_type: str,
        key_kind: str,
        track_key: str,
        now_ts: int,
        box: Box,
        raw_class: str | None,
        color: str | None,
        last_event_id: str | None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO scene_tracks
              (camera_id, track_type, key_kind, track_key, first_seen_ts, last_seen_ts,
               active, last_box_json, raw_class, color, last_event_id)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
            """,
            (camera_id, track_type, key_kind, track_key, now_ts, now_ts, _box_to_json(box), raw_class, color, last_event_id),
        )

    def _mark_exited(self, conn: sqlite3.Connection, *, track_id: int, now_ts: int) -> None:
        conn.execute(
            "UPDATE scene_tracks SET active=0, last_seen_ts=? WHERE id=?",
            (now_ts, track_id),
        )

    def _reactivate_track(
        self,
        conn: sqlite3.Connection,
        *,
        track_id: int,
        now_ts: int,
        box: Box,
        raw_class: str | None,
        color: str | None,
        last_event_id: str | None,
    ) -> None:
        """Reactivate an inactive track (person/vehicle returned)."""
        conn.execute(
            """
            UPDATE scene_tracks
            SET active=1, last_seen_ts=?, last_box_json=?, 
                raw_class=COALESCE(?, raw_class),
                color=COALESCE(?, color), 
                last_event_id=COALESCE(?, last_event_id)
            WHERE id=?
            """,
            (now_ts, _box_to_json(box), raw_class, color, last_event_id, track_id),
        )

    def _find_inactive_track(
        self,
        conn: sqlite3.Connection,
        *,
        camera_id: int,
        track_type: str,
        track_key: str,
    ) -> int | None:
        """Find an inactive track with the given key. Returns track_id or None."""
        row = conn.execute(
            """
            SELECT id FROM scene_tracks
            WHERE camera_id=? AND track_type=? AND track_key=? AND active=0
            ORDER BY last_seen_ts DESC
            LIMIT 1
            """,
            (camera_id, track_type, track_key),
        ).fetchone()
        return row[0] if row else None

    def update_tags(
        self,
        conn: sqlite3.Connection,
        *,
        track_id: int,
        tags: str | None,
    ) -> None:
        """
        Update tags for a specific track.
        
        Tags are space-separated keywords for future expansion, e.g.:
        - "suspicious loitering"
        - "expected delivery"
        - "priority vip"
        - "trusted neighbor"
        
        Args:
            conn: Database connection
            track_id: The track ID to update
            tags: Space-separated tag string, or None to clear tags
        """
        conn.execute(
            "UPDATE scene_tracks SET tags=? WHERE id=?",
            (tags, track_id),
        )

    def is_person_active_anywhere(
        self,
        conn: sqlite3.Connection,
        *,
        visitor_id: str,
        now_ts: int | None = None,
    ) -> bool:
        """
        Check if a person (by visitor_id) is currently active on ANY camera.
        
        This enables cross-camera person tracking - detecting when someone is
        present in the scene regardless of which camera sees them.
        
        Args:
            conn: Database connection
            visitor_id: The visitor_id to check
            now_ts: Current timestamp (defaults to time.time())
            
        Returns:
            True if person is active on any camera (within grace period)
        """
        if now_ts is None:
            import time
            now_ts = int(time.time())
        
        cutoff = now_ts - self.grace_period_s
        
        row = conn.execute(
            """
            SELECT COUNT(*) FROM scene_tracks
            WHERE track_type='person' 
              AND track_key=? 
              AND active=1 
              AND last_seen_ts >= ?
            """,
            (visitor_id, cutoff),
        ).fetchone()
        
        return (row[0] if row else 0) > 0

    def get_person_cameras(
        self,
        conn: sqlite3.Connection,
        *,
        visitor_id: str,
        now_ts: int | None = None,
    ) -> list[int]:
        """
        Get all camera IDs where a person is currently active.
        
        Useful for tracking which cameras can see a person, detecting
        camera handoffs, and multi-camera coverage analysis.
        
        Args:
            conn: Database connection
            visitor_id: The visitor_id to check
            now_ts: Current timestamp (defaults to time.time())
            
        Returns:
            List of camera_ids where person is currently active
        """
        if now_ts is None:
            import time
            now_ts = int(time.time())
        
        cutoff = now_ts - self.grace_period_s
        
        rows = conn.execute(
            """
            SELECT DISTINCT camera_id 
            FROM scene_tracks
            WHERE track_type='person' 
              AND track_key=? 
              AND active=1 
              AND last_seen_ts >= ?
            ORDER BY camera_id
            """,
            (visitor_id, cutoff),
        ).fetchall()
        
        return [row[0] for row in rows]

    def get_active_visitors_all_cameras(
        self,
        conn: sqlite3.Connection,
        *,
        now_ts: int | None = None,
    ) -> dict[str, list[int]]:
        """
        Get all active visitors across all cameras.
        
        Returns a mapping of visitor_id -> [camera_ids] showing which
        cameras can currently see each person.
        
        Args:
            conn: Database connection
            now_ts: Current timestamp (defaults to time.time())
            
        Returns:
            Dict mapping visitor_id to list of camera_ids
            
        Example:
            {
                "visitor_001": [1, 2],  # Seen on cameras 1 and 2
                "visitor_002": [3],     # Only on camera 3
            }
        """
        if now_ts is None:
            import time
            now_ts = int(time.time())
        
        cutoff = now_ts - self.grace_period_s
        
        rows = conn.execute(
            """
            SELECT track_key, camera_id, MAX(last_seen_ts) as most_recent
            FROM scene_tracks
            WHERE track_type='person' 
              AND active=1 
              AND last_seen_ts >= ?
            GROUP BY track_key, camera_id
            ORDER BY track_key, camera_id
            """,
            (cutoff,),
        ).fetchall()
        
        result: dict[str, list[int]] = {}
        for visitor_id, camera_id, _ in rows:
            if visitor_id not in result:
                result[visitor_id] = []
            result[visitor_id].append(camera_id)
        
        return result

    def get_currently_present(
        self,
        conn: sqlite3.Connection,
        *,
        camera_id: int,
        track_type: str | None = None,
        now_ts: int | None = None,
    ) -> list[TrackRow]:
        """
        Get tracks that are CURRENTLY present (seen within grace period).
        This is what external systems should use to check current scene state.
        
        Returns only tracks where:
        - active=1 AND
        - last_seen_ts is within grace_period_s of now_ts
        """
        if now_ts is None:
            import time
            now_ts = int(time.time())
        
        cutoff = now_ts - self.grace_period_s
        
        if track_type:
            rows = conn.execute(
                """
                SELECT id, camera_id, track_type, key_kind, track_key,
                       first_seen_ts, last_seen_ts, active, last_box_json, raw_class, color, tags
                FROM scene_tracks
                WHERE camera_id=? AND track_type=? AND active=1 AND last_seen_ts >= ?
                ORDER BY last_seen_ts DESC
                """,
                (camera_id, track_type, cutoff),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, camera_id, track_type, key_kind, track_key,
                       first_seen_ts, last_seen_ts, active, last_box_json, raw_class, color, tags
                FROM scene_tracks
                WHERE camera_id=? AND active=1 AND last_seen_ts >= ?
                ORDER BY last_seen_ts DESC
                """,
                (camera_id, cutoff),
            ).fetchall()
        
        return [
            TrackRow(
                id=int(rid),
                camera_id=int(cid),
                track_type=str(ttype),
                key_kind=str(kkind),
                track_key=str(tkey),
                first_seen_ts=int(fts),
                last_seen_ts=int(lts),
                active=int(active),
                last_box=_json_to_box(lbox),
                raw_class=str(rc) if rc else None,
                color=str(col) if col else None,
                tags=str(tags) if tags else None,
            )
            for (rid, cid, ttype, kkind, tkey, fts, lts, active, lbox, rc, col, tags) in rows
        ]

    def update(
        self,
        conn: sqlite3.Connection,
        *,
        camera_id: int,
        now_ts: int,
        observations: Sequence[Observation],
        event_id: str | None = None,
    ) -> list[Evidence]:
        """
        Update scene tracks with current frame observations and return scene Evidence.
        """
        # Group observations by type
        obs_by_type: dict[str, list[Observation]] = {"vehicle": [], "person": [], "package": []}
        for o in observations:
            if o.track_type in obs_by_type:
                obs_by_type[o.track_type].append(o)

        evidence: list[Evidence] = []

        for track_type in ("vehicle", "person", "package"):
            active_tracks = self._load_active_tracks(conn, camera_id=camera_id, track_type=track_type)
            matched_track_ids: set[int] = set()

            entered = 0
            still_present = 0

            # Build quick maps for strong keys
            by_key: dict[str, TrackRow] = {}
            for tr in active_tracks:
                if tr.track_key:
                    by_key[tr.track_key] = tr

            for obs in obs_by_type[track_type]:
                # 1) Strong-key match first
                strong_key = None
                strong_kind = None
                if track_type == "vehicle" and obs.plate_hmac:
                    strong_key = obs.plate_hmac
                    strong_kind = "plate"
                    print(f"[SceneTracker] Vehicle observation has plate_hmac: {strong_key[:20]}")
                elif track_type == "person" and obs.visitor_id:
                    strong_key = obs.visitor_id
                    strong_kind = "visitor"

                if strong_key and strong_key in by_key:
                    tr = by_key[strong_key]
                    matched_track_ids.add(tr.id)
                    still_present += 1
                    self._update_track_seen(
                        conn,
                        track_id=tr.id,
                        now_ts=now_ts,
                        box=obs.box,
                        raw_class=obs.raw_class,
                        color=obs.color,
                        last_event_id=event_id,
                    )
                    continue

                # 2) IoU match against remaining active tracks
                best = None
                best_iou = 0.0

                for tr in active_tracks:
                    if tr.id in matched_track_ids:
                        continue
                    if not tr.last_box:
                        continue
                    v = iou(obs.box, tr.last_box)
                    if v > best_iou:
                        best_iou = v
                        best = tr

                if best is not None and best_iou >= self.iou_match_threshold:
                    matched_track_ids.add(best.id)
                    still_present += 1
                    self._update_track_seen(
                        conn,
                        track_id=best.id,
                        now_ts=now_ts,
                        box=obs.box,
                        raw_class=obs.raw_class,
                        color=obs.color,
                        last_event_id=event_id,
                    )

                    # 2.5) Upgrade key if we now have a strong key (plate/visitor)
                    if strong_key and best.track_key.startswith("temp:"):
                        # Check if there's an inactive track with this strong key
                        existing_track_id = self._find_inactive_track(
                            conn, camera_id=camera_id, track_type=track_type, track_key=strong_key
                        )
                        
                        # Mark old temp track inactive
                        self._mark_exited(conn, track_id=best.id, now_ts=now_ts)
                        
                        if existing_track_id:
                            # Reactivate the existing track (person/vehicle returned)
                            print(f"[SceneTracker] Reactivating track {strong_kind}={strong_key[:20]}")
                            self._reactivate_track(
                                conn,
                                track_id=existing_track_id,
                                now_ts=now_ts,
                                box=obs.box,
                                raw_class=obs.raw_class,
                                color=obs.color,
                                last_event_id=event_id,
                            )
                            still_present += 1
                        else:
                            # Create new keyed track
                            print(f"[SceneTracker] Upgrading temp track {best.track_key[:20]} to {strong_kind}={strong_key[:20]}")
                            self._insert_track(
                                conn,
                                camera_id=camera_id,
                                track_type=track_type,
                                key_kind=strong_kind or "iou",
                                track_key=strong_key,
                                now_ts=now_ts,
                                box=obs.box,
                                raw_class=obs.raw_class,
                                color=obs.color,
                                last_event_id=event_id,
                            )
                            entered += 1
                    continue

                # 3) New track - use strong key if available, otherwise temp key
                if strong_key:
                    # Check if there's an inactive track with this strong key (person/vehicle returned)
                    existing_track_id = self._find_inactive_track(
                        conn, camera_id=camera_id, track_type=track_type, track_key=strong_key
                    )
                    
                    if existing_track_id:
                        # Reactivate the existing track
                        print(f"[SceneTracker] Reactivating track {strong_kind}={strong_key[:20]}")
                        self._reactivate_track(
                            conn,
                            track_id=existing_track_id,
                            now_ts=now_ts,
                            box=obs.box,
                            raw_class=obs.raw_class,
                            color=obs.color,
                            last_event_id=event_id,
                        )
                        still_present += 1
                    else:
                        # New track with plate/visitor ID
                        self._insert_track(
                            conn,
                            camera_id=camera_id,
                            track_type=track_type,
                            key_kind=strong_kind or "strong",
                            track_key=strong_key,
                            now_ts=now_ts,
                            box=obs.box,
                            raw_class=obs.raw_class,
                            color=obs.color,
                            last_event_id=event_id,
                        )
                        entered += 1
                else:
                    # New track with temporary IoU-based key
                    temp_key = f"temp:{uuid.uuid4().hex}"
                    self._insert_track(
                        conn,
                        camera_id=camera_id,
                        track_type=track_type,
                        key_kind="iou",
                        track_key=temp_key,
                        now_ts=now_ts,
                        box=obs.box,
                        raw_class=obs.raw_class,
                        color=obs.color,
                        last_event_id=event_id,
                    )
                    entered += 1

            # 4) Exit tracks that were not matched, after grace period
            exited = 0
            for tr in active_tracks:
                if tr.id in matched_track_ids:
                    continue
                age = now_ts - tr.last_seen_ts
                if age >= self.grace_period_s:
                    self._mark_exited(conn, track_id=tr.id, now_ts=now_ts)
                    exited += 1

            # Emit evidence for this type
            current_count = len(obs_by_type[track_type])
            if current_count > 0:
                evidence.append(Evidence("scene", f"{track_type}_present", "true", 0.9, object_id=None))
            evidence.append(Evidence("scene", f"{track_type}_count", str(current_count), 1.0, object_id=None))

            if entered > 0:
                evidence.append(Evidence("scene", f"{track_type}_entered", str(entered), 0.9, object_id=None))
            if exited > 0:
                evidence.append(Evidence("scene", f"{track_type}_exited", str(exited), 0.9, object_id=None))
            if still_present > 0:
                evidence.append(Evidence("scene", f"{track_type}_still_present", str(still_present), 0.8, object_id=None))

        conn.commit()
        return evidence


def build_observations_from_vision(
    vr: VisionResult,
    *,
    plate_hmac_by_object_id: dict[int, str] | None = None,
) -> list[Observation]:
    """
    Helper to convert a VisionResult into SceneTracker observations.
    plate_hmac_by_object_id: map vehicle object_id -> plate_hmac when available.
    """
    plate_hmac_by_object_id = plate_hmac_by_object_id or {}

    obs: list[Observation] = []
    for o in (vr.objects or []):
        label = (o.label or "").lower()
        if label not in ("vehicle", "person", "package"):
            continue

        # If you add this in vision: obj.props["raw_class"] = det.cls.lower()
        raw_class = (o.props.get("raw_class") if getattr(o, "props", None) else None)
        color = (o.props.get("color") if getattr(o, "props", None) else None)

        plate_hmac = None
        visitor_id = None

        if label == "vehicle":
            plate_hmac = plate_hmac_by_object_id.get(int(o.object_id)) if o.object_id is not None else None
        elif label == "person":
            visitor_id = o.props.get("visitor_id") if getattr(o, "props", None) else None

        obs.append(
            Observation(
                track_type=label,
                box=o.box,
                raw_class=str(raw_class) if raw_class else None,
                color=str(color) if color else None,
                plate_hmac=str(plate_hmac) if plate_hmac else None,
                visitor_id=str(visitor_id) if visitor_id else None,
            )
        )

    return obs

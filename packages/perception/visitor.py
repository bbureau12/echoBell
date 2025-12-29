# packages/perception/visitor.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple
import json
import math
import time
from uuid import uuid4
import sqlite3

import cv2
import numpy as np

from packages.common.types import Camera
from packages.data.cache.cache import Cache
from packages.data.cache.reid_cache import ReidHit, get_cached_cam_hit, set_cached_last_seen
from packages.data.camera_service import CameraService
from packages.perception.visitor_types import VisitorQuality, VisitorMatch
from packages.perception.trusted_embeddings.trusted_face_matching import try_match_trusted
# -----------------------------
# Config
# -----------------------------

# Similarity thresholds (cosine sim). Tune with real clips.
KNOWN_MATCH_THRESHOLD = 0.88

# How many embeddings to compare against per match query (keeps it fast).
# For MVP we compare against the most recent embedding per visitor.
MAX_CANDIDATES = 200

# Intent memory decay half-life in days
INTENT_HALF_LIFE_DAYS = 14.0


# -----------------------------
# Types
# -----------------------------


# -----------------------------
# ReID model loader (TorchReID GitHub version)
# -----------------------------

_REID_EXTRACTOR = None
_REID_MODEL_NAME = None


def _get_reid_extractor(model_name: str):
    """
    Lazy singleton. Uses torchreid.utils.FeatureExtractor from deep-person-reid.
    """
    global _REID_EXTRACTOR, _REID_MODEL_NAME
    if _REID_EXTRACTOR is not None and _REID_MODEL_NAME == model_name:
        return _REID_EXTRACTOR

    # Import here so visitor.py still imports even if torchreid isn't installed
    from torchreid.utils import FeatureExtractor  # type: ignore

    _REID_EXTRACTOR = FeatureExtractor(
        model_name=model_name,
        device="cuda" if _has_cuda() else "cpu",
    )
    _REID_MODEL_NAME = model_name
    return _REID_EXTRACTOR


def _has_cuda() -> bool:
    try:
        import torch
        return bool(torch.cuda.is_available())
    except Exception:
        return False


def extract_reid_embedding(frame_bgr: np.ndarray, box: Tuple[int, int, int, int], *, model_name: str) -> np.ndarray:
    """
    Returns L2-normalized float32 embedding suitable for cosine similarity.
    Raises ValueError with actionable context on failure.
    """
    if frame_bgr is None or frame_bgr.size == 0:
        raise ValueError("frame_bgr is empty")

    h, w = frame_bgr.shape[:2]
    x1, y1, x2, y2 = (int(box[0]), int(box[1]), int(box[2]), int(box[3]))

    # Clamp to image bounds
    x1 = max(0, min(x1, w - 1))
    x2 = max(0, min(x2, w))
    y1 = max(0, min(y1, h - 1))
    y2 = max(0, min(y2, h))

    # Validate box after clamp
    if x2 <= x1 or y2 <= y1:
        raise ValueError(f"Invalid crop box after clamp: box={box} clamped={(x1,y1,x2,y2)} frame_wh={(w,h)}")

    crop = frame_bgr[y1:y2, x1:x2]
    if crop.size == 0:
        raise ValueError(f"Empty crop: clamped={(x1,y1,x2,y2)} frame_wh={(w,h)}")

    # BGR -> RGB, make contiguous (some libs are picky)
    rgb = np.ascontiguousarray(crop[:, :, ::-1])

    extractor = _get_reid_extractor(model_name)

    try:
        out = extractor([rgb])
    except Exception as e:
        raise ValueError(f"ReID extractor failed: {type(e).__name__}: {e}")

    if out is None or len(out) == 0:
        raise ValueError("ReID extractor returned empty output")

    feat = out[0]
    if feat is None:
        raise ValueError("ReID extractor returned None feature")
    feat = np.asarray(feat, dtype="float32")
    if feat.ndim != 1 or feat.size == 0:
        raise ValueError(f"Bad feature shape: shape={feat.shape}")

    # L2 normalize
    norm = float(np.linalg.norm(feat))
    if norm > 0:
        feat /= norm
    return feat



def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    # assumes both already normalized
    return float(np.dot(a, b))


# -----------------------------
# Quality gate (your 2K tuned gate)
# -----------------------------

def assess_person_quality(frame_bgr: np.ndarray, box: Tuple[int, int, int, int]) -> VisitorQuality:
    x1, y1, x2, y2 = box
    w = x2 - x1
    h = y2 - y1
    area = w * h

    # --- size gate (2K tuned) ---
    if h < 180 or w < 80 or area < 22_000:
        return VisitorQuality(ok=False, tier="skip", blur_score=0.0, reason="bbox_too_small")

    crop = frame_bgr[y1:y2, x1:x2]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    # --- blur gate ---
    if blur < 100:
        return VisitorQuality(ok=False, tier="skip", blur_score=blur, reason="too_blurry")

    # --- tier selection ---
    if h >= 300 and area >= 45_000 and blur >= 200:
        return VisitorQuality(ok=True, tier="trusted", blur_score=blur)

    return VisitorQuality(ok=True, tier="known", blur_score=blur)


# -----------------------------
# Evidence emission helpers
# -----------------------------

def _append_obj_evidence(vr, obj_id: int, source: str, feature: str, value: str, conf: float) -> None:
    """
    Adds evidence to the *object's* evidence list only.
    vision.py later flattens obj.evidence into vr.evidence. :contentReference[oaicite:1]{index=1}
    """
    # import locally to avoid circular import at module load time
    from packages.common.types import Evidence  # type: ignore

    # locate object by id (object_id == index in vr.objects today)
    # safer: scan
    target = None
    for o in vr.objects:
        if o.object_id == obj_id:
            target = o
            break
    if target is None:
        return

    target.evidence.append(Evidence(
        source=source,
        feature=feature,
        value=value,
        conf=float(conf),
        object_id=obj_id
    ))


def emit_quality_evidence(vr, obj_id: int, quality: VisitorQuality) -> None:
    _append_obj_evidence(vr, obj_id, "visitor", "visitor.match_attempted", str(quality.ok).lower(), 1.0)
    if not quality.ok:
        _append_obj_evidence(vr, obj_id, "visitor", "visitor.skip_reason", quality.reason or "unknown", 1.0)
        _append_obj_evidence(vr, obj_id, "visitor", "visitor.blur_score", f"{quality.blur_score:.1f}", 1.0)
    else:
        _append_obj_evidence(vr, obj_id, "visitor", "visitor.quality_tier", quality.tier, 1.0)
        _append_obj_evidence(vr, obj_id, "visitor", "visitor.blur_score", f"{quality.blur_score:.1f}", 1.0)


def emit_match_evidence(vr, obj_id: int, match: VisitorMatch) -> None:
    if match.kind == "skipped":
        return

    if match.kind == "trusted":
        _append_obj_evidence(vr, obj_id, "visitor", "visitor.trusted", "true", max(0.01, match.similarity))
        _append_obj_evidence(vr, obj_id, "visitor", "visitor.similarity", f"{match.similarity:.3f}", 1.0)
        if match.trusted_id is not None:
            _append_obj_evidence(vr, obj_id, "visitor", "visitor.trusted_id", str(match.trusted_id), 1.0)
        if match.trusted_label:
            _append_obj_evidence(vr, obj_id, "visitor", "visitor.trusted_label", match.trusted_label, 1.0)

    elif match.kind == "known":
        _append_obj_evidence(vr, obj_id, "visitor", "visitor.known", "true", max(0.01, match.similarity))
        _append_obj_evidence(vr, obj_id, "visitor", "visitor.similarity", f"{match.similarity:.3f}", 1.0)
        _append_obj_evidence(vr, obj_id, "visitor", "visitor.visit_count_total", str(match.visit_count_total), 1.0)
        _append_obj_evidence(vr, obj_id, "visitor", "visitor.visit_count_7d", str(match.visit_count_7d), 1.0)
        _append_obj_evidence(vr, obj_id, "visitor", "visitor.visit_count_30d", str(match.visit_count_30d), 1.0)

        if match.intent_last:
            _append_obj_evidence(vr, obj_id, "visitor", "visitor.intent_last", match.intent_last, 1.0)

            if match.intent_last_ts:
                hours = max(0, int((int(time.time()) - int(match.intent_last_ts)) / 3600))
                _append_obj_evidence(vr, obj_id, "visitor", "visitor.intent_last_hours", str(hours), 1.0)

    elif match.kind == "new":
        _append_obj_evidence(vr, obj_id, "visitor", "visitor.new", "true", 1.0)


# -----------------------------
# DB helpers
# -----------------------------

def _fetch_recent_visitor_candidates(conn, model_name: str) -> list[tuple[str, bytes]]:
    """
    Returns list of (visitor_id, embedding_blob) using only the most recent embedding per visitor.
    Keeps matching fast and avoids tons of near-duplicate samples.
    """
    rows = conn.execute(
        """
        SELECT ve.visitor_id, ve.embedding_blob
        FROM visitor_embeddings ve
        JOIN (
            SELECT visitor_id, MAX(created_ts) AS max_ts
            FROM visitor_embeddings
            WHERE model_name = ?
            GROUP BY visitor_id
        ) latest
          ON latest.visitor_id = ve.visitor_id AND latest.max_ts = ve.created_ts
        ORDER BY ve.created_ts DESC
        LIMIT ?
        """,
        (model_name, MAX_CANDIDATES),
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def _fetch_known_visitor_row(conn, visitor_id: str) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        """
        SELECT visitor_id, first_seen_ts, last_seen_ts,
               visit_count_total, visit_count_7d, visit_count_30d,
               intent_last, intent_last_ts
        FROM known_visitors
        WHERE visitor_id = ?
        """,
        (visitor_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "visitor_id": row[0],
        "first_seen_ts": int(row[1]),
        "last_seen_ts": int(row[2]),
        "visit_count_total": int(row[3]),
        "visit_count_7d": int(row[4]),
        "visit_count_30d": int(row[5]),
        "intent_last": row[6],
        "intent_last_ts": int(row[7]) if row[7] is not None else None,
    }


def _update_visit_counters(prev_last_seen_ts: int, now_ts: int, prev_7d: int, prev_30d: int) -> tuple[int, int]:
    # simple rolling counters with reset if gap exceeds window
    days_since = (now_ts - prev_last_seen_ts) / 86400.0
    new_7d = 1 if days_since > 7.0 else (prev_7d + 1)
    new_30d = 1 if days_since > 30.0 else (prev_30d + 1)
    return new_7d, new_30d


def _insert_embedding(conn, visitor_id: str, model_name: str, emb: np.ndarray, now_ts: int, source_event_id: Optional[str] = None, camera_id: Optional[int] = None):
    conn.execute(
        """
        INSERT INTO visitor_embeddings (
            embedding_id, visitor_id, model_name, embedding_dim, embedding_blob,
            source_event_id, created_ts, quality_score, camera_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid4().hex,
            visitor_id,
            model_name,
            int(emb.shape[0]),
            emb.astype("float32").tobytes(),
            source_event_id,
            int(now_ts),
            1.0,
            camera_id,
        ),
    )


def try_match_known(conn, emb: np.ndarray, *, model_name: str, now_ts: int, camera_id: Optional[int] = None, cache: Optional[Cache] = None) -> Optional[VisitorMatch]:
    hit = get_cached_cam_hit(cache, camera_id = camera_id, model_name = model_name)
    if hit and hit.sim >= KNOWN_MATCH_THRESHOLD:
        print("found in cache")
        return VisitorMatch(
            kind="known",
            visitor_id=hit.visitor_id,
            similarity=hit.sim,
            trusted_pending=hit.trusted_pending,
            trusted_verified=hit.trusted_verified
        )

    candidates = _fetch_recent_visitor_candidates(conn, model_name=model_name)
    if not candidates:
        return None

    best_id = None
    best_sim = -1.0

    for visitor_id, blob in candidates:
        db_emb = np.frombuffer(blob, dtype="float32")
        # normalize defensively
        n = float(np.linalg.norm(db_emb))
        if n > 0:
            db_emb = db_emb / n

        sim = cosine_similarity(emb, db_emb)
        if sim > best_sim:
            best_sim = sim
            best_id = visitor_id

    if best_id is None or best_sim < KNOWN_MATCH_THRESHOLD:
        return None

    row = _fetch_known_visitor_row(conn, best_id)
    if not row:
        return None
    
    result = VisitorMatch(
        kind="known",
        visitor_id=best_id,
        similarity=float(best_sim),
        visit_count_total=int(row["visit_count_total"]),
        visit_count_7d=int(row["visit_count_7d"]),
        visit_count_30d=int(row["visit_count_30d"]),
        intent_last=row.get("intent_last"),
        intent_last_ts=row.get("intent_last_ts"),
    )
    set_cached_last_seen(cache, hit=ReidHit(visitor_id=best_id, sim=best_sim, trusted_pending=result.trusted_pending, trusted_verified=result.trusted_verified, model_name=model_name, camera_id=camera_id, ts=now_ts))

    return result


def create_new_visitor(conn, *, now_ts: int) -> str:
    visitor_id = uuid4().hex
    conn.execute(
        """
        INSERT INTO known_visitors (
            visitor_id, first_seen_ts, last_seen_ts,
            visit_count_total, visit_count_7d, visit_count_30d,
            confidence_score, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (visitor_id, int(now_ts), int(now_ts), 1, 1, 1, 0.0, "active"),
    )
    return visitor_id


def update_known_visitor_on_match(conn, visitor_id: str, now_ts: int) -> VisitorMatch:
    row = _fetch_known_visitor_row(conn, visitor_id)
    if not row:
        # should not happen, but be safe
        visitor_id = create_new_visitor(conn, now_ts=now_ts)
        return VisitorMatch(kind="new", visitor_id=visitor_id)

    new_7d, new_30d = _update_visit_counters(
        prev_last_seen_ts=int(row["last_seen_ts"]),
        now_ts=int(now_ts),
        prev_7d=int(row["visit_count_7d"]),
        prev_30d=int(row["visit_count_30d"]),
    )

    new_total = int(row["visit_count_total"]) + 1

    conn.execute(
        """
        UPDATE known_visitors
        SET last_seen_ts=?,
            visit_count_total=?,
            visit_count_7d=?,
            visit_count_30d=?
        WHERE visitor_id=?
        """,
        (int(now_ts), new_total, new_7d, new_30d, visitor_id),
    )

    return VisitorMatch(
        kind="known",
        visitor_id=visitor_id,
        similarity=0.0,  # will be overwritten by caller if desired
        visit_count_total=new_total,
        visit_count_7d=new_7d,
        visit_count_30d=new_30d,
        intent_last=row.get("intent_last"),
        intent_last_ts=row.get("intent_last_ts"),
    )


# -----------------------------
# Public API (called from vision.py)
# -----------------------------

def process_person_and_emit_evidence(
    *,
    conn,
    vr,
    frame_bgr: np.ndarray,
    person_object_id: int,
    person_box: Tuple[int, int, int, int],
    now_ts: int,
    model_name: str = "osnet_x0_5",
    camera_id: Optional[int] = None,
    cache: Optional[Cache] = None,
    camera_service: Optional[CameraService] = None,
) -> VisitorMatch:
    """
    - quality gate
    - match trusted (stub) then known visitor
    - if no match: create visitor
    - store embedding for matched/new visitors
    - emit evidence onto the person SceneObject
    """
    quality = assess_person_quality(frame_bgr, person_box)
    emit_quality_evidence(vr, person_object_id, quality)

    if not quality.ok:
        m = VisitorMatch(kind="skipped")
        return m

    # Extract embedding
    try:
        emb = extract_reid_embedding(frame_bgr, person_box, model_name=model_name)
    except Exception as e:
        _append_obj_evidence(vr, person_object_id, "visitor", "visitor.embed_error", str(e)[:80], 1.0)
        return VisitorMatch(kind="skipped")


    # Trusted (later)
    if quality.tier == "trusted" and camera_id and camera_service:
        camera = camera_service.get_camera(conn, camera_id)
        if camera and camera.capability and camera.capability.allow_facial_detail:
            trusted = try_match_trusted(
                conn,
                camera_service,
                camera_id=camera_id,
                cache=cache,
                frame_bgr=frame_bgr,
                person_box=person_box,
                model_pack="buffalo_l",  # Can be made configurable later
                threshold=0.60,
                margin=0.05,
            )
            if trusted:
                emit_match_evidence(vr, person_object_id, trusted)
                return trusted

    # Known visitor matching
    known = try_match_known(conn, emb, model_name=model_name, now_ts=now_ts, camera_id=camera_id, cache=cache)
    if known:
        # update counters + last seen
        updated = update_known_visitor_on_match(conn, known.visitor_id, now_ts)
        updated.similarity = known.similarity

        # store another embedding sample (helps robustness)
        _insert_embedding(conn, updated.visitor_id, model_name, emb, now_ts, camera_id=camera_id)

        emit_match_evidence(vr, person_object_id, updated)
        return updated

    # New visitor
    visitor_id = create_new_visitor(conn, now_ts=now_ts)
    _insert_embedding(conn, visitor_id, model_name, emb, now_ts, camera_id=camera_id)

    new_match = VisitorMatch(kind="new", visitor_id=visitor_id)
    emit_match_evidence(vr, person_object_id, new_match)
    return new_match


# -----------------------------
# Intent memory update (call AFTER classify())
# -----------------------------

def _decay_factor(dt_seconds: float, half_life_days: float) -> float:
    if dt_seconds <= 0:
        return 1.0
    half_life_seconds = half_life_days * 86400.0
    return 0.5 ** (dt_seconds / half_life_seconds)


def update_visitor_intent_memory(
    *,
    conn,
    visitor_id: str,
    intent: str,
    conf: float,
    now_ts: int,
) -> None:
    """
    Decay + update:
      - intent_last
      - intent_last_ts
      - intent_score_json
    """
    row = conn.execute(
        "SELECT intent_score_json, intent_last_ts FROM known_visitors WHERE visitor_id=?",
        (visitor_id,),
    ).fetchone()
    if not row:
        return

    score_json = row[0] or "{}"
    last_ts = int(row[1]) if row[1] is not None else None

    try:
        scores = json.loads(score_json) if isinstance(score_json, str) else {}
    except Exception:
        scores = {}

    # decay previous scores
    if last_ts is not None:
        f = _decay_factor(float(now_ts - last_ts), INTENT_HALF_LIFE_DAYS)
        for k in list(scores.keys()):
            scores[k] = float(scores[k]) * f

    # add current intent evidence
    intent = (intent or "").strip()
    if intent:
        scores[intent] = float(scores.get(intent, 0.0)) + float(max(0.0, min(1.0, conf)))

    # optional normalization (keeps numbers sane)
    total = sum(float(v) for v in scores.values())
    if total > 0:
        for k in list(scores.keys()):
            scores[k] = float(scores[k]) / total

    conn.execute(
        """
        UPDATE known_visitors
        SET intent_last=?,
            intent_last_ts=?,
            intent_score_json=?
        WHERE visitor_id=?
        """,
        (intent or None, int(now_ts), json.dumps(scores, separators=(",", ":")), visitor_id),
    )

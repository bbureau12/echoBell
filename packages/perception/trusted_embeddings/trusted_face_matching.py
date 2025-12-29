from __future__ import annotations

import base64
import io
import sqlite3
from dataclasses import dataclass
from typing import Optional, Tuple, List

import numpy as np
import cv2
from insightface.app import FaceAnalysis

from packages.data.cache.cache import Cache
from packages.data.camera_service import CameraService
from packages.perception.visitor_types import VisitorMatch

@dataclass(frozen=True)
class TrustedFaceIndex:
    trusted_ids: np.ndarray   # (N,) int
    labels: list[str]         # (N,)
    embs: np.ndarray          # (N, D) float32, L2-normalized


# ---- Face app singleton (avoid reloading models per call) ----
_FACE_APPS: dict[str, FaceAnalysis] = {}


def _get_face_app(model_pack: str) -> FaceAnalysis:
    app = _FACE_APPS.get(model_pack)
    if app is None:
        app = FaceAnalysis(name=model_pack)
        app.prepare(ctx_id=-1, det_size=(640, 640))  # CPU
        _FACE_APPS[model_pack] = app
    return app


def _l2_normalize(x: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(x))
    return x if n == 0 else (x / n)


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    # assumes both normalized
    return float(np.dot(a, b))


def _serialize_index(idx: TrustedFaceIndex) -> str:
    buf = io.BytesIO()
    # labels as an object array
    np.savez_compressed(
        buf,
        trusted_ids=idx.trusted_ids.astype(np.int64),
        labels=np.array(idx.labels, dtype=object),
        embs=idx.embs.astype(np.float32),
    )
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _deserialize_index(s: str) -> TrustedFaceIndex:
    raw = base64.b64decode(s.encode("ascii"))
    buf = io.BytesIO(raw)
    data = np.load(buf, allow_pickle=True)
    trusted_ids = data["trusted_ids"].astype(np.int64)
    labels = [str(x) for x in data["labels"].tolist()]
    embs = data["embs"].astype(np.float32)
    return TrustedFaceIndex(trusted_ids=trusted_ids, labels=labels, embs=embs)


def _load_trusted_face_index_from_db(conn: sqlite3.Connection, *, model_name: str) -> TrustedFaceIndex:
    rows = conn.execute(
        """
        SELECT tp.trusted_id, tp.label, tpe.embedding_blob
        FROM trusted_person_embedding tpe
        JOIN trusted_person tp ON tp.trusted_id = tpe.trusted_id
        WHERE tpe.embedding_type = 'face'
          AND tpe.model_name = ?
        """,
        (model_name,),
    ).fetchall()

    if not rows:
        return TrustedFaceIndex(
            trusted_ids=np.array([], dtype=np.int64),
            labels=[],
            embs=np.zeros((0, 512), dtype=np.float32),
        )

    ids: list[int] = []
    labels: list[str] = []
    embs: list[np.ndarray] = []

    for trusted_id, label, blob in rows:
        e = np.frombuffer(blob, dtype="float32")
        e = _l2_normalize(e.astype("float32"))
        ids.append(int(trusted_id))
        labels.append(str(label or ""))
        embs.append(e)

    E = np.stack(embs, axis=0).astype("float32")
    return TrustedFaceIndex(trusted_ids=np.array(ids, dtype=np.int64), labels=labels, embs=E)


def _get_cached_trusted_index(
    conn: sqlite3.Connection,
    *,
    cache: Optional[Cache],
    model_name: str,
    ttl_s: int = 900,
) -> TrustedFaceIndex:
    key = f"trusted_face_index:{model_name}"
    if cache:
        s = cache.get(key)
        if s:
            try:
                return _deserialize_index(s)
            except Exception:
                # fall through to rebuild
                pass

    idx = _load_trusted_face_index_from_db(conn, model_name=model_name)

    if cache:
        try:
            cache.set(key, _serialize_index(idx), ttl_s=ttl_s)
        except Exception:
            pass

    return idx


def _extract_best_face_embedding(
    *,
    app: FaceAnalysis,
    frame_bgr: np.ndarray,
    person_box: Tuple[int, int, int, int],
    min_det_score: float = 0.60,
    min_face_px: int = 70,
) -> Optional[np.ndarray]:
    x1, y1, x2, y2 = person_box
    h, w = frame_bgr.shape[:2]
    x1 = max(0, min(w - 1, x1))
    x2 = max(0, min(w, x2))
    y1 = max(0, min(h - 1, y1))
    y2 = max(0, min(h, y2))
    if x2 <= x1 or y2 <= y1:
        return None

    crop = frame_bgr[y1:y2, x1:x2]
    faces = app.get(crop) or []
    best = None
    best_score = -1.0

    for f in faces:
        score = float(getattr(f, "det_score", 1.0))
        if score < min_det_score:
            continue
        fx1, fy1, fx2, fy2 = [int(v) for v in f.bbox]
        fw, fh = (fx2 - fx1), (fy2 - fy1)
        if fw < min_face_px or fh < min_face_px:
            continue
        if score > best_score:
            best_score = score
            best = f

    if best is None:
        return None

    emb = best.embedding.astype("float32")
    return _l2_normalize(emb)


def try_match_trusted(
    conn: sqlite3.Connection,
    camera_service: CameraService,
    *,
    camera_id: Optional[int] = None,
    cache: Optional[Cache] = None,
    frame_bgr: np.ndarray,
    person_box: Tuple[int, int, int, int],
    model_pack: str = "buffalo_l",
    threshold: float = 0.60,
    margin: float = 0.05,
) -> Optional[VisitorMatch]:
    # 1) Gate by capability
    if camera_id is None:
        return None

    cam = camera_service.get_camera(conn, camera_id)
    if not cam or not cam.capability.allow_facial_detail:
        return None

    model_name = model_pack  # Use model pack name directly (e.g., "buffalo_l")

    # 2) Compute face embedding from this person crop
    app = _get_face_app(model_pack)
    live = _extract_best_face_embedding(app=app, frame_bgr=frame_bgr, person_box=person_box)
    if live is None:
        return None

    # 3) Load trusted index (cache -> DB)
    idx = _get_cached_trusted_index(conn, cache=cache, model_name=model_name)
    if idx.embs.shape[0] == 0:
        return None

    # 4) Compare (cosine because normalized)
    sims = idx.embs @ live  # (N,)
    best_i = int(np.argmax(sims))
    best_sim = float(sims[best_i])

    # Optional margin check to avoid ambiguity
    second_sim = float(np.partition(sims, -2)[-2]) if sims.shape[0] >= 2 else -1.0
    if best_sim < threshold:
        return None
    if (best_sim - second_sim) < margin:
        return None

    trusted_id = int(idx.trusted_ids[best_i])
    label = idx.labels[best_i] if best_i < len(idx.labels) else ""

    return VisitorMatch(
        kind="trusted",
        trusted_id=trusted_id,
        trusted_label=label,
        similarity=best_sim,
    )

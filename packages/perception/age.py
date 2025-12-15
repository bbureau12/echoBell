# packages/perception/age.py
from __future__ import annotations

import os
import sys
from typing import List, Optional, Tuple
import numpy as np


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from packages.common.types import Evidence, SceneObject

# InsightFace
from insightface.app import FaceAnalysis

_app: FaceAnalysis | None = None


def _get_app() -> FaceAnalysis:
    """
    Lazy init singleton FaceAnalysis.
    CPU-friendly default: providers=['CPUExecutionProvider'].
    """
    global _app
    if _app is None:
        app = FaceAnalysis(
            name="buffalo_l",
            providers=["CPUExecutionProvider"],
        )
        # det_size controls face detector input size (bigger = better small faces, slower)
        app.prepare(ctx_id=-1, det_size=(640, 640))
        _app = app
    return _app


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _largest_face(faces) -> Optional[object]:
    """Pick the largest face by bbox area."""
    best = None
    best_area = -1.0
    for f in faces:
        x1, y1, x2, y2 = [float(v) for v in f.bbox]
        area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
        if area > best_area:
            best_area = area
            best = f
    return best


def _age_to_group(age: float) -> str:
    # Simple first pass: young vs adult
    return "young" if age < 18.0 else "adult"


def _age_confidence(age: float, det_score: float) -> float:
    """
    Heuristic confidence:
    - scaled by face detector confidence
    - penalize ages near the boundary (18)
    """
    # how far from boundary?
    margin = abs(age - 18.0)  # 0 = right on boundary
    # convert margin into 0..1 boost (>=8 years away is "pretty confident")
    margin_boost = _clamp(margin / 8.0)

    # base confidence from detector score (often ~0.7-0.95)
    base = float(det_score) if det_score is not None else 0.7

    # combine
    conf = 0.55 + 0.35 * margin_boost  # 0.55..0.90
    conf *= _clamp(base, 0.4, 1.0)     # scale by detector confidence
    return _clamp(conf, 0.40, 0.95)


def emit_age_evidence_for_people(
    frame_bgr: np.ndarray,
    objects: List[SceneObject],
) -> List[Evidence]:
    """
    For each SceneObject labeled 'person' that has a .box, run face detection on the crop.
    Returns Evidence records with object_id set.
    """
    app = _get_app()
    h, w = frame_bgr.shape[:2]
    out: List[Evidence] = []

    for obj in objects:
        if (obj.label or "").lower() != "person":
            continue
        if obj.box is None:
            continue

        x1, y1, x2, y2 = obj.box
        # clamp
        x1 = max(0, min(int(x1), w - 1))
        x2 = max(0, min(int(x2), w))
        y1 = max(0, min(int(y1), h - 1))
        y2 = max(0, min(int(y2), h))
        if x2 <= x1 or y2 <= y1:
            continue

        crop_bgr = frame_bgr[y1:y2, x1:x2]
        if crop_bgr.size == 0:
            continue

        faces = app.get(crop_bgr)
        if not faces:
            continue

        face = _largest_face(faces)
        if face is None:
            continue

        age = float(getattr(face, "age", 0.0) or 0.0)
        det_score = float(getattr(face, "det_score", 0.7) or 0.7)

        group = _age_to_group(age)
        conf = _age_confidence(age, det_score)

        out.append(
            Evidence(
                source="age",
                feature="age_group",
                value=group,
                conf=conf,
                object_id=obj.object_id,
            )
        )

        # Optional: store as a prop too (handy for debugging/UI)
        obj.props["age_group"] = group
        obj.props["age_estimate"] = int(round(age))
        obj.props["age_conf"] = conf

    return out

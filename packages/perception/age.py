from __future__ import annotations

import importlib
import os
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import torch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from packages.common.types import Evidence, SceneObject
from tools.torch_utils import allowlist_checkpoint_globals, enable_ultralytics_safe_load


# ----------------------------
# MiVOLO lazy predictor
# ----------------------------

# MiVOLO imports are intentionally inside _get_predictor() so your app can still boot
# even if age grouping is disabled / deps not installed.

_mivolo_predictor = None
def _get_predictor():
    global _mivolo_predictor
    if _mivolo_predictor is not None:
        return _mivolo_predictor

    from pathlib import Path
    import os

    detector = os.getenv("MIVOLO_DETECTOR_WEIGHTS", "models/yolov8x_person_face.pt")
    checkpoint = os.getenv("MIVOLO_CHECKPOINT", "models/model_imdb_cross_person_4.22_99.46.pth.tar")
    device = os.getenv("MIVOLO_DEVICE", "cpu")

    detector_path = str(Path(detector).expanduser().resolve())
    checkpoint_path = str(Path(checkpoint).expanduser().resolve())

    try:
        print(f"[age] MiVOLO detector:   {detector_path} (exists={Path(detector_path).exists()})")
        print(f"[age] MiVOLO checkpoint: {checkpoint_path} (exists={Path(checkpoint_path).exists()})")
        print(f"[age] MiVOLO device:     {device}")

        # MUST happen before any YOLO .pt load (covers MiVOLO/Ultralytics internals)
        enable_ultralytics_safe_load()

        # Allowlist globals referenced by the *actual* detector checkpoint (if helper works)
        if Path(detector_path).exists():
            allowlist_checkpoint_globals(detector_path)
        else:
            print("[age] WARNING: detector weights not found; cannot allowlist checkpoint globals.")
            import importlib
            print("[age] Conv module:", importlib.import_module("ultralytics.nn.modules").Conv.__module__)


        from types import SimpleNamespace
        from mivolo.predictor import Predictor  # import once, after safe-globals

        cfg = SimpleNamespace(
            detector_weights=detector_path,
            checkpoint=checkpoint_path,
            device=device,
            with_persons=True,
            disable_faces=False,
            draw=False,
        )

        _mivolo_predictor = Predictor(cfg)
        return _mivolo_predictor

    except Exception as e:
        print(f"[age] MiVOLO predictor init failed: {e}")
        _mivolo_predictor = None
        return None




# ----------------------------
# Utilities
# ----------------------------

def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _iou(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b

    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)

    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)
    inter = iw * ih

    if inter <= 0:
        return 0.0

    a_area = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    b_area = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = a_area + b_area - inter
    return inter / union if union > 0 else 0.0


def _age_to_group(age: float) -> str:
    """
    Safer mapping for "minor vs adult" from an apparent-age regressor:
      - young: clearly under
      - adult: clearly over
      - unknown: ambiguous zone (prevents '23' on a kid from becoming 'adult')
    Tune bounds based on your tolerance.
    """
    if age <= 0:
        return "unknown"
    if age < 16.0:
        return "young"
    if age <= 27.0:
        return "unknown"
    return "adult"


def extract_person_ages(detected_objects) -> float:
    ages = getattr(detected_objects, "ages", None)
    if ages:
        age = float(np.mean(np.array(ages, dtype=float)))
        return age
    return None



@dataclass
class _MiVoloPerson:
    box: Tuple[float, float, float, float]
    age: float
    det_conf: Optional[float] = None


def _extract_mivolo_persons(detected_objects) -> List[_MiVoloPerson]:
    persons: List[_MiVoloPerson] = []

    # 1) Ages from MiVOLO (guid -> (age, gender))
    try:
        persons_dict, _faces_dict = detected_objects.get_results_for_tracking()
    except Exception:
        persons_dict = {}

    ages: List[float] = []
    try:
        ages = [float(v[0]) for v in persons_dict.values()]
    except Exception:
        ages = []

    # 2) Person bbox indices (fork-specific: index-based API)
    person_inds = []

    # Preferred: ask MiVOLO for the indices it uses
    if hasattr(detected_objects, "get_bboxes_inds"):
        try:
            inds = detected_objects.get_bboxes_inds()
            # Common shapes: list[int] OR dict-like with 'persons' key OR tuple(persons, faces)
            if isinstance(inds, dict):
                person_inds = list(inds.get("persons", inds.get("person", [])) or [])
            elif isinstance(inds, (tuple, list)) and len(inds) == 2 and all(isinstance(x, (list, tuple)) for x in inds):
                # e.g. (person_inds, face_inds)
                person_inds = list(inds[0])
            else:
                person_inds = list(inds) if isinstance(inds, (list, tuple)) else []
        except Exception:
            person_inds = []

    # Fallback: n_persons -> 0..n-1 (some forks use this indexing)
    if not person_inds and hasattr(detected_objects, "n_persons"):
        try:
            n = int(detected_objects.n_persons)
            person_inds = list(range(n))
        except Exception:
            person_inds = []

    if not person_inds:
        return persons

    # 3) Get bbox by index
    boxes: List[Tuple[float, float, float, float]] = []
    for ind in person_inds:
        try:
            box = detected_objects.get_bbox_by_ind(ind)
        except TypeError:
            # Some forks require a kind arg, try a couple
            box = None
            for kind in ("person", "persons"):
                try:
                    box = detected_objects.get_bbox_by_ind(ind, kind)
                    break
                except Exception:
                    pass
        except Exception:
            box = None

        if box is None:
            continue

        x1, y1, x2, y2 = [float(v) for v in box]
        boxes.append((x1, y1, x2, y2))

    if not boxes:
        return persons

    # 4) Align ages with boxes (best-effort)
    if len(ages) < len(boxes):
        ages = ages + [0.0] * (len(boxes) - len(ages))
    elif len(ages) > len(boxes):
        ages = ages[: len(boxes)]

    for box, age in zip(boxes, ages):
        persons.append(_MiVoloPerson(box=box, age=float(age), det_conf=None))

    return persons



# ----------------------------
# Public API (same as before)
# ----------------------------

def emit_age_evidence_for_people(
    frame_bgr: np.ndarray,
    objects: List[SceneObject],
) -> List[Evidence]:
    """
    Runs MiVOLO once on the full frame, then matches MiVOLO person detections to your
    SceneObject(person) boxes by IoU and emits age_group evidence.
    """
    pred = _get_predictor()
    if pred is None:
        return []

    # Run MiVOLO once
    try:
        detected_objects, _meta = pred.recognize(frame_bgr)
    except Exception as e:
        print(f"[age] MiVOLO recognize failed: {e}")
        return []

    mivolo_persons = _extract_mivolo_persons(detected_objects)
    if not mivolo_persons:
        return []

    out: List[Evidence] = []

    for obj in objects:
        if (obj.label or "").lower() != "person" or obj.box is None:
            continue

        ox1, oy1, ox2, oy2 = [float(v) for v in obj.box]
        obj_box = (ox1, oy1, ox2, oy2)

        # Find best overlapping MiVOLO person
        best = None
        best_iou = 0.0
        for p in mivolo_persons:
            i = _iou(obj_box, p.box)
            if i > best_iou:
                best_iou = i
                best = p

        if best is None or best_iou < 0.20:
            continue

        age = extract_person_ages(detected_objects)
        if age is None:
            continue

        group = _age_to_group(age)
        conf = 0.85  # or whatever heuristic you want

        out.append(Evidence(source="age", feature="age_group", value=group, conf=conf, object_id=obj.object_id))
        obj.props["age_estimate"] = float(age)
        obj.props["age_group"] = group

    return out

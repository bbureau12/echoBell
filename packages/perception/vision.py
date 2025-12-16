# packages/perception/vision.py
import sqlite3
import os, time
from typing import List
import numpy as np
from ultralytics import YOLO
import cv2
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from packages.common.types import Detection, Evidence, VisionResult, SceneObject
from .ocr import extract_ocr_tokens_by_object
from .age import emit_age_evidence_for_people

_MODEL = YOLO("yolov8n.pt")
MODEL_NAME = "yolov8n"

POSITIVE_CLASSES = {
    "person": "person",
    "microwave": "package",
    "oven": "package",
    "suitcase": "package",
    "truck": "vehicle",
    "car": "vehicle",
    "motorbike": "vehicle",
    "dog": "dog",
    "tie": "tie",
}

CSS_COLORS = {
    "black":  (0, 0, 0),
    "white":  (255, 255, 255),
    "gray":   (128, 128, 128),
    "red":    (200, 40, 40),
    "green":  (40, 160, 40),
    "blue":   (40, 80, 200),
    "yellow": (220, 220, 40),
    "orange": (230, 140, 40),
    "brown":  (140, 90, 40),
    "tan":    (210, 180, 140),
}

MIN_CONF = {
    "person": 0.45,
    "tie": 0.50,
    "vehicle": 0.40,
    "package": 0.35,
    "dog": 0.35,
}

def _derive_flags(labels: List[str]) -> dict:
    return {
        "person_present": any(l == "person" for l in labels),
        "package_box": any(l == "package" for l in labels),
        "vehicle_present": any(l == "vehicle" for l in labels),
        "dog_present": any(l == "dog" for l in labels),
        "uniform": None,  # placeholder
    }


def _fetch_vision_map(conn, model_name: str) -> dict[str, str]:
    rows = conn.execute(
        "SELECT raw_class, semantic_class FROM vision_class_map "
        "WHERE enabled=1 AND model_name=?",
        (model_name,),
    ).fetchall()
    return {raw: sem for (raw, sem) in rows}

def _containment(child_box, parent_box) -> float:
    cx1, cy1, cx2, cy2 = child_box
    px1, py1, px2, py2 = parent_box

    ix1, iy1 = max(cx1, px1), max(cy1, py1)
    ix2, iy2 = min(cx2, px2), min(cy2, py2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih

    c_area = max(1, (cx2 - cx1) * (cy2 - cy1))
    return inter / c_area  # “% of child covered by parent”

def _attach_children(scene_objects):
    persons = [o for o in scene_objects if (o.label or "").lower() == "person" and o.box]

    for o in scene_objects:
        if not o.box:
            continue
        if (o.label or "").lower() == "person":
            continue

        best_parent = None
        best_score = 0.0
        for p in persons:
            s = _containment(o.box, p.box)
            if s > best_score:
                best_score = s
                best_parent = p

        # require strong containment so we don't attach random background junk
        if best_parent and best_score >= 0.70:
            o.parent_id = best_parent.object_id




def _dominant_color_rgb(crop: np.ndarray, k: int = 3) -> np.ndarray:
    if crop is None or crop.size == 0:
        return np.array([0.0, 0.0, 0.0], dtype=np.float32)

    pixels = crop.reshape(-1, 3).astype(np.float32)

    if pixels.shape[0] > 5000:
        idx = np.random.choice(pixels.shape[0], 5000, replace=False)
        pixels = pixels[idx]

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
    _ret, labels, centers = cv2.kmeans(
        pixels, k, None, criteria, 5, cv2.KMEANS_RANDOM_CENTERS
    )
    counts = np.bincount(labels.flatten())
    dom_bgr = centers[np.argmax(counts)]
    dom_rgb = dom_bgr[::-1]
    return dom_rgb


def _closest_color_name(rgb: np.ndarray) -> str:
    r, g, b = rgb
    best_name, best_dist = "unknown", float("inf")
    for name, (cr, cg, cb) in CSS_COLORS.items():
        dist = (cr - r) ** 2 + (cg - g) ** 2 + (cb - b) ** 2
        if dist < best_dist:
            best_name, best_dist = name, dist
    return best_name

def snapshot_and_detect(db: str, rtsp: str,
                        debug: bool = True,
                        enable_ocr: bool = True) -> VisionResult:
    import cv2, time
    from packages.common.types import Detection, VisionResult

    # 1) Grab frame or image
    if rtsp.lower().endswith((".jpg", ".jpeg", ".png")):
        frame = cv2.imread(rtsp)
        if frame is None:
            raise RuntimeError(f"Failed to read test image: {rtsp}")
        snap_path = rtsp
    else:
        cap = cv2.VideoCapture(rtsp)
        ok, frame = cap.read()
        cap.release()
        if not ok:
            raise RuntimeError("Failed to read from camera")
        ts = int(time.time())
        snap_path = f"/tmp/echo_snap_{ts}.jpg"
        cv2.imwrite(snap_path, frame)

    # 2) YOLO
    res = _MODEL(frame, imgsz=640, conf=0.40, iou=0.45, verbose=False)[0]
    h, w = frame.shape[:2]

    with sqlite3.connect(db) as conn:
        positive_classes = _fetch_vision_map(conn, MODEL_NAME)
        if not positive_classes:
            positive_classes = POSITIVE_CLASSES

        # Debug raw detections
        if debug:
            print("\n[YOLO RAW DETECTIONS]")
            for box, cls_i, score in zip(
                res.boxes.xyxy.cpu().numpy(),
                res.boxes.cls.cpu().numpy(),
                res.boxes.conf.cpu().numpy(),
            ):
                name = res.names[int(cls_i)]
                x1, y1, x2, y2 = [int(v) for v in box.tolist()]
                print(f"{name:>14}  conf={float(score):.3f}  box=({x1},{y1},{x2},{y2})")
            try:
                annotated = res.plot()
                dbg_path = snap_path.rsplit(".", 1)[0] + "_annotated.jpg"
                cv2.imwrite(dbg_path, annotated)
                print(f"[YOLO] Wrote annotated image → {dbg_path}")
            except Exception as e:
                print("[YOLO] Could not write annotated image:", e)

        # 3) Build Detection list
        dets: list[Detection] = []
        labels_for_flags: list[str] = []

        for b, c, score in zip(
            res.boxes.xyxy.cpu().numpy(),
            res.boxes.cls.cpu().numpy(),
            res.boxes.conf.cpu().numpy(),
        ):
            cls_name = res.names[int(c)]
            mapped = positive_classes.get(cls_name)
            if not mapped:
                continue
            min_c = MIN_CONF.get(mapped, 0.25)
            if float(score) < min_c:
                continue

            x1, y1, x2, y2 = map(int, b.tolist())
            x1 = max(0, min(x1, w - 1))
            x2 = max(0, min(x2, w))
            y1 = max(0, min(y1, h - 1))
            y2 = max(0, min(y2, h))

            crop = frame[y1:y2, x1:x2]
            dom_rgb = _dominant_color_rgb(crop)
            color_name = _closest_color_name(dom_rgb)

            if debug:
                print(
                    f"  -> mapped={mapped}, color={color_name}, "
                    f"rgb={dom_rgb.astype(int).tolist()}"
                )

            dets.append(
                Detection(
                    cls=mapped,
                    conf=float(score),
                    box=(x1, y1, x2, y2),
                    color=color_name,
                )
            )
            labels_for_flags.append(mapped)

        flags = _derive_flags(labels_for_flags)

                # --- VisionResult ---
        vr = VisionResult(
            snapshot_path=snap_path,
            detections=dets,
            person_present=flags["person_present"],
            package_box=flags["package_box"],
            vehicle_present=flags["vehicle_present"],
            dog_present=flags["dog_present"],
            uniform=flags["uniform"],
        )

        # --- SceneObjects (1 per detection) + object-level evidence ---
        for obj_id, det in enumerate(dets):
            obj = SceneObject(
                object_id=obj_id,
                label=det.cls.lower(),
                box=det.box,
                parent_id=None,
            )

            # canonical props
            obj.props["color"] = (det.color or "unknown").lower()

            # object evidence
            obj.evidence.append(Evidence(
                source="vision",
                feature="class",
                value=det.cls.lower(),
                conf=float(det.conf),
                object_id=obj_id,
            ))
            obj.evidence.append(Evidence(
                source="vision",
                feature="color",
                value=(det.color or "unknown").lower(),
                conf=0.6,                 # heuristic confidence for color
                object_id=obj_id,
            ))

            vr.objects.append(obj)
            _attach_children(vr.objects)

        # --- Scene-level flag evidence (object_id=None) ---
        if flags["person_present"]:
            vr.evidence.append(Evidence("vision", "person_present", "true", 0.9, object_id=None))
        if flags["package_box"]:
            vr.evidence.append(Evidence("vision", "package_box", "true", 0.9, object_id=None))
        if flags["vehicle_present"]:
            vr.evidence.append(Evidence("vision", "vehicle_present", "true", 0.9, object_id=None))
        if flags["dog_present"]:
            vr.evidence.append(Evidence("vision", "dog_present", "true", 0.9, object_id=None))

        # --- Flatten all object evidence into scene evidence (optional but convenient) ---
        for obj in vr.objects:
            vr.evidence.extend(obj.evidence)


        # 7) OCR → OBJECT-LEVEL evidence
        if enable_ocr and dets:
            ocr_by_obj = extract_ocr_tokens_by_object(frame, dets)

            all_tokens = []

            for obj in vr.objects:
                obj_tokens = ocr_by_obj.get(obj.object_id, [])
                if not obj_tokens:
                    continue

                for tok in obj_tokens:
                    ev = Evidence(
                        source="ocr",
                        feature="token",
                        value=tok,
                        conf=0.9,
                        object_id=obj.object_id,
                    )

                    # attach to object
                    obj.evidence.append(ev)

                    # also attach to scene (flattened)
                    vr.evidence.append(ev)

                    all_tokens.append(tok)

            # optional convenience fields (debug/UI only)
            vr.ocr_tokens = sorted(set(all_tokens))
            vr.ocr_raw = " ".join(vr.ocr_tokens) if vr.ocr_tokens else None

            age_evs = emit_age_evidence_for_people(frame, vr.objects)
            vr.evidence.extend(age_evs)
            for ev in age_evs:
                # also attach to the owning object’s evidence list
                vr.objects[ev.object_id].evidence.append(ev)

    return vr

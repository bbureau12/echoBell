# packages/perception/vision.py
import sqlite3
import os, time
from typing import List
import numpy as np
from ultralytics import YOLO
import cv2
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from .types import Detection, VisionResult

# choose a small model for latency; you can swap to 'yolov11s.pt' later
_MODEL = YOLO("yolov8n.pt")  
MODEL_NAME = "yolov8n"
# Map model classes → our semantic buckets
POSITIVE_CLASSES = {
    "person": "person",
    "microwave": "package",
    "oven": "package",
    "suitcase": "package",
    "truck": "vehicle",
    "car": "vehicle",
    "motorbike": "vehicle",
    "dog": "dog",
    "tie":"tie",
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

def _derive_flags(labels: List[str]) -> dict:
    return {
        "person_present": any(l == "person" for l in labels),
        "package_box": any(l == "package" for l in labels),
        "vehicle_present": any(l == "vehicle" for l in labels),
        "dog_present": any(l == "dog" for l in labels),
        "uniform": None,  # placeholder; see note below
    }
def _fetch_vision_map(conn, model_name: str) -> dict[str, str]:
    rows = conn.execute(
        "SELECT raw_class, semantic_class FROM vision_class_map WHERE enabled=1 AND model_name=?",
        (model_name,),
    ).fetchall()
    return {raw: sem for (raw, sem) in rows}

def _dominant_color_rgb(crop: np.ndarray, k: int = 3) -> np.ndarray:
    """Return dominant color in RGB as a float np.array([R,G,B])."""
    if crop is None or crop.size == 0:
        return np.array([0.0, 0.0, 0.0], dtype=np.float32)

    pixels = crop.reshape(-1, 3).astype(np.float32)

    # K-means on a subsample for speed if needed
    if pixels.shape[0] > 5000:
        idx = np.random.choice(pixels.shape[0], 5000, replace=False)
        pixels = pixels[idx]

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
    _ret, labels, centers = cv2.kmeans(
        pixels, k, None, criteria, 5, cv2.KMEANS_RANDOM_CENTERS
    )
    counts = np.bincount(labels.flatten())
    dom_bgr = centers[np.argmax(counts)]  # [B,G,R]
    dom_rgb = dom_bgr[::-1]              # [R,G,B]
    return dom_rgb

def _closest_color_name(rgb: np.ndarray) -> str:
    r, g, b = rgb
    best_name, best_dist = "unknown", float("inf")
    for name, (cr, cg, cb) in CSS_COLORS.items():
        dist = (cr - r) ** 2 + (cg - g) ** 2 + (cb - b) ** 2
        if dist < best_dist:
            best_name, best_dist = name, dist
    return best_name


def snapshot_and_detect(db: str, rtsp: str, debug: bool = True) -> VisionResult:
    import cv2, time
    from packages.perception.types import Detection, VisionResult  # absolute import avoids relative issue

    # Feed still photo if path ends with image extension; else RTSP frame
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

    # Run YOLO
    res = _MODEL(frame, imgsz=640, conf=0.25, iou=0.45, verbose=False)[0]

    h, w = frame.shape[:2]

    with sqlite3.connect(db) as conn:
        # 1) class mapping
        positive_classes = _fetch_vision_map(conn, MODEL_NAME)
        if len(positive_classes) == 0:
            positive_classes = POSITIVE_CLASSES

        # --- DEBUG: print ALL raw detections before any mapping ---
        if debug:
            print("\n[YOLO RAW DETECTIONS]")
            for box, cls_i, score in zip(res.boxes.xyxy.cpu().numpy(),
                                         res.boxes.cls.cpu().numpy(),
                                         res.boxes.conf.cpu().numpy()):
                name = res.names[int(cls_i)]
                x1, y1, x2, y2 = [int(v) for v in box.tolist()]
                print(f"{name:>14}  conf={float(score):.3f}  box=({x1},{y1},{x2},{y2})")
            # Save an annotated debug image
            try:
                annotated = res.plot()  # returns a numpy image with boxes/labels drawn
                dbg_path = snap_path.rsplit(".", 1)[0] + "_annotated.jpg"
                cv2.imwrite(dbg_path, annotated)
                print(f"[YOLO] Wrote annotated image → {dbg_path}")
            except Exception as e:
                print("[YOLO] Could not write annotated image:", e)

        # 2) Build detections with your mapping
        dets: list[Detection] = []
        labels_for_flags: list[str] = []

        for b, c, score in zip(res.boxes.xyxy.cpu().numpy(),
                               res.boxes.cls.cpu().numpy(),
                               res.boxes.conf.cpu().numpy()):
            cls_name = res.names[int(c)]
            mapped = positive_classes.get(cls_name)
            if not mapped:
                continue

            x1, y1, x2, y2 = map(int, b.tolist())
            # safety clamp
            x1 = max(0, min(x1, w - 1))
            x2 = max(0, min(x2, w))
            y1 = max(0, min(y1, h - 1))
            y2 = max(0, min(y2, h))

            crop = frame[y1:y2, x1:x2]  # BGR
            dom_rgb = _dominant_color_rgb(crop)
            color_name = _closest_color_name(dom_rgb)

            if debug:
                print(f"  -> mapped={mapped}, color={color_name}, rgb={dom_rgb.astype(int).tolist()}")

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

        vr = VisionResult(
            snapshot_path=snap_path,
            detections=dets,
            person_present=flags["person_present"],
            package_box=flags["package_box"],
            vehicle_present=flags["vehicle_present"],
            dog_present=flags["dog_present"],
            uniform=flags["uniform"],
        )

        # 3) Apply DB-driven vision rules
        intent, iconf, iurg = _apply_vision_rules(conn, vr)
        if intent is not None:
            vr.vision_intent = intent
            vr.vision_conf = iconf
            vr.vision_urgency = iurg

    return vr


def _apply_vision_rules(conn: sqlite3.Connection, vr: VisionResult):
    """
    Look up vision_rule rows and see if any match this VisionResult.
    Returns (intent, conf, urgency) or (None, None, None).
    """
    rows = conn.execute("""
        SELECT condition_type, attribute, value, intent_name, conf, urgency
        FROM vision_rule
        ORDER BY id
    """).fetchall()

    for condition_type, attribute, value, intent_name, conf, urgency in rows:
        expected = (value or "").lower()
        matched = False

        # Attribute on VisionResult flags, e.g. person_present, package_box, uniform
        if condition_type == "flag_true":
            actual = getattr(vr, attribute, False)
            matched = bool(actual)

        elif condition_type == "flag_equals":
            actual = getattr(vr, attribute, None)
            if actual is not None:
                matched = str(actual).lower() == expected

        # Any detection whose .color matches
        elif condition_type == "color_equals":
            matched = any(
                (det.color or "").lower() == expected
                for det in vr.detections
            )

        # Any detection whose .cls (semantic class) matches
        elif condition_type == "class_equals":
            matched = any(
                (det.cls or "").lower() == expected
                for det in vr.detections
            )

        # You can add more condition types later (e.g. 'dog_present', 'count_gt', etc.)

        if matched:
            # normalize defaults
            c = float(conf if conf is not None else 0.9)
            u = int(urgency if urgency is not None else 10)
            return intent_name, c, u

    return None, None, None

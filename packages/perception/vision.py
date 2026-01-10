# packages/perception/vision.py
from collections import defaultdict
import sqlite3
import os, time
from typing import List, Optional
import numpy as np
from ultralytics import YOLO
import cv2
import sys, os

import cv2
import numpy as np
from typing import Dict, List

from packages.data.cache.cache import Cache
from packages.perception.plate_heurystics import (
    is_plate_candidate, is_plate_component, group_plate_tokens, 
    select_best_plate, PlateModifiers
)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from packages.common.types import Detection, Evidence, VisionResult, SceneObject
from .ocr import extract_ocr_tokens_by_object
from .age import emit_age_evidence_for_people

# Import torch_utils for safe model loading
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from tools.torch_utils import allowlist_checkpoint_globals
from packages.perception.visitor import process_person_and_emit_evidence
from packages.data.visitor_memory import fetch_best_prior_intent, log_visitor_event_intent

# Allowlist YOLO model for PyTorch 2.6+ "weights_only" loading
allowlist_checkpoint_globals("yolov8n.pt")

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

# Color definitions combining RGB (for nearest-color matching) and HSV ranges (for palette extraction)
COLORS = {
    "black":  {"rgb": (0, 0, 0),         "hsv": ((0, 0, 0), (180, 255, 50))},
    "white":  {"rgb": (255, 255, 255),   "hsv": ((0, 0, 200), (180, 40, 255))},
    "gray":   {"rgb": (128, 128, 128),   "hsv": ((0, 0, 50), (180, 40, 200))},
    "red":    {"rgb": (200, 40, 40),     "hsv": ((160, 80, 50), (10, 255, 255))},
    "orange": {"rgb": (230, 140, 40),    "hsv": ((10, 80, 50), (25, 255, 255))},
    "yellow": {"rgb": (220, 220, 40),    "hsv": ((25, 80, 50), (35, 255, 255))},
    "green":  {"rgb": (40, 160, 40),     "hsv": ((35, 60, 50), (85, 255, 255))},
    "blue":   {"rgb": (40, 80, 200),     "hsv": ((85, 60, 50), (130, 255, 255))},
    "purple": {"rgb": (128, 0, 128),     "hsv": ((130, 60, 50), (160, 255, 255))},
    "brown":  {"rgb": (140, 90, 40),     "hsv": ((10, 60, 20), (30, 200, 160))},  # Fixed: V upper from 100 to 160
    "tan":    {"rgb": (210, 180, 140),   "hsv": None},  # No HSV range for tan
}

# Legacy aliases for backwards compatibility
CSS_COLORS = {name: data["rgb"] for name, data in COLORS.items() if data["rgb"]}
CANONICAL_COLORS = {name: data["hsv"] for name, data in COLORS.items() if data["hsv"]}



MIN_CONF = {
    "person": 0.40,
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

def _bbox_area(b: tuple[int,int,int,int]) -> float:
    x1, y1, x2, y2 = b
    return max(0, x2 - x1) * max(0, y2 - y1)

def _intersection_area(a: tuple[int,int,int,int], b: tuple[int,int,int,int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    return max(0, ix2 - ix1) * max(0, iy2 - iy1)

def _containment_ratio(child_box: tuple[int,int,int,int], parent_box: tuple[int,int,int,int]) -> float:
    """How much of the child is inside the parent: intersection_area / child_area."""
    c_area = _bbox_area(child_box)
    if c_area <= 0:
        return 0.0
    inter = _intersection_area(child_box, parent_box)
    return inter / c_area

def _parse_parent_any_of(s: str) -> set[str]:
    return {t.strip().lower() for t in (s or "").split(",") if t.strip()}

def _attach_children(conn: sqlite3.Connection, objects: list[SceneObject], debug: bool = False) -> None:
    """
    Mutates objects in-place: sets child.parent_id based on attach_rule.
    """
    rows = conn.execute("""
        SELECT child_label, parent_any_of, min_containment, min_parent_conf, prefer_parent
        FROM attach_rule
        WHERE enabled = 1
    """).fetchall()

    if not rows or not objects:
        return

    # index objects by label
    by_label: dict[str, list[SceneObject]] = defaultdict(list)
    for o in objects:
        if o.label:
            by_label[o.label.lower()].append(o)

    for child_label, parent_any_of, min_cont, min_parent_conf, prefer_parent in rows:
        child_label = (child_label or "").strip().lower()
        if not child_label:
            continue

        parents_allowed = _parse_parent_any_of(parent_any_of)
        if not parents_allowed:
            continue

        children = by_label.get(child_label, [])
        if not children:
            continue

        parent_candidates: list[SceneObject] = []
        for p_label in parents_allowed:
            parent_candidates.extend(by_label.get(p_label, []))

        if not parent_candidates:
            continue

        min_cont = float(min_cont or 0.70)
        min_parent_conf = float(min_parent_conf or 0.60)
        prefer_parent = (prefer_parent or "best_score").strip().lower()

        for child in children:
            # already attached? skip (or override if you want)
            if getattr(child, "parent_id", None) is not None:
                continue
            if not getattr(child, "box", None):
                continue

            best_parent = None
            best_score = -1.0

            for parent in parent_candidates:
                if not getattr(parent, "box", None):
                    continue

                p_conf = float(parent.props.get("conf", 0.0) or 0.0)
                if p_conf < min_parent_conf:
                    continue

                ratio = _containment_ratio(child.box, parent.box)
                if ratio < min_cont:
                    continue

                # choose parent scoring strategy
                if prefer_parent == "largest":
                    score = _bbox_area(parent.box)
                elif prefer_parent == "highest_conf":
                    score = p_conf
                else:
                    # "best_score": containment ratio weighted by parent confidence (nice default)
                    score = ratio * p_conf

                if score > best_score:
                    best_score = score
                    best_parent = parent

            if best_parent is not None:
                child.parent_id = best_parent.object_id
                if debug:
                    print(
                        f"[ATTACH] {child.label}#{child.object_id} -> "
                        f"{best_parent.label}#{best_parent.object_id} "
                        f"(score={best_score:.3f})"
                    )


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


def extract_color_palette(
    image_bgr: np.ndarray,
    *,
    min_fraction: float = 0.08,
    blur_kernel: int = 5
) -> Dict[str, float]:
    """
    Extract a palette of canonical colors present in an image.

    Args:
        image_bgr: Cropped image (vehicle or person) in BGR format.
        min_fraction: Minimum fraction of pixels for a color to count.
        blur_kernel: Gaussian blur kernel size (odd number).

    Returns:
        Dict[str, float]: {color_name: fraction_of_pixels}
    """

    if image_bgr is None or image_bgr.size == 0:
        return {}

    # Blur to reduce noise / texture
    if blur_kernel and blur_kernel > 1:
        image_bgr = cv2.GaussianBlur(
            image_bgr,
            (blur_kernel | 1, blur_kernel | 1),
            0
        )

    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)

    total_pixels = hsv.shape[0] * hsv.shape[1]
    if total_pixels == 0:
        return {}

    color_fractions: Dict[str, float] = {}

    for color, (lower, upper) in CANONICAL_COLORS.items():
        lower_np = np.array(lower, dtype=np.uint8)
        upper_np = np.array(upper, dtype=np.uint8)

        # Handle Hue wraparound (e.g., red: 160-10 wraps around 0)
        if lower[0] > upper[0]:  # Hue wraps around
            # Create two masks: [lower[0], 180] and [0, upper[0]]
            mask1 = cv2.inRange(hsv, lower_np, np.array([180, upper[1], upper[2]], dtype=np.uint8))
            mask2 = cv2.inRange(hsv, np.array([0, lower[1], lower[2]], dtype=np.uint8), upper_np)
            mask = cv2.bitwise_or(mask1, mask2)
        else:
            mask = cv2.inRange(hsv, lower_np, upper_np)
        
        count = int(cv2.countNonZero(mask))

        frac = count / total_pixels
        if frac >= min_fraction:
            color_fractions[color] = round(frac, 3)

    return color_fractions

def snapshot_and_detect(
    db: str,
    rtsp: str,
    *,
    camera_id: str | None = None,
    debug: bool = True,
    enable_ocr: bool = True,
    cache: Optional[Cache] = None,
    camera_service = None,
    plate_service = None,
    plate_modifiers: Optional[PlateModifiers] = None,
) -> VisionResult:
    import cv2, time, sqlite3
    from packages.common.types import Detection, VisionResult, Evidence, SceneObject
    from packages.perception.visitor import process_person_and_emit_evidence
    # NOTE: extract_ocr_tokens_by_object, emit_age_evidence_for_people, _attach_children
    # are assumed to already exist in this module, as in your current file. :contentReference[oaicite:1]{index=1}

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
                print(f"  -> mapped={mapped}, color={color_name}, rgb={dom_rgb.astype(int).tolist()}")

            dets.append(
                Detection(
                    cls=mapped,
                    conf=float(score),
                    box=(x1, y1, x2, y2),
                    color=color_name,
                    raw_class=cls_name,  # Preserve original YOLO class
                )
            )
            labels_for_flags.append(mapped)

        flags = _derive_flags(labels_for_flags)

        # 4) VisionResult
        vr = VisionResult(
            snapshot_path=snap_path,
            detections=dets,
            person_present=flags["person_present"],
            package_box=flags["package_box"],
            vehicle_present=flags["vehicle_present"],
            dog_present=flags["dog_present"],
            uniform=flags["uniform"],
        )

        # (Optional) scene metadata evidence (useful once you have two cams)
        if camera_id:
            vr.evidence.append(Evidence("vision", "camera_id", camera_id, 1.0, object_id=None))

        # 5) SceneObjects + base object evidence
        for obj_id, det in enumerate(dets):
            obj = SceneObject(
                object_id=obj_id,
                label=det.cls.lower(),
                box=det.box,
                parent_id=None,
            )

            obj.props["raw_class"] = det.cls.lower()
            obj.props["color"] = (det.color or "unknown").lower()
            obj.props["conf"] = float(det.conf)

            obj.evidence.append(Evidence("vision", "class", det.cls.lower(), float(det.conf), object_id=obj_id))
            obj.evidence.append(Evidence("vision", "color", (det.color or "unknown").lower(), 0.6, object_id=obj_id))

            # If this is a vehicle, emit the specific vehicle type for intent rules
            if det.cls.lower() == "vehicle" and det.raw_class:
                obj.evidence.append(
                    Evidence("vision", "vehicle_type", det.raw_class.lower(), float(det.conf), object_id=obj_id)
                )

            # Extract color palette for vehicles and persons (provides richer color info)
            if det.cls.lower() in ("vehicle", "person"):
                x1, y1, x2, y2 = det.box
                crop = frame[y1:y2, x1:x2]
                palette = extract_color_palette(crop, min_fraction=0.05)  # 5% to catch accent colors like USPS blue stripe
                
                # Add palette evidence for each significant color
                for color, fraction in palette.items():
                    # Confidence reflects how much of the object is this color
                    conf = min(0.95, 0.5 + (fraction * 0.5))  # Scale 0.5-0.95 based on coverage
                    
                    # Evidence 1: Color presence (for "contains blue" rules)
                    obj.evidence.append(Evidence(
                        "vision",
                        "palette_color",
                        color.lower(),
                        conf,
                        object_id=obj_id
                    ))
                    
                    # Evidence 2: Color percentage (for "blue > 50%" rules)
                    # Value is integer percentage (0-100) for easier rule matching
                    percentage = int(fraction * 100)
                    obj.evidence.append(Evidence(
                        "vision",
                        f"color_pct_{color.lower()}",
                        str(percentage),
                        0.95,  # High confidence in the measurement itself
                        object_id=obj_id
                    ))
                    
                    if debug:
                        print(f"  -> palette: {color} ({fraction:.1%}, conf={conf:.2f})")
                
                # Store palette in props for later use
                if palette:
                    obj.props["color_palette"] = palette

            vr.objects.append(obj)

        # 6) Parent/child attach
        _attach_children(conn, vr.objects, debug=debug)

        # 6.5) Visitor recognition (per-person)
        now_ts = int(time.time())
        for obj in vr.objects:
            if obj.label != "person":
                continue

            x1, y1, x2, y2 = obj.box

            match = process_person_and_emit_evidence(
                conn=conn,
                vr=vr,
                frame_bgr=frame,
                person_object_id=obj.object_id,
                person_box=(x1, y1, x2, y2),
                now_ts=now_ts,
                camera_id=int(camera_id) if camera_id is not None else None,
                cache=cache,
                camera_service=camera_service,
            )

            # Convenience props for the pipeline after intent.classify()
            if match and match.visitor_id:
                obj.props["visitor_id"] = match.visitor_id
                obj.props["visitor_kind"] = match.kind
                obj.props["visitor_similarity"] = float(match.similarity or 0.0)
                prior = fetch_best_prior_intent(conn, obj.props["visitor_id"], now_ts=now_ts)
                if prior:
                    vr.evidence.append(Evidence("visitor", "prior_intent", prior.intent, prior.conf, object_id=obj.object_id))

        # 7) Scene-level flags (object_id=None)
        if flags["person_present"]:
            vr.evidence.append(Evidence("vision", "person_present", "true", 0.9, object_id=None))
        if flags["package_box"]:
            vr.evidence.append(Evidence("vision", "package_box", "true", 0.9, object_id=None))
        if flags["vehicle_present"]:
            vr.evidence.append(Evidence("vision", "vehicle_present", "true", 0.9, object_id=None))
        if flags["dog_present"]:
            vr.evidence.append(Evidence("vision", "dog_present", "true", 0.9, object_id=None))

        # 8) OCR → object-level only (no direct vr.evidence append; we'll flatten once)
        # Only perform plate OCR if camera has vehicle detail capability
        allow_plate_ocr = False
        if enable_ocr and camera_service is not None and camera_id is not None:
            cam = camera_service.get_camera(conn, int(camera_id))
            if cam and cam.capability.allow_vehicle_detail:
                allow_plate_ocr = True
        
        if enable_ocr and dets:
            ocr_by_obj = extract_ocr_tokens_by_object(frame, dets)
            all_tokens: list[str] = []

            for obj in vr.objects:
                ocr_tokens = ocr_by_obj.get(obj.object_id, [])
                if not ocr_tokens:
                    continue
                
                # Add all OCR tokens as evidence
                for tok_obj in ocr_tokens:
                    tok = tok_obj.text  # Get the actual text string
                    ev = Evidence("ocr", "token", tok, tok_obj.confidence, object_id=obj.object_id)
                    obj.evidence.append(ev)
                    all_tokens.append(tok)
                
                # Process vehicle plates: group nearby tokens into complete plates
                if obj.label == "vehicle" and allow_plate_ocr:
                    # Use provided modifiers or create default
                    mods = plate_modifiers if plate_modifiers is not None else PlateModifiers()
                    
                    # Get vehicle bounding box for spatial validation
                    vehicle_bbox = obj.box if obj.box else None
                    
                    plate_candidates = group_plate_tokens(ocr_tokens, mods, vehicle_bbox)
                    
                    # Select best plate (prevents logging bumper stickers, multiple misreads, etc.)
                    best_plate = select_best_plate(plate_candidates, mods)
                    
                    if best_plate:
                        # Add plate evidence
                        obj.evidence.append(Evidence(
                            "ocr", 
                            "plate_text", 
                            best_plate.text, 
                            best_plate.confidence, 
                            object_id=obj.object_id
                        ))
                        
                        # Upsert plate to database
                        if plate_service is not None:
                            plate_service.upsert_plate_visit(
                                conn,
                                raw_plate_text=best_plate.text,
                                camera_id=int(camera_id),
                                seen_ts=now_ts,
                            )

            vr.ocr_tokens = sorted(set(all_tokens))
            vr.ocr_raw = " ".join(vr.ocr_tokens) if vr.ocr_tokens else None

        # 9) Age evidence (independent of OCR; object-level only, then flatten)
        age_evs = emit_age_evidence_for_people(frame, vr.objects)
        for ev in age_evs:
            # attach to owning object’s evidence list
            if ev.object_id is not None and 0 <= ev.object_id < len(vr.objects):
                vr.objects[ev.object_id].evidence.append(ev)

        # 10) Flatten ONCE at the end
        for obj in vr.objects:
            vr.evidence.extend(obj.evidence)

    return vr

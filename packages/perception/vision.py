# packages/perception/vision.py
import os, time
from typing import List
from ultralytics import YOLO
import cv2
from .types import Detection, VisionResult

# choose a small model for latency; you can swap to 'yolov11s.pt' later
_MODEL = YOLO(os.environ.get("ECHO_YOLO_MODEL", "yolov11n.pt"))

# Map model classes → our semantic buckets
POSITIVE_CLASSES = {
    "person": "person",
    "box": "package",
    "suitcase": "package",
    "truck": "vehicle",
    "car": "vehicle",
    "motorbike": "vehicle",
    "dog": "dog",
}

def _derive_flags(labels: List[str]) -> dict:
    return {
        "person_present": any(l == "person" for l in labels),
        "package_box": any(l == "package" for l in labels),
        "vehicle_present": any(l == "vehicle" for l in labels),
        "dog_present": any(l == "dog" for l in labels),
        "uniform": None,  # placeholder; see note below
    }

def snapshot_and_detect(rtsp: str) -> VisionResult:
    import cv2, time
    from .types import Detection, VisionResult

    # 🟩 Option A — feed a still photo instead of using the camera
    if rtsp.endswith(".jpg") or rtsp.endswith(".png"):
        frame = cv2.imread(rtsp)
        if frame is None:
            raise RuntimeError(f"Failed to read test image: {rtsp}")
        snap_path = rtsp  # already on disk, no need to save again

    else:
        # 🟦 Option B — grab a frame from a live camera (your original code)
        cap = cv2.VideoCapture(rtsp)
        ok, frame = cap.read()
        cap.release()
        if not ok:
            raise RuntimeError("Failed to read from camera")

        ts = int(time.time())
        snap_path = f"/tmp/echo_snap_{ts}.jpg"
        cv2.imwrite(snap_path, frame)

    # Run detector (unchanged)
    res = _MODEL(frame, imgsz=640, conf=0.25, iou=0.45, verbose=False)[0]

    dets: list[Detection] = []
    # ... continue building dets and Vis
    labels_for_flags: List[str] = []

    for b, c, conf in zip(res.boxes.xyxy.cpu().numpy(),
                          res.boxes.cls.cpu().numpy(),
                          res.boxes.conf.cpu().numpy()):
        cls_name = res.names[int(c)]
        # collapse to our buckets
        mapped = POSITIVE_CLASSES.get(cls_name)
        if not mapped:
            continue
        x1, y1, x2, y2 = map(int, b.tolist())
        dets.append(Detection(cls=mapped, conf=float(conf), box=(x1,y1,x2,y2)))
        labels_for_flags.append(mapped)

    flags = _derive_flags(labels_for_flags)

    return VisionResult(
        snapshot_path=snap_path,
        detections=dets,
        person_present=flags["person_present"],
        package_box=flags["package_box"],
        vehicle_present=flags["vehicle_present"],
        dog_present=flags["dog_present"],
        uniform=flags["uniform"],
    )
